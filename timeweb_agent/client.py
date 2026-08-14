"""Низкоуровневый HTTP-клиент Timeweb Cloud API v1.

Работает напрямую с REST API: https://api.timeweb.cloud/api/v1
Аутентификация — JWT-токен панели (раздел «API и Terraform»).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests


class TimewebError(RuntimeError):
    """Ошибка API Timeweb Cloud."""

    def __init__(
        self,
        status_code: int,
        error_code: Optional[str] = None,
        message: Any = None,
        response_id: Optional[str] = None,
        payload: Any = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.response_id = response_id
        self.payload = payload
        text = f"HTTP {status_code}"
        if error_code:
            text += f" [{error_code}]"
        if message:
            if isinstance(message, (list, tuple)):
                message = "; ".join(str(m) for m in message)
            text += f": {message}"
        super().__init__(text)


class TimewebClient:
    """HTTP-клиент с retry, обработкой rate-limit и ошибок API."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.timeweb.cloud/api/v1",
        timeout: int = 60,
        retries: int = 5,
        verbose: bool = False,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------ #
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        url = self.base_url + (path if path.startswith("/") else "/" + path)
        # Пути, начинающиеся с /api/, считаются абсолютными относительно хоста —
        # это нужно для эндпоинтов другой версии API (например /api/v2/...).
        if path.startswith("/api/"):
            host = self.base_url.split("/api/", 1)[0]
            url = host + path
        if self.verbose:
            print(f"[http] {method} {path}", flush=True)
        for attempt in range(self.retries + 1):
            resp = self.session.request(
                method, url, params=params, json=json, timeout=self.timeout
            )
            if resp.status_code == 429:  # rate limit
                try:
                    wait = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    wait = float(2 ** attempt)
                time.sleep(min(max(wait, 0.5), 30))
                continue
            if resp.status_code >= 500 and attempt < self.retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            break

        if 200 <= resp.status_code < 300:
            if resp.status_code == 204 or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return resp.text
        raise TimewebError(
            status_code=resp.status_code,
            error_code=(resp.json() or {}).get("error_code")
            if "json" in resp.headers.get("Content-Type", "")
            else None,
            message=self._error_message(resp),
            response_id=(resp.json() or {}).get("response_id")
            if "json" in resp.headers.get("Content-Type", "")
            else None,
            payload=self._safe_json(resp),
        )

    @staticmethod
    def _safe_json(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return resp.text

    @staticmethod
    def _error_message(resp: requests.Response) -> Any:
        data = TimewebClient._safe_json(resp)
        if isinstance(data, dict):
            return data.get("message") or data.get("error") or None
        return data

    # ------------------------------------------------------------------ #
    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self.request("POST", path, params=params, json=json)

    def patch(self, path: str, json: Optional[dict] = None) -> Any:
        return self.request("PATCH", path, json=json)

    def put(self, path: str, json: Optional[dict] = None) -> Any:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # ------------------------------------------------------------------ #
    def get_all(
        self,
        path: str,
        params: Optional[dict] = None,
        key: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """Обходит все страницы коллекции и возвращает полный список элементов."""
        params = dict(params or {})
        items: list = []
        offset = 0
        while True:
            data = self.get(path, params={**params, "limit": limit, "offset": offset})
            page = self._extract_list(data, key)
            if not page:
                break
            items.extend(page)
            total = ((data or {}).get("meta") or {}).get("total")
            if total is not None and len(items) >= total:
                break
            if len(page) < limit:
                break
            offset += limit
        return items

    @staticmethod
    def _extract_list(data: Any, key: Optional[str]) -> list:
        if not isinstance(data, dict):
            return []
        if key and key in data and isinstance(data[key], list):
            return data[key]
        for k, v in data.items():
            if k in {"meta", "response_id"}:
                continue
            if isinstance(v, list):
                return v
        return []
