"""Рецепты развёртывания на VPS Timeweb по SSH.

Что умеет:
  * provision()            — базовая подготовка сервера (пакеты, docker, fail2ban)
  * deploy_static_site()   — статический сайт: nginx + Let's Encrypt
  * deploy_docker_app()    — приложение из локальной папки: docker compose + nginx + TLS
  * deploy_from_git()      — приложение из git-репозитория (clone/pull + compose)
  * deploy_mysql()         — MySQL в docker-контейнере (альтернатива DBaaS)
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from .ssh import SSHClient

NGINX_STATIC_TEMPLATE = """\
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    root /var/www/{domain};
    index index.html index.htm;

    location / {{
        try_files $uri $uri/ =404;
    }}

    location ~ /\\. {{
        deny all;
    }}
}}
"""

NGINX_PROXY_TEMPLATE = """\
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    client_max_body_size 100M;

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }}
}}
"""

# Команды, которые просит выполнить поддержка Timeweb для проверки
# конфигурации сервера (после смены тарифа / увеличения диска).
SUPPORT_DIAG_COMMANDS = [
    ("nproc", "Количество ядер процессора"),
    ("free -h", "Оперативная память (смотрите строку Mem:)"),
    ("df -h", "Смонтированные разделы и свободное место"),
    ("fdisk -l", "Физический диск и разделы (нужны права root)"),
    ("lsblk", "Дополнительно: дерево дисков и разделов"),
]


def run_support_diagnostics(ssh: SSHClient) -> list:
    """Выполняет диагностические команды поддержки Timeweb.

    Возвращает список: {command, description, exit_code, output, error}.
    """
    results = []
    for command, description in SUPPORT_DIAG_COMMANDS:
        code, out, err = ssh.exec(command, check=False, print_output=False)
        if code != 0 and command.startswith("fdisk"):
            # fdisk требует root; пробуем sudo без пароля
            code2, out2, err2 = ssh.exec(f"sudo -n {command}", check=False, print_output=False)
            if code2 == 0:
                code, out, err = code2, out2, err2
            else:
                err = (
                    f"{err}\n"
                    f"[требуются права root — выполните на сервере вручную: sudo {command}]"
                ).strip()
        results.append(
            {
                "command": command,
                "description": description,
                "exit_code": code,
                "output": (out or "").strip(),
                "error": (err or "").strip(),
            }
        )
    return results


# ---------------------------------------------------------------------- #
def provision(ssh: SSHClient, with_docker: bool = True, with_fail2ban: bool = True) -> None:
    """Базовая подготовка VPS: обновление пакетов, docker, nginx, certbot."""
    ssh.exec("export DEBIAN_FRONTEND=noninteractive")
    ssh.exec("apt-get update -y && apt-get upgrade -y")
    ssh.exec("apt-get install -y curl wget git nginx ca-certificates gnupg lsb-release ufw")
    if with_fail2ban:
        ssh.exec("apt-get install -y fail2ban")
        ssh.exec("systemctl enable --now fail2ban || true")
    if with_docker:
        ensure_docker(ssh)
    ssh.exec("systemctl enable --now nginx || true")
    print("[ok] Базовая подготовка сервера завершена", flush=True)


def ensure_docker(ssh: SSHClient) -> None:
    code, _, _ = ssh.exec("command -v docker || true", check=False, print_output=False)
    if code == 0:
        print("[ok] Docker уже установлен", flush=True)
        return
    ssh.exec("curl -fsSL https://get.docker.com | sh")
    ssh.exec("systemctl enable --now docker")
    print("[ok] Docker установлен", flush=True)


def ensure_certbot(ssh: SSHClient) -> None:
    code, _, _ = ssh.exec("command -v certbot || true", check=False, print_output=False)
    if code == 0:
        return
    ssh.exec("apt-get install -y certbot python3-certbot-nginx")


# ---------------------------------------------------------------------- #
def deploy_static_site(
    ssh: SSHClient,
    local_dir: str | Path,
    domain: str,
    ssl: bool = True,
    ssl_email: Optional[str] = None,
    title: Optional[str] = None,
) -> None:
    """Разворачивает статический сайт: nginx + (опционально) Let's Encrypt.

    Если в папке нет index.html — агент сам создаст красивую
    страницу-заглушку (полезно для новых сайтов)."""
    domain = domain.lower().strip()
    local_dir = Path(local_dir)
    has_index = (
        local_dir.is_dir()
        and any(f.name in {"index.html", "index.htm"} for f in local_dir.iterdir() if f.is_file())
    )
    if not local_dir.is_dir() or not has_index:
        local_dir = make_placeholder_site(
            local_dir, title or domain, f"Домен {domain} · сайт готов к наполнению"
        )

    ssh.exec("apt-get install -y nginx || true")
    ssh.exec(f"mkdir -p /var/www/{domain}")

    # загрузка файлов сайта
    ssh.upload(local_dir, f"/var/www/{domain}")

    # конфиг nginx
    conf = NGINX_STATIC_TEMPLATE.format(domain=domain)
    ssh.put_text(conf, f"/etc/nginx/sites-available/{domain}")
    ssh.exec(f"ln -sf /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/{domain}")
    ssh.exec("nginx -t")
    ssh.exec("systemctl reload nginx")

    if ssl:
        ensure_certbot(ssh)
        email_arg = f"--email {ssl_email}" if ssl_email else "--register-unsafely-without-email"
        ssh.exec(
            f"certbot --nginx -d {domain} -n --agree-tos {email_arg} --redirect || true"
        )
        ssh.exec("systemctl reload nginx")
    print(f"[ok] Сайт развёрнут: http{'s' if ssl else ''}://{domain}", flush=True)


# ---------------------------------------------------------------------- #
def deploy_docker_app(
    ssh: SSHClient,
    local_dir: str | Path,
    domain: str,
    port: int = 8000,
    app_name: str | None = None,
    ssl: bool = True,
    ssl_email: Optional[str] = None,
    compose_file: str = "docker-compose.yml",
) -> None:
    """Разворачивает приложение из локальной папки через docker compose
    и проксирует его через nginx + Let's Encrypt."""
    domain = domain.lower().strip()
    local_dir = Path(local_dir)
    app_name = app_name or local_dir.name
    remote_dir = f"/opt/apps/{app_name}"

    if not (local_dir / compose_file).is_file():
        raise FileNotFoundError(
            f"В папке {local_dir} не найден {compose_file}. "
            "Для docker-деплоя нужен docker-compose.yml."
        )

    ensure_docker(ssh)
    ssh.exec(f"mkdir -p {remote_dir}")
    ssh.upload(local_dir, remote_dir)
    ssh.exec(f"cd {remote_dir} && docker compose -f {compose_file} up -d --build")

    ssh.exec("apt-get install -y nginx || true")
    conf = NGINX_PROXY_TEMPLATE.format(domain=domain, port=port)
    ssh.put_text(conf, f"/etc/nginx/sites-available/{domain}")
    ssh.exec(f"ln -sf /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/{domain}")
    ssh.exec("nginx -t")
    ssh.exec("systemctl reload nginx")

    if ssl:
        ensure_certbot(ssh)
        email_arg = f"--email {ssl_email}" if ssl_email else "--register-unsafely-without-email"
        ssh.exec(
            f"certbot --nginx -d {domain} -n --agree-tos {email_arg} --redirect || true"
        )
        ssh.exec("systemctl reload nginx")
    print(f"[ok] Приложение развёрнуто: http{'s' if ssl else ''}://{domain} (порт {port})", flush=True)


# ---------------------------------------------------------------------- #
def deploy_from_git(
    ssh: SSHClient,
    repo: str,
    branch: str = "main",
    domain: str | None = None,
    port: int = 8000,
    app_name: str | None = None,
    ssl: bool = True,
    ssl_email: Optional[str] = None,
    compose_file: str = "docker-compose.yml",
) -> None:
    """Разворачивает приложение из git-репозитория на VPS."""
    app_name = app_name or repo.rstrip("/").split("/")[-1].replace(".git", "")
    remote_dir = f"/opt/apps/{app_name}"
    ensure_docker(ssh)
    ssh.exec(f"mkdir -p /opt/apps")
    if ssh.exec(f"test -d {remote_dir}/.git && echo yes || echo no", check=False, print_output=False)[1].strip() == "yes":
        ssh.exec(f"cd {remote_dir} && git fetch --all && git reset --hard origin/{branch}")
    else:
        ssh.exec(f"git clone --depth 1 --branch {branch} {repo} {remote_dir}")
    ssh.exec(f"cd {remote_dir} && docker compose -f {compose_file} up -d --build")

    if domain:
        ssh.exec("apt-get install -y nginx || true")
        conf = NGINX_PROXY_TEMPLATE.format(domain=domain, port=port)
        ssh.put_text(conf, f"/etc/nginx/sites-available/{domain}")
        ssh.exec(f"ln -sf /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/{domain}")
        ssh.exec("nginx -t")
        ssh.exec("systemctl reload nginx")
        if ssl:
            ensure_certbot(ssh)
            email_arg = f"--email {ssl_email}" if ssl_email else "--register-unsafely-without-email"
            ssh.exec(f"certbot --nginx -d {domain} -n --agree-tos {email_arg} --redirect || true")
            ssh.exec("systemctl reload nginx")
    print(f"[ok] Приложение из git развёрнуто: {remote_dir}", flush=True)


# ---------------------------------------------------------------------- #
def deploy_mysql(
    ssh: SSHClient,
    db_name: str,
    db_user: str,
    db_password: str | None = None,
    port: int = 3306,
    volume_name: str | None = None,
) -> dict:
    """Поднимает MySQL 8 в docker-контейнере с постоянным томом.

    Возвращает параметры подключения."""
    db_password = db_password or secrets.token_urlsafe(16)
    volume_name = volume_name or f"{db_name}_data"
    ensure_docker(ssh)
    ssh.exec(
        f"docker rm -f mysql-{db_name} || true", check=False
    )
    ssh.exec(
        f"docker volume create {volume_name} || true"
    )
    ssh.exec(
        "docker run -d --restart unless-stopped "
        f"--name mysql-{db_name} "
        f"-p 127.0.0.1:{port}:3306 "
        f"-e MYSQL_ROOT_PASSWORD={secrets.token_urlsafe(16)} "
        f"-e MYSQL_DATABASE={db_name} "
        f"-e MYSQL_USER={db_user} "
        f"-e MYSQL_PASSWORD={db_password} "
        f"-v {volume_name}:/var/lib/mysql "
        "mysql:8.0 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci"
    )
    print(f"[ok] MySQL запущен: 127.0.0.1:{port}, база {db_name}, пользователь {db_user}", flush=True)
    return {
        "host": "127.0.0.1",
        "port": port,
        "database": db_name,
        "user": db_user,
        "password": db_password,
        "container": f"mysql-{db_name}",
    }


def deploy_postgres(
    ssh: SSHClient,
    db_name: str,
    db_user: str,
    db_password: str | None = None,
    port: int = 5432,
    volume_name: str | None = None,
    tag: str = "16-alpine",
) -> dict:
    """Поднимает PostgreSQL в docker-контейнере с постоянным томом."""
    db_password = db_password or secrets.token_urlsafe(16)
    volume_name = volume_name or f"pgdata_{db_name}"
    ensure_docker(ssh)
    ssh.exec(f"docker rm -f pg-{db_name} || true", check=False)
    ssh.exec(f"docker volume create {volume_name} || true")
    ssh.exec(
        "docker run -d --restart unless-stopped "
        f"--name pg-{db_name} "
        f"-p 127.0.0.1:{port}:5432 "
        f"-e POSTGRES_DB={db_name} "
        f"-e POSTGRES_USER={db_user} "
        f"-e POSTGRES_PASSWORD={db_password} "
        f"-v {volume_name}:/var/lib/postgresql/data "
        f"postgres:{tag}"
    )
    print(f"[ok] PostgreSQL запущен: 127.0.0.1:{port}, база {db_name}, пользователь {db_user}", flush=True)
    return {
        "host": "127.0.0.1",
        "port": port,
        "database": db_name,
        "user": db_user,
        "password": db_password,
        "container": f"pg-{db_name}",
    }


def deploy_redis(
    ssh: SSHClient,
    name: str = "redis",
    password: str | None = None,
    port: int = 6379,
    volume_name: str | None = None,
    tag: str = "7-alpine",
) -> dict:
    """Поднимает Redis в docker-контейнере с паролем и постоянным томом."""
    password = password or secrets.token_urlsafe(16)
    volume_name = volume_name or f"redis_data_{name}"
    ensure_docker(ssh)
    ssh.exec(f"docker rm -f redis-{name} || true", check=False)
    ssh.exec(f"docker volume create {volume_name} || true")
    ssh.exec(
        "docker run -d --restart unless-stopped "
        f"--name redis-{name} "
        f"-p 127.0.0.1:{port}:6379 "
        f"-v {volume_name}:/data "
        f"redis:{tag} redis-server --requirepass {password}"
    )
    print(f"[ok] Redis запущен: 127.0.0.1:{port}, контейнер redis-{name}", flush=True)
    return {
        "host": "127.0.0.1",
        "port": port,
        "password": password,
        "container": f"redis-{name}",
    }


PLACEHOLDER_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
         background:radial-gradient(800px 500px at 80% -10%, rgba(79,124,255,.25), transparent 60%),
                    radial-gradient(700px 400px at 0% 110%, rgba(124,92,255,.2), transparent 60%), #0b0f1a;
         color:#e8ecf6; }}
  .box {{ text-align:center; padding:40px; }}
  h1 {{ font-size:44px; margin:0 0 12px; }}
  p {{ color:#8b93a7; font-size:18px; }}
  .badge {{ display:inline-block; margin-top:24px; padding:8px 18px; border-radius:999px;
           background:rgba(46,204,143,.12); color:#2ecc8f; border:1px solid rgba(46,204,143,.4);
           font-size:14px; }}
</style>
</head>
<body>
  <div class="box">
    <h1>{title}</h1>
    <p>{subtitle}</p>
    <div class="badge">✅ Сайт развёрнут агентом Timeweb · HTTPS включён</div>
  </div>
</body>
</html>
"""


def make_placeholder_site(target_dir: Path, title: str, subtitle: str = "") -> Path:
    """Создаёт папку с index.html-заглушкой (если сайта ещё нет)."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    index = target_dir / "index.html"
    if not index.exists():
        index.write_text(
            PLACEHOLDER_HTML.format(
                title=title or "Новый сайт",
                subtitle=subtitle or "Скоро здесь появится контент. Сайт готов к наполнению.",
            ),
            encoding="utf-8",
        )
    return target_dir
