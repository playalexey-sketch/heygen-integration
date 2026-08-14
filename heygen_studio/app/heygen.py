# -*- coding: utf-8 -*-
"""
Клиент HeyGen API — покрывает все параметры генерации,
которые вынесены в форму приложения.

Базовый адрес берётся из HEYGEN_BASE_URL, что позволяет переключить
приложение на тестовый (mock) сервер без единой правки кода.
"""
from __future__ import annotations

import mimetypes
import os
import time
from typing import Any, Optional

import requests

DEFAULT_BASE = "https://api.heygen.com"


class HeyGenError(Exception):
    def __init__(self, message: str, status: int = 0, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class HeyGen:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: int = 120):
        self.api_key = (api_key or os.getenv("HEYGEN_API_KEY", "")).strip()
        self.base = (base_url or os.getenv("HEYGEN_BASE_URL", DEFAULT_BASE)).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise HeyGenError("Не задан API-ключ HeyGen.")

    # ────────────────────────────────────────── low level
    def _headers(self, json_body: bool = True) -> dict:
        h = {"x-api-key": self.api_key, "accept": "application/json"}
        if json_body:
            h["content-type"] = "application/json"
        return h

    def _req(self, method: str, path: str, **kw) -> dict:
        url = f"{self.base}{path}"
        try:
            r = requests.request(method, url, timeout=self.timeout, **kw)
        except requests.exceptions.RequestException as e:
            raise HeyGenError(f"Нет связи с сервисом HeyGen ({self.base}): {e}") from e

        if r.status_code == 401:
            raise HeyGenError("Ключ API отклонён (401). Проверьте правильность ключа.",
                              401)
        if r.status_code == 402:
            raise HeyGenError("Недостаточно кредитов на аккаунте HeyGen (402).", 402)
        if r.status_code == 429:
            raise HeyGenError("Превышен лимит запросов (429). Попробуйте позже.", 429)
        if r.status_code >= 400:
            msg = r.text[:400]
            try:
                j = r.json()
                err = j.get("error") or j.get("message") or j
                msg = err.get("message") if isinstance(err, dict) else str(err)
            except Exception:
                pass
            raise HeyGenError(f"Ошибка HeyGen {r.status_code}: {msg}", r.status_code)
        try:
            return r.json()
        except Exception:
            return {}

    # ────────────────────────────────────────── assets
    def upload_asset(self, file_path: str) -> str:
        """Загрузка файла. Возвращает asset_id."""
        ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            data = f.read()
        url = f"{self.base}/v3/assets"
        try:
            r = requests.post(url, headers={"x-api-key": self.api_key,
                                            "content-type": ctype},
                              data=data, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise HeyGenError(f"Не удалось загрузить файл: {e}") from e
        if r.status_code >= 400:
            raise HeyGenError(f"Загрузка файла отклонена ({r.status_code}): "
                              f"{r.text[:200]}", r.status_code)
        d = (r.json() or {}).get("data", {})
        aid = d.get("asset_id") or d.get("id")
        if not aid:
            raise HeyGenError("Сервис не вернул идентификатор загруженного файла.")
        return aid

    # ────────────────────────────────────────── avatars
    def list_avatars(self) -> list[dict]:
        d = self._req("GET", "/v2/avatars", headers=self._headers(False))
        items = (d.get("data") or {}).get("avatars", []) or []
        out = []
        for a in items:
            out.append({
                "id": a.get("avatar_id") or a.get("id"),
                "name": a.get("avatar_name") or a.get("name") or "",
                "gender": a.get("gender", ""),
                "preview": a.get("preview_image_url"),
            })
        return [x for x in out if x["id"]]

    def create_avatar_from_photo(self, name: str, asset_id: str,
                                 group_id: str = "") -> dict:
        body = {"type": "photo", "name": name,
                "file": {"type": "asset_id", "asset_id": asset_id}}
        if group_id:
            body["avatar_group_id"] = group_id
        d = self._req("POST", "/v3/avatars", headers=self._headers(),
                      json=body).get("data", {})
        item = d.get("avatar_item") or {}
        return {"avatar_id": item.get("id"),
                "group_id": item.get("group_id") or (d.get("avatar_group") or {}).get("id"),
                "engines": item.get("supported_api_engines") or []}

    def create_avatar_from_prompt(self, name: str, prompt: str,
                                  avatar_id: str = "", group_id: str = "",
                                  reference_asset_ids: Optional[list[str]] = None) -> dict:
        body: dict = {"type": "prompt", "name": name, "prompt": prompt}
        if avatar_id:
            body["avatar_id"] = avatar_id
        if group_id:
            body["avatar_group_id"] = group_id
        if reference_asset_ids:
            body["reference_images"] = [
                {"type": "asset_id", "asset_id": a} for a in reference_asset_ids[:3]]
        d = self._req("POST", "/v3/avatars", headers=self._headers(),
                      json=body).get("data", {})
        item = d.get("avatar_item") or {}
        return {"avatar_id": item.get("id"),
                "group_id": item.get("group_id"),
                "engines": item.get("supported_api_engines") or []}

    def get_avatar_status(self, avatar_id: str) -> dict:
        for path in (f"/v2/photo_avatar/{avatar_id}", f"/v3/avatars/{avatar_id}"):
            try:
                d = self._req("GET", path, headers=self._headers(False)).get("data", {})
                if d:
                    return {"status": d.get("status", ""), "raw": d}
            except HeyGenError:
                continue
        return {"status": "unknown", "raw": {}}

    def wait_avatar(self, avatar_id: str, timeout: int = 300,
                    on_tick=None) -> str:
        end = time.time() + timeout
        while time.time() < end:
            st = self.get_avatar_status(avatar_id).get("status", "")
            if on_tick:
                on_tick(st)
            if st in ("completed", "success", "ready", "active"):
                return st
            if st in ("failed", "error"):
                raise HeyGenError("Не удалось подготовить аватар. "
                                  "Попробуйте другое фото: анфас, лицо крупно, ровный свет.")
            if st == "unknown":
                return st          # некоторые аватары доступны сразу
            time.sleep(4)
        return "timeout"

    # ── генерация внешности по описанию (текст → фото аватара)
    def generate_avatar_photos(self, name: str, age: str, gender: str, ethnicity: str,
                               orientation: str, pose: str, style: str,
                               appearance: str) -> str:
        body = {"name": name, "age": age, "gender": gender, "ethnicity": ethnicity,
                "orientation": orientation, "pose": pose, "style": style,
                "appearance": appearance}
        d = self._req("POST", "/v2/photo_avatar/photo/generate",
                      headers=self._headers(), json=body).get("data", {})
        gid = d.get("generation_id") or d.get("id")
        if not gid:
            raise HeyGenError("Сервис не вернул идентификатор генерации.")
        return gid

    def get_generation(self, generation_id: str) -> dict:
        return self._req("GET", f"/v2/photo_avatar/generation/{generation_id}",
                         headers=self._headers(False)).get("data", {})

    # ────────────────────────────────────────── voices
    def list_voices(self) -> list[dict]:
        d = self._req("GET", "/v2/voices", headers=self._headers(False))
        items = (d.get("data") or {}).get("voices", []) or []
        out = []
        for v in items:
            out.append({
                "id": v.get("voice_id"),
                "name": v.get("display_name") or v.get("name") or v.get("voice_name") or "",
                "language": v.get("language", ""),
                "gender": v.get("gender", ""),
                "emotion_support": bool(v.get("emotion_support")),
                "preview": v.get("preview_audio") or v.get("preview_audio_url"),
            })
        return [x for x in out if x["id"]]

    def clone_voice(self, name: str, asset_id: str) -> str:
        d = self._req("POST", "/v2/voice/clone", headers=self._headers(),
                      json={"name": name, "voice_name": name,
                            "audio_asset_id": asset_id}).get("data", {})
        cid = d.get("voice_clone_id") or d.get("id")
        if not cid:
            raise HeyGenError("Сервис не вернул идентификатор клонирования голоса.")
        return cid

    def wait_voice_clone(self, clone_id: str, timeout: int = 600,
                         on_tick=None) -> str:
        end = time.time() + timeout
        while time.time() < end:
            d = self._req("GET", f"/v2/voice/clone/{clone_id}",
                          headers=self._headers(False)).get("data", {})
            st = d.get("status", "")
            if on_tick:
                on_tick(st)
            if st in ("completed", "success", "ready") and d.get("voice_id"):
                return d["voice_id"]
            if st in ("failed", "error"):
                raise HeyGenError("Клонирование голоса не удалось. Нужна чистая "
                                  "запись 30–120 секунд без музыки и шума.")
            time.sleep(4)
        raise HeyGenError("Превышено время ожидания клонирования голоса.")

    # ────────────────────────────────────────── video
    def create_video(self, payload: dict) -> str:
        d = self._req("POST", "/v3/videos", headers=self._headers(),
                      json=payload).get("data", {})
        vid = d.get("video_id") or d.get("id")
        if not vid:
            raise HeyGenError("Сервис не вернул идентификатор видео.")
        return vid

    def get_video(self, video_id: str) -> dict:
        d = self._req("GET", f"/v3/videos/{video_id}",
                      headers=self._headers(False)).get("data", {})
        return {
            "status": d.get("status", ""),
            "progress": d.get("progress"),
            "video_url": d.get("video_url"),
            "thumbnail_url": d.get("thumbnail_url"),
            "subtitle_url": d.get("subtitle_url"),
            "duration": d.get("duration"),
            "error": (d.get("error") or {}).get("message")
                     if isinstance(d.get("error"), dict)
                     else d.get("error") or d.get("failure_message"),
        }

    def wallet(self) -> dict:
        try:
            return self._req("GET", "/v3/wallet",
                             headers=self._headers(False)).get("data", {})
        except HeyGenError:
            return {}
