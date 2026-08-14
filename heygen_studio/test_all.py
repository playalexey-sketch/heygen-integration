#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автотест всего механизма на ТЕСТОВОМ (mock) сервере HeyGen.

Проверяет сквозные сценарии: справочники, настройки, проверку связи,
списки аватаров и голосов, генерацию внешности, все режимы голоса,
валидацию, полный цикл генерации видео и скачивание файла.

    python test_all.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

os.environ["HEYGEN_BASE_URL"] = "http://127.0.0.1:8765"
os.environ["HEYGEN_API_KEY"] = "test_key"

import requests  # noqa: E402
import uvicorn  # noqa: E402

PORT = 8399
BASE = f"http://127.0.0.1:{PORT}"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> bool:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))
    return cond


def make_png(path: Path) -> None:
    import base64
    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))


def make_wav(path: Path, seconds: int = 1) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * seconds)


def wait_job(jid: str, timeout: int = 90) -> dict:
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        last = requests.get(f"{BASE}/api/job/{jid}", timeout=15).json()
        if last.get("status") in ("done", "error"):
            return last
        time.sleep(1.5)
    return last


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    photo, sample, audio = tmp / "p.png", tmp / "s.wav", tmp / "a.wav"
    make_png(photo)
    make_wav(sample, 2)
    make_wav(audio, 1)

    # ── поднимаем mock + приложение ──────────────────────────
    from mock.mock_heygen import app as mock_app
    from app.server import app as studio_app, CFG

    if CFG.is_file():
        CFG.unlink()

    threading.Thread(target=lambda: uvicorn.run(
        mock_app, host="127.0.0.1", port=8765, log_level="error"), daemon=True).start()
    threading.Thread(target=lambda: uvicorn.run(
        studio_app, host="127.0.0.1", port=PORT, log_level="error"), daemon=True).start()

    for _ in range(40):
        try:
            requests.get(f"{BASE}/api/settings", timeout=2)
            requests.get("http://127.0.0.1:8765/", timeout=2)
            break
        except Exception:
            time.sleep(0.4)
    else:
        print("Серверы не поднялись")
        return 1

    print("\n╔══ ТЕСТ МЕХАНИЗМА НА ТЕСТОВОМ API ══╗\n")

    # ── 1. интерфейс и справочники ───────────────────────────
    print("1. Интерфейс и справочники")
    r = requests.get(f"{BASE}/", timeout=15)
    check("страница формы открывается", r.status_code == 200 and "HeyGen" in r.text)
    o = requests.get(f"{BASE}/api/options", timeout=15).json()
    for k in ("engines", "aspect_ratios", "resolutions", "output_formats",
              "expressiveness", "caption_formats", "avatar_age", "avatar_gender",
              "avatar_ethnicity", "avatar_style", "avatar_orientation", "avatar_pose",
              "voice_emotions", "voice_locales", "voice_ranges"):
        check(f"справочник «{k}» отдан", bool(o.get(k)))
    ru = all(any(ord(c) > 1000 for c in p[1]) for p in o["aspect_ratios"])
    check("подписи полей на русском", ru)

    # ── 2. настройки и связь ─────────────────────────────────
    print("\n2. Подключение")
    requests.post(f"{BASE}/api/settings", json={
        "api_key": "test_key", "base_url": "http://127.0.0.1:8765"}, timeout=15)
    s = requests.get(f"{BASE}/api/settings", timeout=15).json()
    check("ключ сохраняется", s["has_key"])
    check("тестовый режим распознан", s["is_test_mode"])
    c = requests.post(f"{BASE}/api/check", timeout=30).json()
    check("проверка связи проходит", c.get("ok") is True, json.dumps(c, ensure_ascii=False))
    check("голоса получены", c.get("voices", 0) > 0)
    check("аватары получены", c.get("avatars", 0) > 0)

    # ── 3. списки ────────────────────────────────────────────
    print("\n3. Списки из HeyGen")
    av = requests.get(f"{BASE}/api/avatars", timeout=20).json()
    check("список аватаров", len(av.get("items", [])) > 0)
    vo = requests.get(f"{BASE}/api/voices", timeout=20).json()
    check("список голосов", len(vo.get("items", [])) > 0)
    check("у голоса есть язык и пол",
          all("language" in v and "gender" in v for v in vo["items"]))
    voice_id = vo["items"][0]["id"]
    avatar_id = av["items"][0]["id"]

    # ── 4. валидация ─────────────────────────────────────────
    print("\n4. Валидация формы")
    cases = [
        ({"avatar_mode": "photo", "voice_mode": "library"}, "фото"),
        ({"avatar_mode": "existing", "voice_mode": "library"}, "аватар"),
        ({"avatar_mode": "prompt", "voice_mode": "library"}, "внешность"),
    ]
    for data, word in cases:
        rr = requests.post(f"{BASE}/api/generate", data=data, timeout=20)
        check(f"ловит отсутствие: {word}",
              rr.status_code == 400 and word.lower() in rr.json().get("error", "").lower(),
              rr.text[:90])
    with photo.open("rb") as f:
        rr = requests.post(f"{BASE}/api/generate",
                           data={"avatar_mode": "photo", "voice_mode": "library"},
                           files={"photos": ("p.png", f, "image/png")}, timeout=20)
    check("ловит отсутствие текста", rr.status_code == 400 and "текст" in rr.json()["error"].lower())
    with photo.open("rb") as f:
        rr = requests.post(f"{BASE}/api/generate",
                           data={"avatar_mode": "photo", "voice_mode": "library",
                                 "script": "Привет"},
                           files={"photos": ("p.png", f, "image/png")}, timeout=20)
    check("ловит отсутствие голоса", rr.status_code == 400 and "голос" in rr.json()["error"].lower())
    with photo.open("rb") as f:
        rr = requests.post(f"{BASE}/api/generate",
                           data={"avatar_mode": "photo", "voice_mode": "library",
                                 "script": "к" * 5001, "voice_id_input": voice_id},
                           files={"photos": ("p.png", f, "image/png")}, timeout=20)
    check("ловит слишком длинный текст", rr.status_code == 400)
    rr = requests.post(f"{BASE}/api/generate",
                       data={"avatar_mode": "existing", "avatar_id": avatar_id,
                             "voice_mode": "library", "script": "Привет",
                             "voice_id_input": voice_id, "aspect_ratio": "3:7"}, timeout=20)
    check("ловит неверное соотношение сторон", rr.status_code == 400)

    # ── 5. генерация внешности ───────────────────────────────
    print("\n5. Генерация внешности по описанию")
    rr = requests.post(f"{BASE}/api/generate-appearance", data={
        "name": "Тест", "appearance": "женщина 35 лет, деловой стиль",
        "age": "Young Adult", "gender": "Woman", "ethnicity": "White",
        "orientation": "vertical", "pose": "half_body", "style": "Realistic"}, timeout=25)
    check("задача создана", rr.status_code == 200 and "job_id" in rr.json())
    j = wait_job(rr.json()["job_id"])
    check("варианты внешности получены",
          j.get("status") == "done" and len(j.get("images", [])) > 0,
          str(j.get("error"))[:90])

    # ── 6. полный цикл: фото + библиотечный голос ────────────
    print("\n6. Видео: фото + голос из библиотеки + все настройки")
    with photo.open("rb") as f:
        rr = requests.post(f"{BASE}/api/generate", data={
            "avatar_mode": "photo", "avatar_name": "Тестовый аватар",
            "voice_mode": "library", "voice_id_input": voice_id,
            "script": "Проверка полного цикла генерации видео.",
            "motion_prompt": "спокойный взгляд в камеру, лёгкие жесты",
            "engine": "avatar_iv", "expressiveness": "medium",
            "aspect_ratio": "9:16", "resolution": "1080p", "output_format": "mp4",
            "title": "Автотест",
            "voice_speed": "1.15", "voice_pitch": "8", "voice_volume": "0.9",
            "voice_locale": "ru-RU", "voice_emotion": "Friendly",
            "use_engine_settings": "true", "similarity_boost": "0.7",
            "stability": "0.4", "speaker_boost": "true",
            "background_type": "color", "background_color": "#0B0B0F",
            "caption_format": "srt", "caption_style": "default",
            "watermark_url": "https://example.com/logo.png",
            "watermark_position": "bottom_left", "watermark_scale": "0.8",
            "watermark_opacity": "0.7", "watermark_x": "20", "watermark_y": "30",
        }, files={"photos": ("p.png", f, "image/png")}, timeout=30)
    check("задача принята", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео сгенерировано", j.get("status") == "done", str(j.get("error"))[:120])

    if j.get("status") == "done":
        pl = j.get("request_payload", {})
        check("параметр: движок", pl.get("engine", {}).get("type") == "avatar_iv")
        check("параметр: выразительность", pl.get("expressiveness") == "medium")
        check("параметр: сценарий движений", bool(pl.get("motion_prompt")))
        check("параметр: соотношение сторон", pl.get("aspect_ratio") == "9:16")
        check("параметр: разрешение", pl.get("resolution") == "1080p")
        vs = pl.get("voice_settings", {})
        check("параметр: скорость речи", abs(vs.get("speed", 0) - 1.15) < 0.01)
        check("параметр: высота голоса", vs.get("pitch") == 8)
        check("параметр: громкость", abs(vs.get("volume", 0) - 0.9) < 0.01)
        check("параметр: язык/акцент", vs.get("locale") == "ru-RU")
        es = vs.get("engine_settings", {})
        check("параметр: эмоция", es.get("style") == "Friendly")
        check("параметр: схожесть голоса", abs(es.get("similarity_boost", 0) - 0.7) < 0.01)
        check("параметр: стабильность", abs(es.get("stability", 0) - 0.4) < 0.01)
        check("параметр: цвет фона", pl.get("background", {}).get("value") == "#0B0B0F")
        check("параметр: субтитры", pl.get("caption", {}).get("file_format") == "srt")
        wm = pl.get("watermark", {})
        check("параметр: водяной знак", wm.get("placement", {}).get("position") == "bottom_left")
        check("параметр: отступы знака", wm.get("placement", {}).get("offset_x") == 20)

        # скачивание
        dr = requests.get(BASE + j["download"], timeout=60)
        check("файл видео скачивается", dr.status_code == 200 and len(dr.content) > 1000,
              f"{dr.status_code}, {len(dr.content)} байт")
        check("это настоящий MP4", b"ftyp" in dr.content[:64])
        check("указан размер файла", (j.get("size_mb") or 0) > 0)
        if j.get("subtitles"):
            sr = requests.get(BASE + j["subtitles"], timeout=30)
            check("файл субтитров скачивается", sr.status_code == 200 and len(sr.content) > 5)

    # ── 7. клонирование голоса ───────────────────────────────
    print("\n7. Видео: клонирование голоса")
    with photo.open("rb") as f, sample.open("rb") as s2:
        rr = requests.post(f"{BASE}/api/generate", data={
            "avatar_mode": "photo", "voice_mode": "clone",
            "voice_name": "Мой тестовый голос",
            "script": "Проверка клонирования голоса.",
            "aspect_ratio": "16:9", "resolution": "720p",
        }, files={"photos": ("p.png", f, "image/png"),
                  "voice_sample": ("s.wav", s2, "audio/wav")}, timeout=30)
    check("задача принята", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео с клоном готово", j.get("status") == "done", str(j.get("error"))[:120])
    cloned = j.get("cloned_voice_id")
    check("ID клонированного голоса возвращён", bool(cloned))

    if cloned:
        rr = requests.post(f"{BASE}/api/save-voice",
                           json={"voice_id": cloned, "name": "Мой голос"}, timeout=15)
        check("голос сохраняется для повторного использования",
              rr.status_code == 200 and len(rr.json().get("saved_voices", [])) > 0)

    # ── 8. своя озвучка ──────────────────────────────────────
    print("\n8. Видео: своя озвучка (липсинк)")
    with photo.open("rb") as f, audio.open("rb") as a2:
        rr = requests.post(f"{BASE}/api/generate", data={
            "avatar_mode": "photo", "voice_mode": "audio",
            "aspect_ratio": "1:1", "resolution": "720p", "output_format": "webm",
        }, files={"photos": ("p.png", f, "image/png"),
                  "audio": ("a.wav", a2, "audio/wav")}, timeout=30)
    check("задача принята без текста", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео по своей озвучке готово", j.get("status") == "done", str(j.get("error"))[:120])
    if j.get("status") == "done":
        pl = j.get("request_payload", {})
        check("использован загруженный аудиофайл", bool(pl.get("audio_asset_id")))
        check("текст не отправлен", "script" not in pl)
        check("формат webm применён", pl.get("output_format") == "webm")

    # ── 9. готовый аватар + удаление фона ────────────────────
    print("\n9. Видео: готовый аватар + удаление фона")
    rr = requests.post(f"{BASE}/api/generate", data={
        "avatar_mode": "existing", "avatar_id": avatar_id,
        "voice_mode": "library", "voice_id_input": voice_id,
        "script": "Проверка готового аватара.",
        "engine": "avatar_v", "background_type": "remove",
        "aspect_ratio": "4:5", "resolution": "1080p",
    }, timeout=30)
    check("задача принята", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео с готовым аватаром готово", j.get("status") == "done",
          str(j.get("error"))[:120])
    if j.get("status") == "done":
        pl = j.get("request_payload", {})
        check("удаление фона применено", pl.get("remove_background") is True)
        check("движок Avatar V применён", pl.get("engine", {}).get("type") == "avatar_v")
        check("выразительность не шлётся для Avatar V", "expressiveness" not in pl)

    # ── 10. аватар по описанию ───────────────────────────────
    print("\n10. Видео: аватар по текстовому описанию")
    rr = requests.post(f"{BASE}/api/generate", data={
        "avatar_mode": "prompt",
        "appearance_prompt": "мужчина 40 лет, тёмный пиджак, студийный свет",
        "avatar_name": "Персонаж", "voice_mode": "library",
        "voice_id_input": voice_id, "script": "Проверка аватара по описанию.",
    }, timeout=30)
    check("задача принята", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео с созданным персонажем готово", j.get("status") == "done",
          str(j.get("error"))[:120])

    # ── 10б. агент: разбор свободного описания ───────────────
    print("\n10б. Агент: разбор свободного описания")
    rr = requests.post(f"{BASE}/api/analyse", json={"text": "к"}, timeout=20)
    check("ловит слишком короткое описание", rr.status_code == 400)

    brief = ("Хочу вертикальный ролик для Reels секунд на 20. Настроение спокойное, "
             "доверительное, тон эксперта. Нужны субтитры прямо в кадре, тёмный фон. "
             "Текст: «Ты замечал, что в твоём Роду всё повторяется по кругу?»")
    d = requests.post(f"{BASE}/api/analyse", json={"text": brief}, timeout=20).json()
    pa = d.get("params", {})
    check("описание разобрано", bool(pa))
    check("определил вертикальный формат", pa.get("aspect_ratio") == "9:16")
    check("определил субтитры в кадре", pa.get("caption_style") == "default")
    check("определил тёмный фон", pa.get("background_color") == "#0B0B0F")
    check("определил спокойную подачу", pa.get("expressiveness") == "low")
    check("замедлил речь под спокойный тон", pa.get("voice_speed", 1) < 1.0)
    check("извлёк текст из кавычек", "повторяется по кругу" in (pa.get("script") or ""))
    check("собрал поведение в кадре", bool(pa.get("motion_prompt")))
    check("подсказал объём текста под 20 секунд",
          any("20 сек" in q or "секунд" in q for q in d.get("questions", [])))
    check("НЕ подбирает голос", "voice_id_input" not in pa and "voice_mode" not in pa)
    check("НЕ подбирает фото", "photos" not in pa and "avatar_mode" not in pa)
    cards = d.get("cards", [])
    check("карточка согласования сформирована", len(cards) > 8)
    check("у каждого параметра есть русская подпись",
          all(c.get("label") and any(ord(ch) > 1000 for ch in c["label"]) for c in cards))
    check("у решений есть объяснение", sum(1 for c in cards if c.get("why")) > 8)

    d2 = requests.post(f"{BASE}/api/analyse", json={
        "text": "横 ролик для YouTube в 4K, энергично и ярко, с жестами, "
                "прозрачный фон для монтажа, на английском"}, timeout=20).json()
    p2 = d2.get("params", {})
    check("распознал YouTube → 16:9", p2.get("aspect_ratio") == "16:9")
    check("распознал 4K", p2.get("resolution") == "4k")
    check("распознал прозрачный фон → webm", p2.get("output_format") == "webm")
    check("прозрачность включила удаление фона", p2.get("background_type") == "remove")
    check("распознал энергичную подачу", p2.get("expressiveness") == "high")
    check("ускорил речь", p2.get("voice_speed", 1) > 1.0)
    check("распознал английский язык", p2.get("voice_locale") == "en-US")

    # применяем подобранное к реальной генерации
    print("\n10в. Генерация по утверждённым параметрам агента")
    gen = {"avatar_mode": "existing", "avatar_id": avatar_id,
           "voice_mode": "library", "voice_id_input": voice_id}
    for k in ("aspect_ratio", "resolution", "output_format", "engine",
              "expressiveness", "motion_prompt", "background_type",
              "background_color", "caption_format", "caption_style",
              "voice_speed", "voice_pitch", "voice_emotion", "voice_locale",
              "script", "title"):
        if pa.get(k) not in (None, ""):
            gen[k] = str(pa[k])
    rr = requests.post(f"{BASE}/api/generate", data=gen, timeout=30)
    check("задача по параметрам агента принята", rr.status_code == 200, rr.text[:120])
    j = wait_job(rr.json()["job_id"], 120)
    check("видео по описанию словами готово", j.get("status") == "done",
          str(j.get("error"))[:120])
    if j.get("status") == "done":
        pl = j.get("request_payload", {})
        check("формат агента применён", pl.get("aspect_ratio") == "9:16")
        check("субтитры агента применены",
              pl.get("caption", {}).get("style") == "default")
        check("фон агента применён",
              pl.get("background", {}).get("value") == "#0B0B0F")

    # ── 10г. устойчивость сохранения файла ───────────────────
    print("\n10г. Устойчивость сохранения (баг с отсутствующей папкой)")
    from app.server import OUT as OUTDIR
    import shutil as _sh
    if OUTDIR.is_dir():
        _sh.rmtree(OUTDIR)          # имитируем удалённую папку videos
    check("папка videos удалена для проверки", not OUTDIR.is_dir())
    h0 = requests.get(f"{BASE}/api/history", timeout=20)
    check("архив не падает без папки", h0.status_code == 200)
    rr = requests.post(f"{BASE}/api/generate", data={
        "avatar_mode": "existing", "avatar_id": avatar_id,
        "voice_mode": "library", "voice_id_input": voice_id,
        "script": "Проверка сохранения при удалённой папке."}, timeout=30)
    j = wait_job(rr.json()["job_id"], 120)
    check("видео сохраняется даже без папки", j.get("status") == "done",
          str(j.get("error"))[:140])
    if j.get("status") == "done":
        dr = requests.get(BASE + j["download"], timeout=60)
        check("файл доступен по ссылке", dr.status_code == 200 and len(dr.content) > 1000)

    # ── 11. история ──────────────────────────────────────────
    print("\n11. Архив готовых видео")
    h = requests.get(f"{BASE}/api/history", timeout=20).json()
    # папка videos удалялась в п.10г, поэтому считаем видео, снятые после этого
    check("список готовых видео не пуст", len(h.get("items", [])) >= 1,
          str(h)[:120])

    # ── 12. поведение без ключа ──────────────────────────────
    print("\n12. Поведение без ключа")
    requests.post(f"{BASE}/api/settings", json={"api_key": ""}, timeout=15)
    rr = requests.post(f"{BASE}/api/generate",
                       data={"avatar_mode": "existing", "avatar_id": "x",
                             "voice_mode": "library", "script": "п",
                             "voice_id_input": "v"}, timeout=20)
    check("без ключа выдаётся понятная ошибка",
          rr.status_code == 400 and "ключ" in rr.json().get("error", "").lower())
    requests.post(f"{BASE}/api/settings", json={
        "api_key": "test_key", "base_url": "http://127.0.0.1:8765"}, timeout=15)

    # ── итог ─────────────────────────────────────────────────
    total = len(PASS) + len(FAIL)
    print("\n" + "═" * 54)
    print(f"  ПРОЙДЕНО: {len(PASS)} из {total}")
    if FAIL:
        print(f"  ПРОВАЛЕНО: {len(FAIL)}")
        for f in FAIL:
            print(f"    ✗ {f}")
    else:
        print("  Все проверки пройдены.")
    print("═" * 54 + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
