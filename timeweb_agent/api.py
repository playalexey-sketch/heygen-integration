"""Высокоуровневые операции Timeweb Cloud.

Обёртки над REST API с «умным» автоподбором (ОС, тарифы, SSH-ключи),
ожиданием статусов и удобным разрешением ресурсов по имени или ID.
"""
from __future__ import annotations

import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from .client import TimewebClient, TimewebError

# Статусы сервера
SERVER_READY = {"on"}
SERVER_BUSY = {"installing", "starting", "stopping", "rebooting", "configuring", "booting", "cloning", "restoring"}
SERVER_ERROR = {"error", "failed", "blocked", "locked"}

# Статусы кластера БД
DB_READY = {"started", "active", "on", "running"}
DB_BUSY = {"starting", "creating", "installing", "configuring", "restarting", "replication"}
DB_ERROR = {"error", "failed", "blocked"}


def _pick(data: Any, *keys: str, default=None) -> Any:
    """Достаёт значение по одному из ключей; при отсутствии — первый осмысленный."""
    if isinstance(data, dict):
        for k in keys:
            if k in data:
                return data[k]
        for k, v in data.items():
            if k in {"meta", "response_id"}:
                continue
            return v
    return default


def _wait_status(
    client: TimewebClient,
    get_path: str,
    item_key: str,
    ready: set,
    busy: set,
    error_states: set,
    timeout: int,
    verbose: bool,
) -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = client.get(get_path)
        item = _pick(data, item_key) or {}
        last = item
        status = str(item.get("status", "")).lower()
        if verbose:
            print(f"[wait] {get_path}: status={status or '?'}", flush=True)
        if status in error_states:
            raise TimewebError(0, "resource_error", f"Ресурс перешёл в ошибочный статус: {status}", payload=item)
        if status in ready:
            return item
        if status not in busy and status:
            # неизвестный статус — не считаем ошибкой, но и не ждём зря:
            # продолжаем ждать только известные переходные
            if verbose:
                print(f"[wait] неизвестный статус «{status}», ждём дальше", flush=True)
        time.sleep(10)
    raise TimeError(f"Таймаут ожидания ({timeout} с). Последний статус: {last.get('status') if last else '?'}")


class TimeError(RuntimeError):
    pass


# ====================================================================== #
#  Аккаунт и проекты
# ====================================================================== #
def account_status(client: TimewebClient) -> dict:
    return client.get("/account/status")


def list_projects(client: TimewebClient) -> list:
    return client.get_all("/projects", key="projects")


def create_project(client: TimewebClient, name: str, description: str | None = None) -> dict:
    payload: dict = {"name": name}
    if description:
        payload["description"] = description
    return _pick(client.post("/projects", json=payload), "project") or {}


def resolve_project(client: TimewebClient, name_or_id: str) -> Optional[dict]:
    for p in list_projects(client):
        if str(p.get("id")) == str(name_or_id) or str(p.get("name")) == str(name_or_id):
            return p
    return None


# ====================================================================== #
#  Справочники: ОС, тарифы, локации
# ====================================================================== #
def list_os(client: TimewebClient) -> list:
    return _pick(client.get("/os/servers"), "servers_os", default=[]) or []


def pick_os(client: TimewebClient, prefer: str = "ubuntu 24.04") -> dict:
    oss = list_os(client)
    if not oss:
        raise TimeError("Не удалось получить список ОС (/os/servers).")
    pref = prefer.lower()
    for name_key in ("name", "version"):
        for os_ in oss:
            if pref in str(os_.get(name_key, "")).lower():
                return os_
        # менее строгое совпадение: ubuntu любой версии
        for os_ in oss:
            if "ubuntu" in str(os_.get(name_key, "")).lower():
                return os_
    return oss[0]


def list_server_presets(client: TimewebClient) -> list:
    return _pick(client.get("/presets/servers"), "server_presets", default=[]) or []


def pick_server_preset(client: TimewebClient, prefer_location: str = "ru") -> dict:
    presets = list_server_presets(client)
    if not presets:
        raise TimeError("Не удалось получить тарифы серверов (/presets/servers).")
    pool = [p for p in presets if prefer_location in str(p.get("location", "")).lower()] or presets

    def price(p: dict) -> float:
        try:
            return float(p.get("price", float("inf")))
        except (TypeError, ValueError):
            return float("inf")

    return min(pool, key=price)


def list_db_types(client: TimewebClient) -> list:
    return _pick(client.get("/database-types"), "types", default=[]) or []


def list_db_presets(client: TimewebClient) -> list:
    return _pick(client.get("/api/v2/presets/dbs"), "databases_presets", default=[]) or []


def pick_db_preset(client: TimewebClient, family: str = "") -> dict:
    presets = list_db_presets(client)
    if not presets:
        raise TimeError("Не удалось получить тарифы БД (/v2/presets/dbs).")
    fam = family.lower()
    pool = [p for p in presets if fam and fam in str(p.get("type", "")).lower()] or presets

    def price(p: dict) -> float:
        try:
            return float(p.get("price", float("inf")))
        except (TypeError, ValueError):
            return float("inf")

    return min(pool, key=price)


def list_locations(client: TimewebClient) -> list:
    return _pick(client.get("/locations"), "locations", default=[]) or []


# ====================================================================== #
#  SSH-ключи
# ====================================================================== #
def list_ssh_keys(client: TimewebClient) -> list:
    return client.get_all("/ssh-keys", key="ssh_keys")


def find_ssh_key(client: TimewebClient, name_or_id: str) -> Optional[dict]:
    for k in list_ssh_keys(client):
        if str(k.get("id")) == str(name_or_id) or str(k.get("name")) == str(name_or_id):
            return k
    return None


def add_ssh_key(client: TimewebClient, name: str, body: str) -> dict:
    data = client.post("/ssh-keys", json={"name": name, "body": body})
    return _pick(data, "ssh_key", default=data) or {}


def _generate_keypair(path: Path) -> str:
    """Генерирует ed25519-пару, возвращает публичную часть."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(path), "-C", "timeweb-agent"],
            check=True,
            capture_output=True,
        )
    pub = path.with_suffix(".pub")
    return pub.read_text().strip()


def ensure_ssh_key(client: TimewebClient, key_name: str = "timeweb-agent") -> dict:
    """Возвращает SSH-ключ из панели: существующий с таким именем либо
    сгенерированный локально и загруженный в панель."""
    existing = find_ssh_key(client, key_name)
    if existing:
        return existing
    local_key = Path.home() / ".ssh" / "timeweb_agent_ed25519"
    pub = _generate_keypair(local_key)
    return add_ssh_key(client, key_name, pub)


# ====================================================================== #
#  Облачные серверы
# ====================================================================== #
def list_servers(client: TimewebClient, search: str | None = None) -> list:
    params = {"search": search} if search else None
    return client.get_all("/servers", params=params, key="servers")


def get_server(client: TimewebClient, server_id: int | str) -> dict:
    return _pick(client.get(f"/servers/{server_id}"), "server", default={}) or {}


def resolve_server(client: TimewebClient, name_or_id: str) -> Optional[dict]:
    for s in list_servers(client):
        if str(s.get("id")) == str(name_or_id) or str(s.get("name")) == str(name_or_id):
            return s
    return None


def server_ip(server: dict) -> Optional[str]:
    """Публичный IPv4 сервера."""
    ips = server.get("ips") or []
    for net in server.get("networks") or []:
        if net.get("type") == "public" or net.get("is_public"):
            for ip in net.get("ips") or []:
                return str(ip.get("ip"))
    for ip in ips:
        addr = ip.get("ip")
        if addr:
            return str(addr)
    return None


def get_server_ips(client: TimewebClient, server_id: int | str) -> list:
    return _pick(client.get(f"/servers/{server_id}/ips"), "server_ips", default=[]) or []


def create_server(
    client: TimewebClient,
    name: str,
    os_id: str = "auto",
    preset_id: str = "auto",
    ssh_key_ids: list | None = None,
    project_id: str | None = None,
    is_ddos_guard: bool | None = None,
    cloud_init: str | None = None,
    comment: str | None = None,
    wait: bool = False,
    wait_timeout: int = 900,
    verbose: bool = False,
) -> dict:
    """Создаёт облачный сервер. os_id/preset_id могут быть «auto»."""
    if os_id == "auto":
        os_id = pick_os(client).get("id")
    if preset_id == "auto":
        preset_id = pick_server_preset(client).get("id")
    payload: dict = {"name": name, "os_id": os_id, "preset_id": preset_id}
    if ssh_key_ids:
        payload["ssh_keys_ids"] = ssh_key_ids
    if project_id:
        payload["project_id"] = project_id
    if is_ddos_guard is not None:
        payload["is_ddos_guard"] = bool(is_ddos_guard)
    if cloud_init:
        payload["cloud_init"] = cloud_init
    if comment:
        payload["comment"] = comment
    data = client.post("/servers", json=payload)
    server = _pick(data, "server", default=data) or {}
    if wait and server.get("id"):
        server = wait_server(client, server["id"], wait_timeout, verbose)
    return server


def wait_server(client: TimewebClient, server_id: int | str, timeout: int = 900, verbose: bool = False) -> dict:
    return _wait_status(client, f"/servers/{server_id}", "server", SERVER_READY, SERVER_BUSY, SERVER_ERROR, timeout, verbose)


def server_action(client: TimewebClient, server_id: int | str, action: str) -> Any:
    """action: reboot, shutdown, start, hard-reboot, hard-shutdown, clone..."""
    if action in {"reboot", "shutdown", "start", "hard-reboot", "hard-shutdown"}:
        return client.post(f"/servers/{server_id}/{action}")
    return client.post(f"/servers/{server_id}/action", json={"action": action})


def reset_server_password(client: TimewebClient, server_id: int | str) -> dict:
    return client.post(f"/servers/{server_id}/reset-password") or {}


def delete_server(client: TimewebClient, server_id: int | str) -> Any:
    return client.delete(f"/servers/{server_id}")


def server_logs(client: TimewebClient, server_id: int | str, order: str = "asc") -> list:
    data = client.get(f"/servers/{server_id}/logs", params={"order": order})
    return _pick(data, "server_logs", default=[]) or []


# ====================================================================== #
#  Базы данных (кластеры DBaaS)
# ====================================================================== #
def list_databases(client: TimewebClient) -> list:
    return client.get_all("/databases", key="dbs")


def get_database(client: TimewebClient, db_id: int | str) -> dict:
    return _pick(client.get(f"/databases/{db_id}"), "db", default={}) or {}


def resolve_database(client: TimewebClient, name_or_id: str) -> Optional[dict]:
    for d in list_databases(client):
        if str(d.get("id")) == str(name_or_id) or str(d.get("name")) == str(name_or_id):
            return d
    return None


def create_database(
    client: TimewebClient,
    name: str,
    db_type: str,
    admin_login: str = "admin",
    admin_password: str | None = None,
    preset_id: str = "auto",
    instance_name: str | None = None,
    project_id: str | None = None,
    description: str | None = None,
    wait: bool = False,
    wait_timeout: int = 900,
    verbose: bool = False,
) -> dict:
    """Создаёт кластер БД (mysql, postgresql, redis, ...)."""
    if not admin_password:
        admin_password = secrets.token_urlsafe(18)
    if preset_id == "auto":
        preset_id = pick_db_preset(client, family=db_type.split("_")[0]).get("id")
    payload: dict = {
        "name": name,
        "type": db_type,
        "preset_id": preset_id,
        "admin": {"login": admin_login, "password": admin_password},
        "instance": {"name": instance_name or name},
    }
    if project_id:
        payload["project_id"] = project_id
    if description:
        payload["description"] = description
    data = client.post("/databases", json=payload)
    db = _pick(data, "db", default=data) or {}
    db["_admin_login"] = admin_login
    db["_admin_password"] = admin_password
    if wait and db.get("id"):
        db = wait_database(client, db["id"], wait_timeout, verbose)
    return db


def wait_database(client: TimewebClient, db_id: int | str, timeout: int = 900, verbose: bool = False) -> dict:
    return _wait_status(client, f"/databases/{db_id}", "db", DB_READY, DB_BUSY, DB_ERROR, timeout, verbose)


def delete_database(client: TimewebClient, db_id: int | str) -> Any:
    return client.delete(f"/databases/{db_id}")


def list_db_admins(client: TimewebClient, db_id: int | str) -> list:
    return client.get_all(f"/databases/{db_id}/admins", key="admins")


def add_db_admin(
    client: TimewebClient,
    db_id: int | str,
    login: str,
    password: str | None = None,
    host: str | None = None,
    instance_id: int | str | None = None,
    privileges: list | None = None,
) -> dict:
    if not password:
        password = secrets.token_urlsafe(18)
    payload: dict = {"login": login, "password": password}
    if host:
        payload["host"] = host
    if instance_id:
        payload["instance_id"] = instance_id
    if privileges:
        payload["privileges"] = privileges
    data = client.post(f"/databases/{db_id}/admins", json=payload)
    admin = _pick(data, "admin", default=data) or {}
    admin["_password"] = password
    return admin


def list_db_instances(client: TimewebClient, db_id: int | str) -> list:
    return client.get_all(f"/databases/{db_id}/instances", key="instances")


def add_db_instance(client: TimewebClient, db_id: int | str, name: str, description: str | None = None) -> dict:
    payload: dict = {"name": name}
    if description:
        payload["description"] = description
    data = client.post(f"/databases/{db_id}/instances", json=payload)
    return _pick(data, "instance", default=data) or {}


def db_connection_info(db: dict) -> dict:
    """Собирает параметры подключения к кластеру БД."""
    host = None
    port = None
    for net in db.get("networks") or []:
        if net.get("type") == "public" or net.get("is_public"):
            host = net.get("ip") or net.get("host")
            port = net.get("port")
    return {
        "host": host or db.get("host"),
        "port": port or db.get("port"),
        "type": db.get("type"),
        "hash_type": db.get("hash_type"),
        "ip": db.get("ip"),
    }


# ====================================================================== #
#  Домены и DNS
# ====================================================================== #
def list_domains(client: TimewebClient) -> list:
    return client.get_all("/domains", key="domains")


def check_domain(client: TimewebClient, fqdn: str) -> bool:
    data = client.get(f"/check-domain/{fqdn}")
    return bool(data.get("is_domain_available"))


def add_domain(client: TimewebClient, fqdn: str) -> dict:
    data = client.post(f"/add-domain/{fqdn}")
    return _pick(data, "domain", default=data) or {}


def delete_domain(client: TimewebClient, fqdn: str) -> Any:
    return client.delete(f"/domains/{fqdn}")


def list_dns_records(client: TimewebClient, fqdn: str) -> list:
    return client.get_all(f"/domains/{fqdn}/dns-records", key="dns_records")


def add_dns_record(
    client: TimewebClient,
    fqdn: str,
    rtype: str,
    value: str,
    ttl: int | None = None,
    app_id: int | str | None = None,
) -> dict:
    payload: dict = {"type": rtype, "value": value}
    if ttl:
        payload["ttl"] = ttl
    if app_id:
        payload["app_id"] = app_id
    data = client.post(f"/domains/{fqdn}/dns-records", json=payload)
    return _pick(data, "dns_record", default=data) or {}


def update_dns_record(client: TimewebClient, fqdn: str, record_id: int | str, **fields) -> dict:
    data = client.patch(f"/domains/{fqdn}/dns-records/{record_id}", json=fields)
    return _pick(data, "dns_record", default=data) or {}


def delete_dns_record(client: TimewebClient, fqdn: str, record_id: int | str) -> Any:
    return client.delete(f"/domains/{fqdn}/dns-records/{record_id}")


def add_subdomain(client: TimewebClient, fqdn: str, subdomain: str) -> dict:
    data = client.post(f"/domains/{fqdn}/subdomains/{subdomain}")
    return _pick(data, "subdomain", default=data) or {}


# ====================================================================== #
#  PaaS-приложения (Timeweb Apps)
# ====================================================================== #
def list_vcs_providers(client: TimewebClient) -> list:
    return client.get_all("/vcs-provider", key="providers")


def connect_vcs(client: TimewebClient, provider_type: str, token: str) -> dict:
    data = client.post(
        "/vcs-provider",
        json={"provider_type": provider_type, "provider_token": token},
    )
    return _pick(data, "provider", default=data) or {}


def delete_vcs(client: TimewebClient, provider_id: int | str) -> Any:
    return client.delete(f"/vcs-provider/{provider_id}")


def list_repos(client: TimewebClient, provider_id: int | str) -> list:
    data = client.get(f"/vcs-provider/{provider_id}/repository")
    return _pick(data, "repositories", "repos", default=[]) or []


def list_branches(client: TimewebClient, provider_id: int | str, repo_id: int | str) -> list:
    data = client.get(f"/vcs-provider/{provider_id}/repository/{repo_id}/branch")
    return _pick(data, "branches", default=[]) or []


def list_frameworks(client: TimewebClient) -> dict:
    return client.get("/frameworks/apps") or {}


def list_app_presets(client: TimewebClient) -> dict:
    return client.get("/presets/apps") or {}


def list_apps(client: TimewebClient) -> list:
    return client.get_all("/apps", key="apps")


def get_app(client: TimewebClient, app_id: int | str) -> dict:
    return _pick(client.get(f"/apps/{app_id}"), "app", default={}) or {}


def resolve_app(client: TimewebClient, name_or_id: str) -> Optional[dict]:
    for a in list_apps(client):
        if str(a.get("id")) == str(name_or_id) or str(a.get("name")) == str(name_or_id):
            return a
    return None


def pick_framework(client: TimewebClient, app_type: str, language: str | None = None) -> Optional[dict]:
    data = list_frameworks(client)
    key = "backend_frameworks" if app_type == "backend" else "frontend_frameworks"
    frameworks = data.get(key) or data.get("frameworks") or []
    if not frameworks:
        return None
    if language:
        for f in frameworks:
            if language.lower() in str(f.get("language", "")).lower():
                return f
    return frameworks[0]


def create_app(
    client: TimewebClient,
    name: str,
    app_type: str,
    provider_id: int | str,
    repository_id: int | str,
    branch_name: str,
    framework_id: int | str | None = None,
    build_cmd: str | None = None,
    run_cmd: str | None = None,
    index_dir: str | None = None,
    envs: dict | None = None,
    preset_id: int | str | None = None,
    is_auto_deploy: bool = False,
    project_id: str | None = None,
    comment: str | None = None,
) -> dict:
    payload: dict = {
        "name": name,
        "type": app_type,
        "provider_id": provider_id,
        "repository_id": repository_id,
        "branch_name": branch_name,
        "is_auto_deploy": bool(is_auto_deploy),
    }
    if framework_id is not None:
        payload["framework"] = {"id": framework_id}
    if build_cmd:
        payload["build_cmd"] = build_cmd
    if run_cmd:
        payload["run_cmd"] = run_cmd
    if index_dir:
        payload["index_dir"] = index_dir
    if envs:
        payload["envs"] = envs
    if preset_id:
        payload["preset_id"] = preset_id
    if project_id:
        payload["project_id"] = project_id
    if comment:
        payload["comment"] = comment
    data = client.post("/apps", json=payload)
    return _pick(data, "app", default=data) or {}


def deploy_app(client: TimewebClient, app_id: int | str, commit_sha: str | None = None) -> dict:
    payload: dict = {}
    if commit_sha:
        payload["commit_sha"] = commit_sha
    data = client.post(f"/apps/{app_id}/deploy", json=payload or None)
    return _pick(data, "deploy", default=data) or {}


def app_logs(client: TimewebClient, app_id: int | str) -> list:
    data = client.get(f"/apps/{app_id}/logs")
    return _pick(data, "app_logs", default=[]) or []


def app_deploys(client: TimewebClient, app_id: int | str) -> list:
    data = client.get(f"/apps/{app_id}/deploys")
    return _pick(data, "deploys", default=[]) or []


def delete_app(client: TimewebClient, app_id: int | str) -> Any:
    return client.delete(f"/apps/{app_id}")


def bind_app_domain(client: TimewebClient, app_id: int | str, fqdn: str) -> dict:
    """Привязывает домен/поддомен к приложению через DNS-запись с app_id."""
    data = client.post(
        f"/domains/{fqdn}/dns-records",
        json={"type": "A", "value": "", "app_id": app_id},
    )
    return _pick(data, "dns_record", default=data) or {}
