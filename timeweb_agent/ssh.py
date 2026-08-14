"""SSH-подключение к серверам Timeweb для деплоя.

Использует paramiko (устанавливается опционально:
    pip install paramiko
). Если paramiko не установлен, команды, требующие SSH, сообщат об этом.

Подключение настраивается переменными окружения:
    TW_SSH_HOST, TW_SSH_PORT, TW_SSH_USER, TW_SSH_PASSWORD,
    TW_SSH_KEY_PATH, TW_SSH_KEY_PASSPHRASE
"""
from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import Optional

from . import config

try:
    import paramiko  # type: ignore
    HAS_PARAMIKO = True
except ImportError:  # pragma: no cover
    HAS_PARAMIKO = False


class SSHError(RuntimeError):
    pass


class SSHClient:
    def __init__(
        self,
        host: str,
        user: str = "root",
        port: int = 22,
        password: str | None = None,
        key_path: str | None = None,
        key_passphrase: str | None = None,
        connect_timeout: int = 30,
    ):
        if not HAS_PARAMIKO:
            raise SSHError(
                "Для SSH-операций нужен paramiko: pip install -r timeweb_agent/requirements.txt"
            )
        self.host = host
        self.user = user
        self.port = int(port)
        self.password = password
        self.key_path = key_path
        self.key_passphrase = key_passphrase
        self.connect_timeout = connect_timeout
        self._client: Optional[paramiko.SSHClient] = None

    # ------------------------------------------------------------------ #
    def connect(self) -> "SSHClient":
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user,
            "timeout": self.connect_timeout,
            "banner_timeout": self.connect_timeout,
            "auth_timeout": self.connect_timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if self.key_path and Path(self.key_path).exists():
            kwargs["key_filename"] = self.key_path
            if self.key_passphrase:
                kwargs["passphrase"] = self.key_passphrase
        elif self.password:
            kwargs["password"] = self.password
        else:
            raise SSHError(
                "Не задан ни пароль (TW_SSH_PASSWORD), ни ключ (TW_SSH_KEY_PATH) для SSH."
            )
        try:
            client.connect(**kwargs)
        except Exception as e:  # paramiko throws many exception types
            raise SSHError(f"Не удалось подключиться к {self.host}:{self.port} — {e}") from e
        self._client = client
        return self

    @property
    def client(self) -> paramiko.SSHClient:
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self) -> "SSHClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def exec(self, command: str, check: bool = True, timeout: int = 1800, print_output: bool = True) -> tuple[int, str, str]:
        """Выполняет команду. Возвращает (код, stdout, stderr)."""
        if print_output:
            print(f"$ {command}", flush=True)
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        stdin.close()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if print_output and out.strip():
            print(out.rstrip(), flush=True)
        if err.strip():
            print(err.rstrip(), flush=True)
        if check and code != 0:
            raise SSHError(f"Команда завершилась с кодом {code}: {command}\n{err[-2000:]}")
        return code, out, err

    def upload(self, local: str | Path, remote: str) -> None:
        """Загружает файл или папку по SFTP (рекурсивно)."""
        local = Path(local)
        sftp = self.client.open_sftp()
        try:
            if local.is_dir():
                self._upload_dir(sftp, local, remote)
            else:
                self._ensure_dir(sftp, str(Path(remote).parent))
                sftp.put(str(local), remote)
        finally:
            sftp.close()
        print(f"[upload] {local} -> {self.host}:{remote}", flush=True)

    def _upload_dir(self, sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
        self._ensure_dir(sftp, remote)
        for child in local.iterdir():
            if child.name in {".git", "__pycache__", ".venv", "venv", "node_modules", ".env"}:
                continue
            target = f"{remote.rstrip('/')}/{child.name}"
            if child.is_dir():
                self._upload_dir(sftp, child, target)
            else:
                try:
                    sftp.stat(target)
                except IOError:
                    pass
                sftp.put(str(child), target)

    @staticmethod
    def _ensure_dir(sftp: paramiko.SFTPClient, path: str) -> None:
        parts = path.split("/")
        cur = ""
        for part in parts:
            if not part:
                cur = "/"
                continue
            cur = f"{cur.rstrip('/')}/{part}"
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)

    def put_text(self, content: str, remote: str, mode: int | None = None) -> None:
        """Записывает текст в файл на сервере."""
        sftp = self.client.open_sftp()
        try:
            self._ensure_dir(sftp, str(Path(remote).parent))
            with sftp.open(remote, "w") as fh:
                fh.write(content)
            if mode is not None:
                sftp.chmod(remote, mode)
        finally:
            sftp.close()
        print(f"[write] {remote} ({len(content)} байт)", flush=True)

    def download(self, remote: str, local: str | Path) -> None:
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        sftp = self.client.open_sftp()
        try:
            sftp.get(remote, str(local))
        finally:
            sftp.close()
        print(f"[download] {self.host}:{remote} -> {local}", flush=True)


def from_env(host: str | None = None) -> SSHClient:
    """Создаёт SSHClient из переменных окружения (.env)."""
    host = host or config.SSH_HOST
    if not host:
        raise SSHError(
            "Не задан SSH-хост. Укажите --host или переменную TW_SSH_HOST в .env"
        )
    return SSHClient(
        host=host,
        user=config.SSH_USER,
        port=config.SSH_PORT,
        password=config.SSH_PASSWORD,
        key_path=config.SSH_KEY_PATH,
        key_passphrase=config.SSH_KEY_PASSPHRASE,
    )
