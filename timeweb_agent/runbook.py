"""Исполнитель сценариев (runbook) — пошаговые планы развёртывания.

Позволяет описать план в YAML и выполнить его целиком:

    python -m timeweb_agent run timeweb_agent/examples/deploy-website.yaml

Формат файла:

    name: Развернуть сайт
    vars:
      domain: example.ru
    steps:
      - name: Создать сервер
        action: servers.create          # действие из реестра
        with: {name: web-1, os: auto, preset: auto, wait: true}
        save: {as: server, field: id}   # сохранить результат для следующих шагов
      - action: dns.add
        with:
          fqdn: "{{ vars.domain }}"
          type: A
          value: "{{ server.ip }}"
      - action: deploy.website
        with: {server: web-1, path: ./site, domain: "{{ vars.domain }}", ssl: true}

Подстановки: {{ vars.X }}, {{ имя_сохранённого }}, {{ имя.поле }}, {{ env.NAME }}.
"""
from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from . import api, config, deploy, verify
from .client import TimewebClient
from .ssh import SSHClient, SSHError

_SUB = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


class RunbookError(RuntimeError):
    pass


# ---------------------------------------------------------------------- #
#  Подстановки
# ---------------------------------------------------------------------- #
def _resolve_expr(expr: str, ctx: dict) -> Any:
    expr = expr.strip()
    parts = expr.split(".")
    if parts[0] == "vars":
        cur: Any = ctx["vars"]
        rest = parts[1:]
    elif parts[0] == "env":
        return os.environ.get(".".join(parts[1:]))
    else:
        cur = ctx["saved"].get(parts[0])
        rest = parts[1:]
        if cur is None:
            cur = ctx["vars"].get(parts[0])
    for p in rest:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                cur = None
        else:
            cur = None
    return cur


def render(value: Any, ctx: dict) -> Any:
    if isinstance(value, str):
        return _SUB.sub(lambda m: str(_resolve_expr(m.group(1), ctx)), value)
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------- #
#  SSH-клиент для шага деплоя
# ---------------------------------------------------------------------- #
def ssh_for(params: dict, client: TimewebClient) -> SSHClient:
    """Строит SSHClient из параметров шага (server/host) или .env."""
    host = params.get("host") or config.SSH_HOST
    if not host and params.get("server"):
        server = api.resolve_server(client, str(params["server"]))
        if not server:
            raise RunbookError(f"Сервер не найден: {params['server']}")
        host = api.server_ip(server) or (server.get("ips") or [{}])[0].get("ip")
    if not host:
        raise SSHError("Не указан SSH-хост (TW_SSH_HOST или параметр host/server)")
    return SSHClient(
        host=str(host),
        user=params.get("ssh_user") or config.SSH_USER,
        port=int(params.get("ssh_port") or config.SSH_PORT),
        password=params.get("ssh_password") or config.SSH_PASSWORD,
        key_path=params.get("ssh_key_path") or config.SSH_KEY_PATH,
        key_passphrase=params.get("ssh_key_passphrase") or config.SSH_KEY_PASSPHRASE,
    )


def _ssh_for(params: dict, client: TimewebClient) -> SSHClient:
    return ssh_for(params, client)


# ---------------------------------------------------------------------- #
#  Реестр действий
# ---------------------------------------------------------------------- #
def _resolve_server_arg(client: TimewebClient, value: Any) -> Any:
    if isinstance(value, str) and not str(value).isdigit():
        server = api.resolve_server(client, value)
        if server:
            return server.get("id")
    return value


def _resolve_db_arg(client: TimewebClient, value: Any) -> Any:
    if isinstance(value, str) and not str(value).isdigit():
        db = api.resolve_database(client, value)
        if db:
            return db.get("id")
    return value


ACTIONS: dict[str, Any] = {}


def action(name: str):
    def deco(fn):
        ACTIONS[name] = fn
        return fn
    return deco


@action("echo")
def _echo(client, ctx, p):
    print(p.get("text", ""), flush=True)
    return {"text": p.get("text", "")}


@action("sleep")
def _sleep(client, ctx, p):
    seconds = float(p.get("seconds", 1))
    print(f"[sleep] {seconds} с", flush=True)
    time.sleep(seconds)
    return {"seconds": seconds}


@action("projects.create")
def _project_create(client, ctx, p):
    project = api.create_project(client, str(p["name"]), description=p.get("description"))
    return {"project": project, **project}


@action("sshkeys.ensure")
def _sshkeys_ensure(client, ctx, p):
    key = api.ensure_ssh_key(client, key_name=str(p.get("name", "timeweb-agent")))
    return {"ssh_key": key, **key}


@action("servers.list")
def _servers_list(client, ctx, p):
    servers = api.list_servers(client, search=p.get("search"))
    return {"servers": servers}


@action("servers.create")
def _servers_create(client, ctx, p):
    existing = api.resolve_server(client, str(p["name"]))
    if existing:
        print(f"[skip] Сервер «{p['name']}» уже существует (id={existing.get('id')}) — использую его", flush=True)
        existing = dict(existing)
        existing["ip"] = api.server_ip(existing)
        return {"server": existing, **existing}
    ssh_arg = p.get("ssh_key") or p.get("ssh_key_ids")
    ssh_key_ids = None
    if ssh_arg == "auto":
        key = api.ensure_ssh_key(client)
        ssh_key_ids = [key.get("id")]
    elif isinstance(ssh_arg, dict):
        ssh_key_ids = [ssh_arg.get("id")]
    elif ssh_arg:
        ssh_key_ids = list(ssh_arg) if isinstance(ssh_arg, list) else [ssh_arg]
    server = api.create_server(
        client,
        name=str(p["name"]),
        os_id=str(p.get("os", "auto")),
        preset_id=str(p.get("preset", "auto")),
        ssh_key_ids=ssh_key_ids,
        project_id=p.get("project_id") or (p.get("project", {}) or {}).get("id"),
        is_ddos_guard=p.get("ddos"),
        cloud_init=p.get("cloud_init"),
        comment=p.get("comment"),
        wait=bool(p.get("wait", True)),
        wait_timeout=int(p.get("wait_timeout", 900)),
        verbose=bool(p.get("verbose")),
    )
    if p.get("wait", True):
        server = dict(server)
        server["ip"] = api.server_ip(server)
    return {"server": server, **server}


@action("servers.wait")
def _servers_wait(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    server = api.wait_server(client, sid, timeout=int(p.get("timeout", 900)))
    return {"server": server, **server}


@action("servers.reboot")
def _servers_reboot(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    api.server_action(client, sid, "reboot")
    return {"status": "rebooting"}


@action("servers.stop")
def _servers_stop(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    api.server_action(client, sid, "shutdown")
    return {"status": "stopping"}


@action("servers.start")
def _servers_start(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    api.server_action(client, sid, "start")
    return {"status": "starting"}


@action("servers.reset-password")
def _servers_reset_password(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    data = api.reset_server_password(client, sid)
    return {"password": data, **data}


@action("servers.delete")
def _servers_delete(client, ctx, p):
    sid = _resolve_server_arg(client, p["server"])
    api.delete_server(client, sid)
    return {"deleted": sid}


@action("db.list")
def _db_list(client, ctx, p):
    dbs = api.list_databases(client)
    return {"databases": dbs}


@action("db.create")
def _db_create(client, ctx, p):
    existing = api.resolve_database(client, str(p["name"]))
    if existing:
        print(
            f"[skip] Кластер БД «{p['name']}» уже существует (id={existing.get('id')}) — использую его. "
            "Пароль администратора возьмите из панели (API его не возвращает для существующих кластеров).",
            flush=True,
        )
        result = {"database": existing, **existing}
        result["connection"] = api.db_connection_info(existing)
        return result
    db = api.create_database(
        client,
        name=str(p["name"]),
        db_type=str(p.get("type", "mysql")),
        admin_login=str(p.get("admin_login", "admin")),
        admin_password=p.get("admin_password"),
        preset_id=str(p.get("preset", "auto")),
        instance_name=p.get("instance_name"),
        project_id=p.get("project_id"),
        description=p.get("description"),
        wait=bool(p.get("wait", True)),
        wait_timeout=int(p.get("wait_timeout", 900)),
    )
    conn = api.db_connection_info(db)
    result = {"database": db, **db}
    result["connection"] = conn
    result["admin_password"] = db.get("_admin_password")
    return result


@action("db.add-admin")
def _db_add_admin(client, ctx, p):
    db_id = _resolve_db_arg(client, p["db"])
    admin = api.add_db_admin(
        client, db_id,
        login=str(p["login"]),
        password=p.get("password"),
        host=p.get("host"),
        instance_id=p.get("instance_id"),
        privileges=p.get("privileges"),
    )
    return {"admin": admin, **admin}


@action("db.add-instance")
def _db_add_instance(client, ctx, p):
    db_id = _resolve_db_arg(client, p["db"])
    inst = api.add_db_instance(client, db_id, str(p["name"]), description=p.get("description"))
    return {"instance": inst, **inst}


@action("db.delete")
def _db_delete(client, ctx, p):
    db_id = _resolve_db_arg(client, p["db"])
    api.delete_database(client, db_id)
    return {"deleted": db_id}


@action("dns.add")
def _dns_add(client, ctx, p):
    rec = api.add_dns_record(
        client,
        fqdn=str(p["fqdn"]),
        rtype=str(p["type"]),
        value=str(p["value"]),
        ttl=p.get("ttl"),
        app_id=p.get("app_id"),
    )
    return {"dns_record": rec, **rec}


@action("dns.delete")
def _dns_delete(client, ctx, p):
    api.delete_dns_record(client, str(p["fqdn"]), p["record_id"])
    return {"deleted": p["record_id"]}


@action("domains.check")
def _domains_check(client, ctx, p):
    available = api.check_domain(client, str(p["fqdn"]))
    return {"fqdn": p["fqdn"], "available": available}


@action("domains.add")
def _domains_add(client, ctx, p):
    domain = api.add_domain(client, str(p["fqdn"]))
    return {"domain": domain, **domain}


@action("apps.create")
def _apps_create(client, ctx, p):
    framework_id = p.get("framework_id")
    if not framework_id and p.get("framework") == "auto":
        framework = api.pick_framework(client, str(p.get("type", "backend")), language=p.get("language"))
        framework_id = framework.get("id") if framework else None
    app = api.create_app(
        client,
        name=str(p["name"]),
        app_type=str(p["type"]),
        provider_id=p["provider_id"],
        repository_id=p["repository_id"],
        branch_name=str(p.get("branch", "main")),
        framework_id=framework_id,
        build_cmd=p.get("build_cmd"),
        run_cmd=p.get("run_cmd"),
        index_dir=p.get("index_dir"),
        envs=p.get("envs"),
        preset_id=p.get("preset_id"),
        is_auto_deploy=bool(p.get("auto_deploy")),
        project_id=p.get("project_id"),
        comment=p.get("comment"),
    )
    return {"app": app, **app}


@action("apps.deploy")
def _apps_deploy(client, ctx, p):
    app_id = p["app"]
    if isinstance(app_id, dict):
        app_id = app_id.get("id")
    deploy_result = api.deploy_app(client, app_id, commit_sha=p.get("commit_sha"))
    return {"deploy": deploy_result, **deploy_result}


@action("ssh.exec")
def _ssh_exec(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        code, out, err = ssh.exec(str(p["command"]), check=not bool(p.get("ignore_errors")))
    return {"exit_code": code, "stdout": out, "stderr": err}


@action("deploy.provision")
def _deploy_provision(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        deploy.provision(ssh, with_docker=bool(p.get("docker", True)), with_fail2ban=bool(p.get("fail2ban", True)))
    return {"status": "provisioned"}


@action("deploy.website")
def _deploy_website(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        deploy.deploy_static_site(
            ssh,
            local_dir=p["path"],
            domain=str(p["domain"]),
            ssl=bool(p.get("ssl", True)),
            ssl_email=p.get("ssl_email"),
        )
    return {"status": "deployed", "domain": p["domain"]}


@action("deploy.docker")
def _deploy_docker(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        deploy.deploy_docker_app(
            ssh,
            local_dir=p["path"],
            domain=str(p["domain"]),
            port=int(p.get("port", 8000)),
            app_name=p.get("app_name"),
            ssl=bool(p.get("ssl", True)),
            ssl_email=p.get("ssl_email"),
            compose_file=p.get("compose_file", "docker-compose.yml"),
        )
    return {"status": "deployed", "domain": p["domain"]}


@action("deploy.git")
def _deploy_git(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        deploy.deploy_from_git(
            ssh,
            repo=str(p["repo"]),
            branch=str(p.get("branch", "main")),
            domain=p.get("domain"),
            port=int(p.get("port", 8000)),
            app_name=p.get("app_name"),
            ssl=bool(p.get("ssl", True)),
            ssl_email=p.get("ssl_email"),
            compose_file=p.get("compose_file", "docker-compose.yml"),
        )
    return {"status": "deployed", "repo": p["repo"]}


@action("deploy.mysql")
def _deploy_mysql(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        info = deploy.deploy_mysql(
            ssh,
            db_name=str(p["name"]),
            db_user=str(p.get("user", "app")),
            db_password=p.get("password"),
            port=int(p.get("port", 3306)),
            volume_name=p.get("volume_name"),
        )
    return {"mysql": info, **info}


@action("deploy.postgres")
def _deploy_postgres(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        info = deploy.deploy_postgres(
            ssh,
            db_name=str(p["name"]),
            db_user=str(p.get("user", "app")),
            db_password=p.get("password"),
            port=int(p.get("port", 5432)),
            volume_name=p.get("volume_name"),
        )
    return {"postgres": info, **info}


@action("deploy.redis")
def _deploy_redis(client, ctx, p):
    ssh = _ssh_for(p, client)
    with ssh:
        info = deploy.deploy_redis(
            ssh,
            name=str(p.get("name", "redis")),
            password=p.get("password"),
            port=int(p.get("port", 6379)),
            volume_name=p.get("volume_name"),
        )
    return {"redis": info, **info}


@action("check")
def _check(client, ctx, p):
    """Универсальная проверка: {kind: http|dns|command|docker|postgres|mysql|redis|nginx, ...}"""
    kind = str(p["kind"])
    ssh = None
    if kind not in {"http", "dns"}:
        ssh = _ssh_for(p, client)
    result = verify.run_check(kind, p, ssh=ssh)
    print(f"[check] {kind}: {'✓' if result['ok'] else '✗'} {result['detail'][:120]}", flush=True)
    return {"check": result, **result}


# ---------------------------------------------------------------------- #
#  Выполнение
# ---------------------------------------------------------------------- #
def _when_true(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text not in {"", "false", "0", "no", "none", "null", "нет", "ложь"}


def execute_step(
    client: TimewebClient,
    ctx: dict,
    step: dict,
    verbose: bool = False,
) -> Any:
    """Выполняет один шаг плана (с ретраями и сохранением результата).

    ctx = {"vars": {...}, "saved": {...}}. Мутирует ctx["saved"].
    """
    if not isinstance(step, dict):
        raise RunbookError(f"Шаг: ожидается объект, получено {type(step)}")
    name = step.get("name") or step.get("action") or "шаг"
    action_name = step.get("action")
    if not action_name:
        raise RunbookError(f"Шаг ({name}): не указано поле action")
    if action_name not in ACTIONS:
        raise RunbookError(
            f"Шаг ({name}): неизвестное действие «{action_name}». "
            f"Доступны: {', '.join(sorted(ACTIONS))}"
        )
    if step.get("when") is not None and not _when_true(render(step["when"], ctx)):
        print(f"[skip] {name}", flush=True)
        return None
    params = render(step.get("with") or {}, ctx)
    retries = int(step.get("retries", 0))
    last_error: Optional[Exception] = None
    result = None
    for attempt in range(retries + 1):
        try:
            print(f"[run] {name} ({action_name})", flush=True)
            result = ACTIONS[action_name](client, ctx, params)
            save = step.get("save")
            if save and isinstance(result, dict):
                as_name = save.get("as")
                field = save.get("field")
                if as_name:
                    value = result.get(field) if field else result
                    ctx["saved"][as_name] = value
                    if verbose:
                        print(f"[save] {as_name} = {value}", flush=True)
            last_error = None
            break
        except Exception as e:  # noqa: BLE001 — ретраи по желанию автора сценария
            last_error = e
            if attempt < retries:
                delay = int(step.get("retry_delay", 15))
                print(f"[warn] {name}: {e}; повтор через {delay} с (попытка {attempt + 2}/{retries + 1})", flush=True)
                time.sleep(delay)
    if last_error is not None and not step.get("ignore_errors"):
        raise RunbookError(f"Шаг ({name}) не выполнен: {last_error}") from last_error
    if last_error is not None:
        print(f"[warn] {name}: ошибка проигнорирована: {last_error}", flush=True)
        result = {"error": str(last_error), "ignored": True}
    return result


def execute(
    client: TimewebClient,
    steps: list,
    vars_: Optional[dict] = None,
    verbose: bool = False,
) -> dict:
    ctx: dict = {"vars": vars_ or {}, "saved": {}}
    for i, step in enumerate(steps, 1):
        execute_step(client, ctx, step, verbose=verbose)
    return ctx["saved"]


def load_runbook(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise RunbookError(f"Файл сценария не найден: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RunbookError(f"Ошибка разбора YAML: {e}") from e
    if not isinstance(data, dict) or "steps" not in data:
        raise RunbookError("Сценарий должен быть объектом с ключом steps")
    return data


def generate_password(length: int = 20) -> str:
    return secrets.token_urlsafe(length)
