"""Проверки результатов — «глаза» агента.

Каждая проверка возвращает {"ok": bool, "detail": str}.
Проверки делятся на:
  * локальные (выполняются с компьютера агента): http, dns;
  * удалённые (по SSH): command, docker, postgres, redis, mysql, nginx, systemd.
"""
from __future__ import annotations

import socket
import time
from typing import Optional

import requests

from .ssh import SSHClient


# ---------------------------------------------------------------------- #
#  Локальные проверки
# ---------------------------------------------------------------------- #
def check_http(url: str, expect: int = 200, timeout: int = 45, retries: int = 4) -> dict:
    """Проверяет, что URL отвечает ожидаемым статусом (по умолчанию 200)."""
    if not url.startswith("http"):
        url = "https://" + url
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == expect:
                tls = "SSL/TLS ✓" if url.startswith("https") else ""
                return {"ok": True, "detail": f"{url} → {resp.status_code} {tls}".strip()}
            last_err = f"{url} → статус {resp.status_code} (ожидался {expect})"
        except requests.exceptions.SSLError as e:
            last_err = f"{url} → ошибка сертификата: {type(e).__name__}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{url} → {type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(5 * attempt)
    return {"ok": False, "detail": last_err or "нет ответа"}


def check_dns(domain: str, expect_ip: Optional[str] = None) -> dict:
    """Проверяет, что домен резолвится (и, опционально, на нужный IP)."""
    try:
        infos = socket.getaddrinfo(domain, None)
        ips = sorted({i[4][0] for i in infos})
        if not ips:
            return {"ok": False, "detail": f"{domain} не резолвится"}
        if expect_ip and expect_ip not in ips:
            return {
                "ok": False,
                "detail": f"{domain} → {', '.join(ips)} (ожидался {expect_ip}; DNS мог ещё не обновиться)",
            }
        return {"ok": True, "detail": f"{domain} → {', '.join(ips)}"}
    except socket.gaierror as e:
        return {"ok": False, "detail": f"{domain} не резолвится: {e}"}


# ---------------------------------------------------------------------- #
#  Проверки по SSH
# ---------------------------------------------------------------------- #
def check_command(ssh: SSHClient, command: str, contains: Optional[str] = None, timeout: int = 300) -> dict:
    code, out, err = ssh.exec(command, check=False, print_output=False, timeout=timeout)
    text = (out + err).strip()
    if code == 0 and (contains is None or contains in text):
        return {"ok": True, "detail": f"$ {command}\n{text[:400]}"}
    return {"ok": False, "detail": f"$ {command}\nexit={code}\n{text[:400]}"}


def check_docker(ssh: SSHClient, name: str) -> dict:
    code, out, _ = ssh.exec(
        f"docker ps --filter name=^{name}$ --format '{{{{.Names}}}} {{{{.Status}}}}'",
        check=False, print_output=False,
    )
    out = out.strip()
    if code == 0 and out:
        return {"ok": True, "detail": f"Контейнер {out}"}
    return {"ok": False, "detail": f"Контейнер «{name}» не запущен"}


def check_postgres(
    ssh: SSHClient, container: str, user: str, password: str, database: str, timeout: int = 120
) -> dict:
    cmd = (
        f"docker exec -e PGPASSWORD={password} {container} "
        f"psql -U {user} -d {database} -tAc 'SELECT 1'"
    )
    return check_command(ssh, cmd, contains="1", timeout=timeout)


def check_mysql(ssh: SSHClient, container: str, user: str, password: str, database: str) -> dict:
    cmd = f"docker exec {container} mysql -u{user} -p{password} -e 'SELECT 1' {database}"
    code, out, err = ssh.exec(cmd, check=False, print_output=False)
    if code == 0 and "1" in out:
        return {"ok": True, "detail": f"MySQL {database}: SELECT 1 → 1"}
    return {"ok": False, "detail": f"MySQL не отвечает: {err.strip()[-300:] or out.strip()[-300:]}"}


def check_redis(ssh: SSHClient, container: str, password: str) -> dict:
    cmd = f"docker exec {container} redis-cli -a {password} ping"
    code, out, err = ssh.exec(cmd, check=False, print_output=False)
    if code == 0 and "PONG" in out:
        return {"ok": True, "detail": "Redis: PING → PONG"}
    return {"ok": False, "detail": f"Redis не отвечает: {err.strip()[-200:] or out.strip()[-200:]}"}


def check_nginx(ssh: SSHClient) -> dict:
    code, out, err = ssh.exec("systemctl is-active nginx", check=False, print_output=False)
    if code == 0 and "active" in out:
        return {"ok": True, "detail": "Nginx: active (running)"}
    return {"ok": False, "detail": f"Nginx не активен: {out.strip()} {err.strip()}"}


# ---------------------------------------------------------------------- #
#  Диспетчер
# ---------------------------------------------------------------------- #
KINDS = {
    "http": check_http,
    "dns": check_dns,
    "command": check_command,
    "docker": check_docker,
    "postgres": check_postgres,
    "mysql": check_mysql,
    "redis": check_redis,
    "nginx": check_nginx,
}


def run_check(kind: str, params: dict, ssh: Optional[SSHClient] = None) -> dict:
    """Выполняет проверку по имени вида. Никогда не бросает исключений."""
    if kind not in KINDS:
        return {"ok": False, "detail": f"Неизвестный вид проверки: {kind}"}
    try:
        if kind in {"http", "dns"}:
            if kind == "http":
                return check_http(
                    str(params["url"]),
                    expect=int(params.get("expect", 200)),
                    timeout=int(params.get("timeout", 45)),
                    retries=int(params.get("retries", 4)),
                )
            return check_dns(str(params["domain"]), expect_ip=params.get("expect_ip"))
        if ssh is None:
            return {"ok": False, "detail": f"Проверка {kind} требует SSH-подключения"}
        if kind == "command":
            return check_command(
                ssh, str(params["command"]), contains=params.get("contains"),
                timeout=int(params.get("timeout", 300)),
            )
        if kind == "docker":
            return check_docker(ssh, str(params["name"]))
        if kind == "postgres":
            return check_postgres(
                ssh,
                str(params["container"]),
                str(params["user"]),
                str(params["password"]),
                str(params["database"]),
            )
        if kind == "mysql":
            return check_mysql(
                ssh,
                str(params["container"]),
                str(params["user"]),
                str(params["password"]),
                str(params["database"]),
            )
        if kind == "redis":
            return check_redis(ssh, str(params["container"]), str(params["password"]))
        if kind == "nginx":
            return check_nginx(ssh)
    except Exception as e:  # noqa: BLE001 — проверка не должна ронять весь прогон
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return {"ok": False, "detail": "проверка не выполнена"}
