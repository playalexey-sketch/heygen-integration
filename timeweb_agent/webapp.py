"""Веб-панель агента Timeweb Cloud (Flask).

Запуск:
    python -m timeweb_agent web            — откроется http://127.0.0.1:8050
    run_twagent_web.bat / run_twagent_web.sh  — двойной клик (Windows / Linux)

Интерфейс лежит в timeweb_agent/webui/ (index.html, style.css, app.js).
Все API-вызовы идут через этот бэкенд — токен и пароли не покидают
ваш компьютер.
"""
from __future__ import annotations

import os
import traceback
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from . import __version__, api, brain, config, deploy
from .client import TimewebClient
from .ssh import SSHClient

WEBUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
DEMO = config.get_bool("TW_DEMO")

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------------- #
#  Вспомогательное
# ---------------------------------------------------------------------- #
def ok(data: Any):
    return jsonify({"ok": True, "data": data})


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": str(message)}), status


def wrap(fn):
    try:
        return ok(fn())
    except Exception as e:  # noqa: BLE001 — любую ошибку показываем в UI
        traceback.print_exc()
        return fail(str(e))


def make_client() -> TimewebClient:
    if not config.API_TOKEN:
        raise RuntimeError(
            "Токен не задан. Заполните TIMEWEB_CLOUD_TOKEN в файле .env "
            "(вкладка «Настройки» подскажет путь и что заполнить)."
        )
    return TimewebClient(
        token=config.API_TOKEN,
        base_url=config.API_BASE_URL,
        timeout=config.API_TIMEOUT,
        retries=config.API_RETRIES,
    )


def _ssh_from(payload: dict) -> SSHClient:
    host = str(payload.get("host") or config.SSH_HOST or "").strip()
    if not host and payload.get("server"):
        server = api.resolve_server(make_client(), str(payload["server"]))
        if not server:
            raise RuntimeError(f"Сервер не найден в панели: {payload['server']}")
        host = api.server_ip(server)
    if not host:
        raise RuntimeError(
            "Не задан SSH-хост: укажите IP вручную, выберите сервер из панели "
            "или заполните TW_SSH_HOST в .env"
        )
    return SSHClient(
        host=host,
        user=payload.get("ssh_user") or config.SSH_USER,
        port=int(payload.get("ssh_port") or config.SSH_PORT),
        password=payload.get("ssh_password") or config.SSH_PASSWORD,
        key_path=payload.get("ssh_key_path") or config.SSH_KEY_PATH,
        key_passphrase=payload.get("ssh_key_passphrase") or config.SSH_KEY_PASSPHRASE,
    )


def _server_out(s: dict) -> dict:
    s = dict(s)
    s["ip"] = api.server_ip(s)
    return s


def _db_out(d: dict) -> dict:
    d = dict(d)
    d["connection"] = api.db_connection_info(d)
    return d


# ---------------------------------------------------------------------- #
#  Демо-данные диагностики (TW_DEMO=1 — только для предпросмотра UI)
# ---------------------------------------------------------------------- #
DEMO_DIAG = [
    {
        "command": "nproc",
        "description": "Количество ядер процессора",
        "exit_code": 0,
        "output": "4",
        "error": "",
        "demo": True,
    },
    {
        "command": "free -h",
        "description": "Оперативная память (смотрите строку Mem:)",
        "exit_code": 0,
        "output": (
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:           7.7Gi       1.2Gi       4.1Gi        89Mi       2.4Gi       6.1Gi\n"
            "Swap:          2.0Gi          0B       2.0Gi"
        ),
        "error": "",
        "demo": True,
    },
    {
        "command": "df -h",
        "description": "Смонтированные разделы и свободное место",
        "exit_code": 0,
        "output": (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "udev            3.8G     0  3.8G   0% /dev\n"
            "/dev/vda1        20G  6.4G   13G  34% /\n"
            "tmpfs           782M  1.1M  781M   1% /run"
        ),
        "error": "",
        "demo": True,
    },
    {
        "command": "fdisk -l",
        "description": "Физический диск и разделы (нужны права root)",
        "exit_code": 0,
        "output": (
            "Disk /dev/vda: 30 GiB, 32212254720 bytes, 62914560 sectors\n"
            "Device     Boot Start      End  Sectors Size Id Type\n"
            "/dev/vda1  *     2048 62914526 62912479  30G 83 Linux"
        ),
        "error": "",
        "demo": True,
    },
    {
        "command": "lsblk",
        "description": "Дополнительно: дерево дисков и разделов",
        "exit_code": 0,
        "output": (
            "NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT\n"
            "vda    254:0    0   30G  0 disk\n"
            "└─vda1 254:1    0   30G  0 part /"
        ),
        "error": "",
        "demo": True,
    },
]


# ---------------------------------------------------------------------- #
#  Статика и служебные эндпоинты
# ---------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(WEBUI_DIR, "index.html")


@app.get("/style.css")
def style():
    return send_from_directory(WEBUI_DIR, "style.css")


@app.get("/app.js")
def app_js():
    return send_from_directory(WEBUI_DIR, "app.js")


@app.get("/api/health")
def health():
    return ok(
        {
            "token_set": bool(config.API_TOKEN),
            "token_masked": config.mask(config.API_TOKEN) if config.API_TOKEN else None,
            "api_url": config.API_BASE_URL,
            "demo": DEMO,
            "version": __version__,
            "ssh": {
                "host": config.SSH_HOST or None,
                "user": config.SSH_USER,
                "port": config.SSH_PORT,
                "auth": (
                    "password"
                    if config.SSH_PASSWORD
                    else ("key" if config.SSH_KEY_PATH else None)
                ),
            },
        }
    )


@app.get("/api/env")
def env_info():
    return ok(
        {
            "files": [{"path": str(p), "exists": p.is_file()} for p in config._ENV_FILES],
            "values": {
                "TIMEWEB_CLOUD_TOKEN": {
                    "set": bool(config.API_TOKEN),
                    "value": config.mask(config.API_TOKEN) if config.API_TOKEN else None,
                    "hint": "токен панели: timeweb.cloud/my/api-keys",
                },
                "TIMEWEB_API_URL": {"set": True, "value": config.API_BASE_URL, "hint": None},
                "TW_SSH_HOST": {
                    "set": bool(config.SSH_HOST),
                    "value": config.SSH_HOST or None,
                    "hint": "IP вашего VPS",
                },
                "TW_SSH_USER": {"set": True, "value": config.SSH_USER, "hint": "обычно root"},
                "TW_SSH_PORT": {"set": True, "value": config.SSH_PORT, "hint": "обычно 22"},
                "TW_SSH_PASSWORD": {
                    "set": bool(config.SSH_PASSWORD),
                    "value": config.mask(config.SSH_PASSWORD) if config.SSH_PASSWORD else None,
                    "hint": "или TW_SSH_KEY_PATH",
                },
                "TW_SSH_KEY_PATH": {
                    "set": bool(config.SSH_KEY_PATH),
                    "value": config.SSH_KEY_PATH or None,
                    "hint": "путь к приватному ключу",
                },
                "TW_YES": {"set": True, "value": config.AUTO_YES, "hint": "автоподтверждение действий"},
            },
        }
    )


@app.get("/api/doctor")
def doctor():
    def run():
        client = make_client()
        status = api.account_status(client)
        return {
            "account": status,
            "servers": len(api.list_servers(client)),
            "databases": len(api.list_databases(client)),
            "apps": len(api.list_apps(client)),
            "domains": len(api.list_domains(client)),
            "ssh_keys": len(api.list_ssh_keys(client)),
            "projects": len(api.list_projects(client)),
        }

    return wrap(run)


# ---------------------------------------------------------------------- #
#  Серверы
# ---------------------------------------------------------------------- #
@app.get("/api/servers")
def servers_list():
    def run():
        return [_server_out(s) for s in api.list_servers(make_client())]

    return wrap(run)


@app.post("/api/servers/create")
def servers_create():
    payload = request.get_json(silent=True) or {}

    def run():
        client = make_client()
        ssh_key_ids = None
        ssh_key = str(payload.get("ssh_key") or "").strip()
        if ssh_key == "auto":
            key = api.ensure_ssh_key(client)
            ssh_key_ids = [key.get("id")]
        elif ssh_key:
            key = api.find_ssh_key(client, ssh_key)
            if not key:
                raise RuntimeError(f"SSH-ключ не найден: {ssh_key}")
            ssh_key_ids = [key.get("id")]
        server = api.create_server(
            client,
            name=str(payload["name"]),
            os_id=str(payload.get("os") or "auto"),
            preset_id=str(payload.get("preset") or "auto"),
            ssh_key_ids=ssh_key_ids,
            is_ddos_guard=payload.get("ddos"),
            comment=payload.get("comment"),
            wait=bool(payload.get("wait", True)),
            wait_timeout=int(payload.get("wait_timeout", 900)),
        )
        if payload.get("wait", True):
            server = _server_out(server)
        return server

    return wrap(run)


@app.post("/api/servers/<int:sid>/action")
def servers_action(sid: int):
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")

    def run():
        client = make_client()
        if action == "reset-password":
            return api.reset_server_password(client, sid)
        if action not in {"reboot", "start", "shutdown", "hard-reboot", "hard-shutdown"}:
            raise RuntimeError(f"Неизвестное действие: {action}")
        return api.server_action(client, sid, action)

    return wrap(run)


@app.delete("/api/servers/<int:sid>")
def servers_delete(sid: int):
    return wrap(lambda: api.delete_server(make_client(), sid))


# ---------------------------------------------------------------------- #
#  Базы данных
# ---------------------------------------------------------------------- #
@app.get("/api/dbs")
def dbs_list():
    def run():
        return [_db_out(d) for d in api.list_databases(make_client())]

    return wrap(run)


@app.post("/api/dbs/create")
def dbs_create():
    payload = request.get_json(silent=True) or {}

    def run():
        db = api.create_database(
            make_client(),
            name=str(payload["name"]),
            db_type=str(payload.get("type") or "mysql"),
            admin_login=str(payload.get("admin_login") or "admin"),
            admin_password=payload.get("admin_password"),
            preset_id=str(payload.get("preset") or "auto"),
            instance_name=payload.get("instance_name"),
            wait=bool(payload.get("wait", True)),
            wait_timeout=int(payload.get("wait_timeout", 900)),
        )
        result = _db_out(db)
        result["admin_password"] = db.get("_admin_password")
        return result

    return wrap(run)


@app.delete("/api/dbs/<int:dbid>")
def dbs_delete(dbid: int):
    return wrap(lambda: api.delete_database(make_client(), dbid))


# ---------------------------------------------------------------------- #
#  Домены и DNS
# ---------------------------------------------------------------------- #
@app.get("/api/domains")
def domains_list():
    def run():
        return api.list_domains(make_client())

    return wrap(run)


@app.get("/api/dns/<path:fqdn>")
def dns_list(fqdn: str):
    return wrap(lambda: api.list_dns_records(make_client(), fqdn))


@app.post("/api/dns/<path:fqdn>")
def dns_add(fqdn: str):
    payload = request.get_json(silent=True) or {}

    def run():
        return api.add_dns_record(
            make_client(),
            fqdn,
            rtype=str(payload["type"]),
            value=str(payload["value"]),
            ttl=payload.get("ttl"),
            app_id=payload.get("app_id"),
        )

    return wrap(run)


@app.delete("/api/dns/<path:fqdn>/<int:rid>")
def dns_delete(fqdn: str, rid: int):
    return wrap(lambda: api.delete_dns_record(make_client(), fqdn, rid))


# ---------------------------------------------------------------------- #
#  Приложения (PaaS)
# ---------------------------------------------------------------------- #
@app.get("/api/apps")
def apps_list():
    def run():
        return api.list_apps(make_client())

    return wrap(run)


# ---------------------------------------------------------------------- #
#  SSH: произвольная команда и диагностика поддержки
# ---------------------------------------------------------------------- #
@app.post("/api/ssh/exec")
def ssh_exec():
    payload = request.get_json(silent=True) or {}

    def run():
        ssh = _ssh_from(payload)
        with ssh:
            code, out, err = ssh.exec(
                str(payload["command"]),
                check=False,
                timeout=int(payload.get("timeout", 600)),
                print_output=False,
            )
        return {"exit_code": code, "stdout": out, "stderr": err}

    return wrap(run)


@app.post("/api/diag")
def diag():
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host") or config.SSH_HOST or "").strip()
    if DEMO and not host and not payload.get("server"):
        return ok({"demo": True, "target": "демо-сервер", "results": DEMO_DIAG})

    def run():
        target = payload.get("server") or payload.get("host") or host
        ssh = _ssh_from(payload)
        with ssh:
            results = deploy.run_support_diagnostics(ssh)
        return {"demo": False, "target": target, "results": results}

    return wrap(run)


# ---------------------------------------------------------------------- #
#  Интеллектуальный помощник (естественный язык → план → проверка → отчёт)
# ---------------------------------------------------------------------- #
@app.get("/api/ask/info")
def ask_info():
    llm = brain.get_llm()
    return ok(
        {
            "llm": (
                {
                    "available": True,
                    "provider": llm.provider,
                    "model": llm.model,
                }
                if llm
                else {"available": False}
            ),
            "actions": list(brain.ACTIONS_SPEC.keys()),
            "examples": [
                "Создай на сервере новый сайт для клиента Maria, PostgreSQL, Redis, Nginx и HTTPS на домене maria.ru",
                "Создай управляемую базу данных PostgreSQL для проекта shop",
                "Разверни приложение из https://github.com/me/app.git на app.example.ru с HTTPS",
                "Добавь A-запись example.ru на IP 185.105.1.42",
                "Покажи список серверов",
                "Проверь конфигурацию сервера: nproc, free, df, fdisk",
            ],
        }
    )


@app.post("/api/ask/plan")
def ask_plan():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return fail("Введите запрос")

    def run():
        return brain.plan(text, make_client(), force_llm=payload.get("llm"))

    return wrap(run)


@app.post("/api/ask/execute")
def ask_execute():
    payload = request.get_json(silent=True) or {}
    steps = payload.get("steps")
    text = str(payload.get("text") or "").strip()
    if not isinstance(steps, list) or not steps:
        return fail("План пуст")

    def run():
        result = brain.run_request(
            text or "запрос из веб-панели",
            make_client(),
            confirm=False,
            preapproved_plan={"summary": payload.get("summary") or "", "steps": steps},
        )
        # в веб-панели показываем доступы открыто (это личная панель пользователя)
        return result

    return wrap(run)


# ---------------------------------------------------------------------- #
#  Деплой по SSH
# ---------------------------------------------------------------------- #
@app.post("/api/deploy/<kind>")
def deploy_route(kind: str):
    payload = request.get_json(silent=True) or {}

    def run():
        ssh = _ssh_from(payload)
        with ssh:
            if kind == "provision":
                deploy.provision(
                    ssh,
                    with_docker=bool(payload.get("docker", True)),
                    with_fail2ban=bool(payload.get("fail2ban", True)),
                )
                return {"status": "ok", "message": "Сервер подготовлен (пакеты, docker, nginx)"}
            if kind == "website":
                deploy.deploy_static_site(
                    ssh,
                    local_dir=payload["path"],
                    domain=str(payload["domain"]),
                    ssl=bool(payload.get("ssl", True)),
                    ssl_email=payload.get("ssl_email"),
                )
                return {"status": "ok", "message": f"Сайт развёрнут: {payload['domain']}"}
            if kind == "docker":
                deploy.deploy_docker_app(
                    ssh,
                    local_dir=payload["path"],
                    domain=str(payload["domain"]),
                    port=int(payload.get("port", 8000)),
                    app_name=payload.get("app_name"),
                    ssl=bool(payload.get("ssl", True)),
                    ssl_email=payload.get("ssl_email"),
                    compose_file=payload.get("compose_file", "docker-compose.yml"),
                )
                return {"status": "ok", "message": f"Приложение развёрнуто: {payload['domain']}"}
            if kind == "git":
                deploy.deploy_from_git(
                    ssh,
                    repo=str(payload["repo"]),
                    branch=str(payload.get("branch", "main")),
                    domain=payload.get("domain"),
                    port=int(payload.get("port", 8000)),
                    app_name=payload.get("app_name"),
                    ssl=bool(payload.get("ssl", True)),
                    ssl_email=payload.get("ssl_email"),
                    compose_file=payload.get("compose_file", "docker-compose.yml"),
                )
                return {"status": "ok", "message": "Приложение из git развёрнуто"}
            if kind == "mysql":
                info = deploy.deploy_mysql(
                    ssh,
                    db_name=str(payload["name"]),
                    db_user=str(payload.get("user", "app")),
                    db_password=payload.get("password"),
                    port=int(payload.get("port", 3306)),
                    volume_name=payload.get("volume"),
                )
                return {"status": "ok", "message": "MySQL запущен", "connection": info}
        raise RuntimeError(f"Неизвестный тип деплоя: {kind}")

    return wrap(run)
