"""CLI агента Timeweb Cloud.

Использование:
    python -m timeweb_agent <команда> [аргументы]
    python -m timeweb_agent doctor
    python -m timeweb_agent servers list
    python -m timeweb_agent run plan.yaml

Глобальные флаги (перед командой): --json, -v, --yes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from . import api, config, deploy, runbook
from .client import TimewebClient, TimewebError
from .ssh import SSHClient

SECRET_HINTS = ("password", "token", "secret", "passphrase")


# ---------------------------------------------------------------------- #
#  Вывод
# ---------------------------------------------------------------------- #
def redact(obj: Any, show_secrets: bool = False) -> Any:
    if show_secrets:
        return obj
    if isinstance(obj, dict):
        return {
            k: ("***" if any(h in str(k).lower() for h in SECRET_HINTS) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def print_json(data: Any, show_secrets: bool = False) -> None:
    print(json.dumps(redact(data, show_secrets), ensure_ascii=False, indent=2, default=str))


def print_table(items: list, columns: list[str]) -> None:
    if not items:
        print("(пусто)")
        return
    headers = []
    for c in columns:
        title = c
        headers.append(title)
    rows = []
    for it in items:
        row = []
        for c in columns:
            value = it.get(c) if isinstance(it, dict) else getattr(it, c, None)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            row.append("" if value is None else str(value))
        rows.append(row)
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))


def print_dict(data: dict, indent: int = 0) -> None:
    pad = " " * indent
    for k, v in data.items():
        if isinstance(v, dict):
            print(f"{pad}{k}:")
            print_dict(v, indent + 2)
        elif isinstance(v, list):
            print(f"{pad}{k}: {len(v)} элементов")
        else:
            print(f"{pad}{k}: {v}")


def emit(data: Any, args: argparse.Namespace) -> None:
    """Печатает результат: JSON при --json/TW_JSON, иначе по-человечески."""
    if getattr(args, "json", False) or config.JSON_OUTPUT:
        print_json(data, show_secrets=getattr(args, "show_secrets", False))
        return
    if data is None:
        return
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            keys = sorted({k for d in data for k in d.keys()})
            priority = ["id", "name", "fqdn", "type", "status", "location", "price"]
            cols = [k for k in priority if k in keys] + [k for k in keys if k not in priority][:6]
            print_table(data, cols)
        else:
            for v in data:
                print(v)
    elif isinstance(data, dict):
        print_dict(redact(data, getattr(args, "show_secrets", False)))
    else:
        print(data)


def confirm(args: argparse.Namespace, action_desc: str) -> bool:
    if getattr(args, "yes", False) or config.AUTO_YES:
        return True
    if not sys.stdin.isatty():
        print(
            f"[отмена] Действие «{action_desc}» требует подтверждения. "
            f"Запустите с флагом --yes или установите TW_YES=1.",
            file=sys.stderr,
        )
        return False
    answer = input(f"Подтвердите действие «{action_desc}» [y/N]: ").strip().lower()
    return answer in {"y", "yes", "д", "да"}


# ---------------------------------------------------------------------- #
#  Фабрика клиента
# ---------------------------------------------------------------------- #
def make_client(args: argparse.Namespace) -> TimewebClient:
    token = config.require_token()
    return TimewebClient(
        token=token,
        base_url=config.API_BASE_URL,
        timeout=config.API_TIMEOUT,
        retries=config.API_RETRIES,
        verbose=bool(getattr(args, "verbose", False)),
    )


def get_ssh(args: argparse.Namespace, params: Optional[dict] = None) -> SSHClient:
    params = params or {}
    host = getattr(args, "host", None) or params.get("host") or config.SSH_HOST
    if not host and getattr(args, "server", None):
        server = api.resolve_server(make_client(args), str(args.server))
        if not server:
            raise SystemExit(f"Сервер не найден: {args.server}")
        host = api.server_ip(server)
    if not host:
        raise SystemExit(
            "Не задан SSH-хост: укажите --host, --server (имя сервера в панели) "
            "или переменную TW_SSH_HOST в .env"
        )
    return SSHClient(
        host=str(host),
        user=params.get("ssh_user") or config.SSH_USER,
        port=int(params.get("ssh_port") or config.SSH_PORT),
        password=params.get("ssh_password") or config.SSH_PASSWORD,
        key_path=params.get("ssh_key_path") or config.SSH_KEY_PATH,
        key_passphrase=params.get("ssh_key_passphrase") or config.SSH_KEY_PASSPHRASE,
    )


# ---------------------------------------------------------------------- #
#  Команды
# ---------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace) -> None:
    client = make_client(args)
    status = api.account_status(client)
    result: dict = {"account": status}
    for label, fn in [
        ("projects", api.list_projects),
        ("servers", api.list_servers),
        ("databases", api.list_databases),
        ("apps", api.list_apps),
        ("domains", api.list_domains),
        ("ssh_keys", api.list_ssh_keys),
    ]:
        try:
            items = fn(client)
            result[label] = {"count": len(items), "names": [i.get("name") or i.get("fqdn") or i.get("id") for i in items]}
        except TimewebError as e:
            result[label] = {"error": str(e)}
    emit(result, args)
    if not (getattr(args, "json", False) or config.JSON_OUTPUT):
        blocked = ((status or {}).get("is_blocked")) if isinstance(status, dict) else None
        if blocked:
            print("⚠️  Аккаунт заблокирован!", file=sys.stderr)


def cmd_projects(args: argparse.Namespace) -> None:
    client = make_client(args)
    if args.sub == "list":
        emit(api.list_projects(client), args)
    elif args.sub == "create":
        emit(api.create_project(client, args.name, description=args.description), args)


def cmd_os(args: argparse.Namespace) -> None:
    emit(api.list_os(make_client(args)), args)


def cmd_presets(args: argparse.Namespace) -> None:
    client = make_client(args)
    kind = args.kind
    if kind == "servers":
        emit(api.list_server_presets(client), args)
    elif kind == "dbs":
        emit(api.list_db_presets(client), args)
    elif kind == "apps":
        emit(api.list_app_presets(client), args)
    else:
        emit(client.get(f"/presets/{kind}"), args)


def cmd_ssh_keys(args: argparse.Namespace) -> None:
    client = make_client(args)
    if args.sub == "list":
        emit(api.list_ssh_keys(client), args)
    elif args.sub == "add":
        body = args.public_key or Path(args.pubkey_file).read_text().strip()
        emit(api.add_ssh_key(client, args.name, body), args)
    elif args.sub == "ensure":
        emit(api.ensure_ssh_key(client, args.name), args)
    elif args.sub == "delete":
        key = api.find_ssh_key(client, args.key)
        if not key:
            raise SystemExit(f"SSH-ключ не найден: {args.key}")
        if confirm(args, f"удалить SSH-ключ {key.get('name')} (id={key.get('id')})"):
            emit(client.delete(f"/ssh-keys/{key['id']}"), args)


def cmd_servers(args: argparse.Namespace) -> None:
    client = make_client(args)
    sub = args.sub
    if sub == "list":
        emit(api.list_servers(client, search=args.search), args)
        return
    if sub == "create":
        ssh_key_ids = None
        if args.ssh_key == "auto":
            key = api.ensure_ssh_key(client)
            ssh_key_ids = [key.get("id")]
        elif args.ssh_key:
            key = api.find_ssh_key(client, args.ssh_key)
            if not key:
                raise SystemExit(f"SSH-ключ не найден: {args.ssh_key}")
            ssh_key_ids = [key.get("id")]
        if confirm(args, f"создать облачный сервер «{args.name}» (это платная операция)"):
            server = api.create_server(
                client,
                name=args.name,
                os_id=args.os,
                preset_id=args.preset,
                ssh_key_ids=ssh_key_ids,
                project_id=args.project_id,
                is_ddos_guard=args.ddos,
                comment=args.comment,
                wait=not args.no_wait,
                wait_timeout=args.wait_timeout,
                verbose=args.verbose,
            )
            if not args.no_wait and not (args.json or config.JSON_OUTPUT):
                server = dict(server)
                server["ip"] = api.server_ip(server)
            emit(server, args)
        return
    if sub == "get":
        server = api.resolve_server(client, args.server)
        if not server:
            raise SystemExit(f"Сервер не найден: {args.server}")
        emit(api.get_server(client, server.get("id")), args)
        return
    server = api.resolve_server(client, args.server)
    if not server:
        raise SystemExit(f"Сервер не найден: {args.server}")
    sid = server.get("id")
    if sub == "delete":
        if confirm(args, f"удалить сервер {server.get('name')} (id={sid}) БЕЗВОЗВРАТНО"):
            emit(api.delete_server(client, sid), args)
    elif sub == "wait":
        emit(api.wait_server(client, sid, timeout=args.timeout, verbose=args.verbose), args)
    elif sub in {"reboot", "start", "stop", "hard-reboot", "hard-shutdown"}:
        action = "shutdown" if sub == "stop" else sub
        if confirm(args, f"{action} сервера {server.get('name')}"):
            emit(api.server_action(client, sid, action), args)
    elif sub == "reset-password":
        if confirm(args, f"сбросить root-пароль сервера {server.get('name')}"):
            emit(api.reset_server_password(client, sid), args)
    elif sub == "logs":
        emit(api.server_logs(client, sid), args)
    elif sub == "ip":
        emit(api.get_server_ips(client, sid), args)


def cmd_db(args: argparse.Namespace) -> None:
    client = make_client(args)
    sub = args.sub

    def db_id(value: str):
        db = api.resolve_database(client, value)
        if not db:
            raise SystemExit(f"Кластер БД не найден: {value}")
        return db.get("id")

    if sub == "types":
        emit(api.list_db_types(client), args)
    elif sub == "presets":
        emit(api.list_db_presets(client), args)
    elif sub == "list":
        emit(api.list_databases(client), args)
    elif sub == "create":
        if confirm(args, f"создать кластер БД «{args.name}» ({args.type}) — платная операция"):
            db = api.create_database(
                client,
                name=args.name,
                db_type=args.type,
                admin_login=args.admin_login,
                admin_password=args.admin_password,
                preset_id=args.preset,
                instance_name=args.instance_name,
                project_id=args.project_id,
                wait=not args.no_wait,
                wait_timeout=args.wait_timeout,
                verbose=args.verbose,
            )
            result = {k: v for k, v in db.items() if not str(k).startswith("_")}
            result["admin_password"] = db.get("_admin_password")
            result["connection"] = api.db_connection_info(db)
            emit(result, args)
    elif sub == "get":
        emit(api.get_database(client, db_id(args.db)), args)
    elif sub == "delete":
        if confirm(args, f"удалить кластер БД {args.db} (id={db_id(args.db)}) БЕЗВОЗВРАТНО"):
            emit(api.delete_database(client, db_id(args.db)), args)
    elif sub == "admins":
        emit(api.list_db_admins(client, db_id(args.db)), args)
    elif sub == "add-admin":
        emit(api.add_db_admin(client, db_id(args.db), args.login, password=args.password, host=args.host), args)
    elif sub == "instances":
        emit(api.list_db_instances(client, db_id(args.db)), args)
    elif sub == "add-instance":
        emit(api.add_db_instance(client, db_id(args.db), args.name), args)
    elif sub == "wait":
        emit(api.wait_database(client, db_id(args.db), timeout=args.timeout, verbose=args.verbose), args)


def cmd_domains(args: argparse.Namespace) -> None:
    client = make_client(args)
    if args.sub == "list":
        emit(api.list_domains(client), args)
    elif args.sub == "check":
        emit(api.check_domain(client, args.fqdn), args)
    elif args.sub == "add":
        if confirm(args, f"добавить домен {args.fqdn} на аккаунт (регистрация может быть платной)"):
            emit(api.add_domain(client, args.fqdn), args)
    elif args.sub == "delete":
        if confirm(args, f"удалить домен {args.fqdn}"):
            emit(api.delete_domain(client, args.fqdn), args)


def cmd_dns(args: argparse.Namespace) -> None:
    client = make_client(args)
    if args.sub == "list":
        emit(api.list_dns_records(client, args.fqdn), args)
    elif args.sub == "add":
        emit(api.add_dns_record(client, args.fqdn, args.type, args.value, ttl=args.ttl, app_id=args.app_id), args)
    elif args.sub == "update":
        fields = {}
        if args.value:
            fields["value"] = args.value
        if args.ttl:
            fields["ttl"] = args.ttl
        if not fields:
            raise SystemExit("Для обновления укажите --value и/или --ttl")
        emit(api.update_dns_record(client, args.fqdn, args.record_id, **fields), args)
    elif args.sub == "delete":
        if confirm(args, f"удалить DNS-запись {args.record_id} домена {args.fqdn}"):
            emit(api.delete_dns_record(client, args.fqdn, args.record_id), args)


def cmd_apps(args: argparse.Namespace) -> None:
    client = make_client(args)
    sub = args.sub
    if sub == "list":
        emit(api.list_apps(client), args)
    elif sub == "frameworks":
        emit(api.list_frameworks(client), args)
    elif sub == "presets":
        emit(api.list_app_presets(client), args)
    elif sub == "get":
        emit(api.get_app(client, args.app), args)
    elif sub == "create":
        if confirm(args, f"создать приложение «{args.name}» — платная операция"):
            emit(
                api.create_app(
                    client,
                    name=args.name,
                    app_type=args.type,
                    provider_id=args.provider_id,
                    repository_id=args.repository_id,
                    branch_name=args.branch,
                    framework_id=args.framework_id,
                    build_cmd=args.build_cmd,
                    run_cmd=args.run_cmd,
                    index_dir=args.index_dir,
                    envs=json.loads(args.envs) if args.envs else None,
                    preset_id=args.preset_id,
                    is_auto_deploy=args.auto_deploy,
                    project_id=args.project_id,
                    comment=args.comment,
                ),
                args,
            )
    elif sub == "deploy":
        app = api.resolve_app(client, args.app)
        if not app:
            raise SystemExit(f"Приложение не найдено: {args.app}")
        emit(api.deploy_app(client, app.get("id"), commit_sha=args.commit_sha), args)
    elif sub == "logs":
        app = api.resolve_app(client, args.app)
        if not app:
            raise SystemExit(f"Приложение не найдено: {args.app}")
        emit(api.app_logs(client, app.get("id")), args)
    elif sub == "deploys":
        app = api.resolve_app(client, args.app)
        if not app:
            raise SystemExit(f"Приложение не найдено: {args.app}")
        emit(api.app_deploys(client, app.get("id")), args)
    elif sub == "bind-domain":
        app = api.resolve_app(client, args.app)
        if not app:
            raise SystemExit(f"Приложение не найдено: {args.app}")
        emit(api.bind_app_domain(client, app.get("id"), args.fqdn), args)
    elif sub == "delete":
        app = api.resolve_app(client, args.app)
        if not app:
            raise SystemExit(f"Приложение не найдено: {args.app}")
        if confirm(args, f"удалить приложение {app.get('name')} (id={app.get('id')})"):
            emit(api.delete_app(client, app["id"]), args)


def cmd_vcs(args: argparse.Namespace) -> None:
    client = make_client(args)
    if args.sub == "list":
        emit(api.list_vcs_providers(client), args)
    elif args.sub == "connect":
        if confirm(args, "подключить VCS-провайдера (токен сохранится в панели Timeweb)"):
            emit(api.connect_vcs(client, args.provider, args.token), args)
    elif args.sub == "delete":
        if confirm(args, f"отключить VCS-провайдера {args.provider_id}"):
            emit(api.delete_vcs(client, args.provider_id), args)
    elif args.sub == "repos":
        emit(api.list_repos(client, args.provider_id), args)
    elif args.sub == "branches":
        emit(api.list_branches(client, args.provider_id, args.repository_id), args)


def cmd_deploy(args: argparse.Namespace) -> None:
    ssh = get_ssh(args)
    sub = args.sub
    with ssh:
        if sub == "provision":
            deploy.provision(ssh, with_docker=not args.no_docker)
        elif sub == "website":
            deploy.deploy_static_site(ssh, args.path, args.domain, ssl=not args.no_ssl, ssl_email=args.ssl_email)
        elif sub == "docker":
            deploy.deploy_docker_app(
                ssh, args.path, args.domain, port=args.port, app_name=args.app_name,
                ssl=not args.no_ssl, ssl_email=args.ssl_email, compose_file=args.compose_file,
            )
        elif sub == "git":
            deploy.deploy_from_git(
                ssh, args.repo, branch=args.branch, domain=args.domain, port=args.port,
                app_name=args.app_name, ssl=not args.no_ssl, ssl_email=args.ssl_email,
                compose_file=args.compose_file,
            )
        elif sub == "mysql":
            info = deploy.deploy_mysql(
                ssh, db_name=args.name, db_user=args.user, db_password=args.password,
                port=args.port, volume_name=args.volume,
            )
            emit(info, args)
        elif sub == "exec":
            code, out, err = ssh.exec(args.command, check=not args.ignore_errors)
            emit({"exit_code": code, "stdout": out, "stderr": err}, args)
        elif sub == "upload":
            ssh.upload(args.path, args.remote)


def cmd_run(args: argparse.Namespace) -> None:
    data = runbook.load_runbook(args.runbook)
    print(f"[plan] {data.get('name') or args.runbook} ({len(data['steps'])} шагов)", flush=True)
    if args.dry_run:
        for i, step in enumerate(data["steps"], 1):
            print(f"  {i}. {step.get('name') or step.get('action')} — {step.get('action')}", flush=True)
        return
    client = make_client(args)
    if not args.yes and sys.stdin.isatty():
        answer = input("Выполнить план? [y/N]: ").strip().lower()
        if answer not in {"y", "yes", "д", "да"}:
            print("Отменено.", file=sys.stderr)
            return
    if not args.yes and not config.AUTO_YES and not sys.stdin.isatty():
        print(
            "[отмена] Выполнение плана требует подтверждения. "
            "Запустите с флагом --yes или установите TW_YES=1.",
            file=sys.stderr,
        )
        return
    saved = runbook.execute(client, data["steps"], vars_=data.get("vars"), verbose=args.verbose)
    print("[plan] Готово", flush=True)
    emit(saved, args)


# ---------------------------------------------------------------------- #
#  Парсер
# ---------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twagent",
        description="Агент управления Timeweb Cloud: серверы, БД, домены, приложения, деплой.",
    )
    parser.add_argument("--json", action="store_true", help="выводить результат в JSON")
    parser.add_argument("--show-secrets", action="store_true", help="не скрывать пароли/токены в выводе")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    parser.add_argument("--yes", action="store_true", help="подтверждать все действия автоматически")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        # default=SUPPRESS, чтобы флаг сработал и до, и после подкоманды
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--show-secrets", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--yes", action="store_true", default=argparse.SUPPRESS)

    # doctor
    p = sub.add_parser("doctor", help="проверка токена и сводка по аккаунту")
    add_common(p)
    p.set_defaults(func=cmd_doctor)

    # projects
    p = sub.add_parser("projects", help="проекты")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list", help="список проектов"); add_common(p1); p1.set_defaults(func=cmd_projects)
    p2 = ps.add_parser("create", help="создать проект"); add_common(p2)
    p2.add_argument("name"); p2.add_argument("--description")
    p2.set_defaults(func=cmd_projects)

    # os
    p = sub.add_parser("os", help="доступные ОС для серверов")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.set_defaults(func=cmd_os)

    # presets
    p = sub.add_parser("presets", help="тарифы: servers, dbs, apps, balancers, k8s...")
    p.add_argument("kind", choices=["servers", "dbs", "apps", "balancers", "k8s", "storages", "network-drives", "routers", "dedicated-servers"])
    add_common(p)
    p.set_defaults(func=cmd_presets)

    # ssh-keys
    p = sub.add_parser("ssh-keys", help="SSH-ключи панели")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.set_defaults(func=cmd_ssh_keys)
    p2 = ps.add_parser("add", help="добавить ключ"); add_common(p2)
    p2.add_argument("name"); p2.add_argument("--public-key"); p2.add_argument("--pubkey-file")
    p2.set_defaults(func=cmd_ssh_keys)
    p3 = ps.add_parser("ensure", help="найти или сгенерировать ключ «timeweb-agent»"); add_common(p3)
    p3.add_argument("--name", default="timeweb-agent")
    p3.set_defaults(func=cmd_ssh_keys)
    p4 = ps.add_parser("delete"); add_common(p4); p4.add_argument("key"); p4.set_defaults(func=cmd_ssh_keys)

    # servers
    p = sub.add_parser("servers", help="облачные серверы")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.add_argument("--search"); p1.set_defaults(func=cmd_servers)
    p2 = ps.add_parser("create", help="создать сервер"); add_common(p2)
    p2.add_argument("name")
    p2.add_argument("--os", default="auto", help="ID ОС или auto (Ubuntu 24.04)")
    p2.add_argument("--preset", default="auto", help="ID тарифа или auto (самый дешёвый)")
    p2.add_argument("--ssh-key", help="имя/ID SSH-ключа или auto (сгенерировать)")
    p2.add_argument("--project-id")
    p2.add_argument("--ddos", action="store_true", help="включить защиту от DDoS")
    p2.add_argument("--comment")
    p2.add_argument("--no-wait", action="store_true")
    p2.add_argument("--wait-timeout", type=int, default=900)
    p2.set_defaults(func=cmd_servers)
    for subname, hlp in [
        ("get", "информация о сервере"), ("delete", "удалить сервер"),
        ("wait", "дождаться статуса on"), ("reboot", "перезагрузить"),
        ("start", "запустить"), ("stop", "выключить"), ("reset-password", "сбросить root-пароль"),
        ("logs", "логи сервера"), ("ip", "IP-адреса сервера"),
    ]:
        p3 = ps.add_parser(subname, help=hlp); add_common(p3)
        p3.add_argument("server", help="имя или ID сервера")
        if subname in {"wait", "reset-password"}:
            p3.add_argument("--timeout", type=int, default=900)
        p3.set_defaults(func=cmd_servers)

    # db
    p = sub.add_parser("db", help="базы данных (DBaaS)")
    ps = p.add_subparsers(dest="sub", required=True)
    for subname, hlp in [("types", "типы СУБД"), ("presets", "тарифы БД"), ("list", "список кластеров")]:
        p1 = ps.add_parser(subname, help=hlp); add_common(p1); p1.set_defaults(func=cmd_db)
    p2 = ps.add_parser("create", help="создать кластер БД"); add_common(p2)
    p2.add_argument("name")
    p2.add_argument("--type", default="mysql", help="тип СУБД (см. db types)")
    p2.add_argument("--admin-login", default="admin")
    p2.add_argument("--admin-password", help="пусто — сгенерировать")
    p2.add_argument("--preset", default="auto")
    p2.add_argument("--instance-name")
    p2.add_argument("--project-id")
    p2.add_argument("--no-wait", action="store_true")
    p2.add_argument("--wait-timeout", type=int, default=900)
    p2.set_defaults(func=cmd_db)
    p3 = ps.add_parser("get"); add_common(p3); p3.add_argument("db"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("delete"); add_common(p3); p3.add_argument("db"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("admins", help="пользователи БД"); add_common(p3); p3.add_argument("db"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("add-admin"); add_common(p3); p3.add_argument("db"); p3.add_argument("login")
    p3.add_argument("--password"); p3.add_argument("--host"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("instances", help="инстансы (базы) кластера"); add_common(p3); p3.add_argument("db"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("add-instance"); add_common(p3); p3.add_argument("db"); p3.add_argument("name"); p3.set_defaults(func=cmd_db)
    p3 = ps.add_parser("wait"); add_common(p3); p3.add_argument("db"); p3.add_argument("--timeout", type=int, default=900); p3.set_defaults(func=cmd_db)

    # domains
    p = sub.add_parser("domains", help="домены")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.set_defaults(func=cmd_domains)
    p2 = ps.add_parser("check", help="проверить доступность домена"); add_common(p2); p2.add_argument("fqdn"); p2.set_defaults(func=cmd_domains)
    p3 = ps.add_parser("add", help="добавить/зарегистрировать домен"); add_common(p3); p3.add_argument("fqdn"); p3.set_defaults(func=cmd_domains)
    p4 = ps.add_parser("delete"); add_common(p4); p4.add_argument("fqdn"); p4.set_defaults(func=cmd_domains)

    # dns
    p = sub.add_parser("dns", help="DNS-записи")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.add_argument("fqdn"); p1.set_defaults(func=cmd_dns)
    p2 = ps.add_parser("add"); add_common(p2)
    p2.add_argument("fqdn", help="домен или поддомен, напр. www.example.ru")
    p2.add_argument("type", choices=["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"])
    p2.add_argument("value"); p2.add_argument("--ttl", type=int); p2.add_argument("--app-id")
    p2.set_defaults(func=cmd_dns)
    p3 = ps.add_parser("update"); add_common(p3); p3.add_argument("fqdn"); p3.add_argument("record_id")
    p3.add_argument("--value"); p3.add_argument("--ttl", type=int); p3.set_defaults(func=cmd_dns)
    p4 = ps.add_parser("delete"); add_common(p4); p4.add_argument("fqdn"); p4.add_argument("record_id"); p4.set_defaults(func=cmd_dns)

    # apps
    p = sub.add_parser("apps", help="PaaS-приложения (Apps)")
    ps = p.add_subparsers(dest="sub", required=True)
    for subname, hlp in [
        ("list", "список приложений"), ("frameworks", "доступные фреймворки"),
        ("presets", "тарифы приложений"), ("get", "информация о приложении"),
        ("deploy", "запустить деплой"), ("logs", "логи приложения"), ("deploys", "история деплоев"),
        ("delete", "удалить приложение"),
    ]:
        p1 = ps.add_parser(subname, help=hlp); add_common(p1)
        if subname in {"get", "deploy", "logs", "deploys", "delete"}:
            p1.add_argument("app", help="имя или ID приложения")
        if subname == "deploy":
            p1.add_argument("--commit-sha")
        p1.set_defaults(func=cmd_apps)
    p2 = ps.add_parser("create", help="создать приложение из git-репозитория"); add_common(p2)
    p2.add_argument("name")
    p2.add_argument("--type", choices=["frontend", "backend"], required=True)
    p2.add_argument("--provider-id", required=True, help="ID VCS-провайдера (см. vcs list)")
    p2.add_argument("--repository-id", required=True, help="ID репозитория (см. vcs repos)")
    p2.add_argument("--branch", default="main")
    p2.add_argument("--framework-id", type=int)
    p2.add_argument("--build-cmd"); p2.add_argument("--run-cmd"); p2.add_argument("--index-dir")
    p2.add_argument("--envs", help="JSON-объект переменных окружения")
    p2.add_argument("--preset-id", type=int)
    p2.add_argument("--auto-deploy", action="store_true")
    p2.add_argument("--project-id"); p2.add_argument("--comment")
    p2.set_defaults(func=cmd_apps)
    p3 = ps.add_parser("bind-domain", help="привязать домен к приложению"); add_common(p3)
    p3.add_argument("app"); p3.add_argument("fqdn"); p3.set_defaults(func=cmd_apps)

    # vcs
    p = sub.add_parser("vcs", help="VCS-провайдеры (GitHub и др.) для Apps")
    ps = p.add_subparsers(dest="sub", required=True)
    p1 = ps.add_parser("list"); add_common(p1); p1.set_defaults(func=cmd_vcs)
    p2 = ps.add_parser("connect"); add_common(p2)
    p2.add_argument("--provider", choices=["github", "gitlab", "bitbucket"], required=True)
    p2.add_argument("--token", required=True, help="fine-grained PAT")
    p2.set_defaults(func=cmd_vcs)
    p3 = ps.add_parser("delete"); add_common(p3); p3.add_argument("provider_id"); p3.set_defaults(func=cmd_vcs)
    p4 = ps.add_parser("repos", help="репозитории провайдера"); add_common(p4); p4.add_argument("provider_id"); p4.set_defaults(func=cmd_vcs)
    p5 = ps.add_parser("branches", help="ветки репозитория"); add_common(p5); p5.add_argument("provider_id"); p5.add_argument("repository_id"); p5.set_defaults(func=cmd_vcs)

    # deploy (SSH)
    p = sub.add_parser("deploy", help="развёртывание на VPS по SSH")
    ps = p.add_subparsers(dest="sub", required=True)
    def add_ssh_args(pp, with_server=True):
        if with_server:
            pp.add_argument("--server", help="имя/ID сервера Timeweb (взять его IP) — вместо --host")
        pp.add_argument("--host", help="IP/host сервера (или TW_SSH_HOST)")
        pp.add_argument("--ssh-user", default=config.SSH_USER)
        pp.add_argument("--ssh-port", type=int, default=config.SSH_PORT)
        pp.add_argument("--ssh-password")
        pp.add_argument("--ssh-key-path")
        add_common(pp)

    p1 = ps.add_parser("provision", help="подготовить сервер (пакеты, docker, nginx)"); add_ssh_args(p1)
    p1.add_argument("--no-docker", action="store_true"); p1.set_defaults(func=cmd_deploy)

    p2 = ps.add_parser("website", help="развернуть статический сайт"); add_ssh_args(p2)
    p2.add_argument("path", help="папка с сайтом"); p2.add_argument("--domain", required=True)
    p2.add_argument("--ssl", action="store_true", default=True); p2.add_argument("--no-ssl", action="store_true", dest="no_ssl")
    p2.add_argument("--ssl-email"); p2.set_defaults(func=cmd_deploy)

    p3 = ps.add_parser("docker", help="развернуть приложение через docker compose"); add_ssh_args(p3)
    p3.add_argument("path"); p3.add_argument("--domain", required=True); p3.add_argument("--port", type=int, default=8000)
    p3.add_argument("--app-name"); p3.add_argument("--compose-file", default="docker-compose.yml")
    p3.add_argument("--no-ssl", action="store_true"); p3.add_argument("--ssl-email"); p3.set_defaults(func=cmd_deploy)

    p4 = ps.add_parser("git", help="развернуть приложение из git-репозитория"); add_ssh_args(p4)
    p4.add_argument("repo"); p4.add_argument("--branch", default="main"); p4.add_argument("--domain")
    p4.add_argument("--port", type=int, default=8000); p4.add_argument("--app-name"); p4.add_argument("--compose-file", default="docker-compose.yml")
    p4.add_argument("--no-ssl", action="store_true"); p4.add_argument("--ssl-email"); p4.set_defaults(func=cmd_deploy)

    p5 = ps.add_parser("mysql", help="поднять MySQL в docker на сервере"); add_ssh_args(p5)
    p5.add_argument("--name", required=True, help="имя базы"); p5.add_argument("--user", default="app")
    p5.add_argument("--password"); p5.add_argument("--port", type=int, default=3306); p5.add_argument("--volume")
    p5.set_defaults(func=cmd_deploy)

    p6 = ps.add_parser("exec", help="выполнить команду по SSH"); add_ssh_args(p6)
    p6.add_argument("command"); p6.add_argument("--ignore-errors", action="store_true"); p6.set_defaults(func=cmd_deploy)

    p7 = ps.add_parser("upload", help="загрузить файл/папку по SFTP"); add_ssh_args(p7)
    p7.add_argument("path"); p7.add_argument("remote"); p7.set_defaults(func=cmd_deploy)

    # run
    p = sub.add_parser("run", help="выполнить план (runbook) из YAML-файла")
    add_common(p)
    p.add_argument("runbook", help="путь к YAML-плану")
    p.add_argument("--dry-run", action="store_true", help="только показать шаги")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[list] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except TimewebError as e:
        print(f"[api] {e}", file=sys.stderr)
        if e.response_id:
            print(f"[api] response_id: {e.response_id}", file=sys.stderr)
        raise SystemExit(2)
    except (runbook.RunbookError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        raise SystemExit(3)
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
