#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Видео цифрового аватара: ТВОЁ ФОТО + ТВОЙ ГОЛОС.

Два режима:

  1) КЛОНИРОВАНИЕ ГОЛОСА (аватар говорит текст твоим голосом)
     python make_avatar_video.py --photo my.jpg --voice-sample voice.mp3 \
            --script "Текст, который скажет аватар" --out video.mp4

  2) ГОТОВАЯ ОЗВУЧКА (аватар липсинкает твою аудиодорожку)
     python make_avatar_video.py --photo my.jpg --audio speech.mp3 --out video.mp4

Перед запуском нужен HeyGen API-ключ в файле .env:
     HEYGEN_API_KEY=hg_xxxxxxxxxxxxx

Требования к материалам:
  Фото  — портрет анфас, лицо крупно, ровный свет, без очков/головных уборов,
          без обрезанного подбородка. JPG/PNG, желательно от 1000 px по ширине.
  Голос — чистая запись 30–120 секунд, без музыки и шума, один говорящий. MP3/WAV.
"""

import argparse
import json
import os
import sys

# .env подхватываем до импорта конфигурации
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _check_key() -> bool:
    if not os.getenv("HEYGEN_API_KEY"):
        print("❌ Не найден HEYGEN_API_KEY.")
        print("   Создай файл .env рядом со скриптом и впиши строку:")
        print("   HEYGEN_API_KEY=твой_ключ")
        print("   Ключ берётся тут: https://app.heygen.com/settings/api")
        return False
    return True


def _check_file(path: str, label: str) -> bool:
    if not path:
        return True
    if not os.path.isfile(path):
        print(f"❌ Не найден файл {label}: {path}")
        return False
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"   {label}: {os.path.basename(path)} ({size_mb:.1f} МБ)")
    return True


def _download(url: str, out_path: str) -> str:
    import requests
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Видео цифрового аватара из фото + твоего голоса.")
    p.add_argument("--photo", required=True, help="Портретное фото (jpg/png)")
    p.add_argument("--voice-sample", help="Запись твоего голоса для клонирования (30–120 с)")
    p.add_argument("--audio", help="Готовая озвучка — аватар просто липсинкает её")
    p.add_argument("--script", help="Текст, который произнесёт аватар (для --voice-sample)")
    p.add_argument("--voice-id", help="ID готового голоса из библиотеки HeyGen")
    p.add_argument("--voice-name", default="Мой голос", help="Название клонированного голоса")
    p.add_argument("--avatar-name", default="Мой аватар", help="Название фото-аватара")
    p.add_argument("--title", default="Аватар-видео", help="Название ролика в HeyGen")
    p.add_argument("--aspect-ratio", default="9:16",
                   choices=["16:9", "9:16", "1:1", "auto"],
                   help="Соотношение сторон (9:16 — Reels/Stories)")
    p.add_argument("--resolution", default="1080p", choices=["720p", "1080p"])
    p.add_argument("--background", help="Цвет фона hex (#0B0B0F) или URL картинки")
    p.add_argument("--out", default="avatar_video.mp4", help="Куда сохранить видео")
    p.add_argument("--timeout", type=int, default=900, help="Макс. ожидание, сек")
    args = p.parse_args(argv)

    if not _check_key():
        return 1
    if not args.audio and not args.script:
        print("❌ Нужен либо --audio (готовая озвучка), либо --script (текст).")
        return 1
    if args.script and not args.voice_sample and not args.voice_id:
        print("❌ Для --script укажи --voice-sample (клонировать твой голос) "
              "или --voice-id (голос из библиотеки).")
        return 1

    print("▶ Проверяю материалы...")
    for path, label in ((args.photo, "фото"),
                        (args.voice_sample, "образец голоса"),
                        (args.audio, "аудио")):
        if not _check_file(path, label):
            return 1

    from photo_video_agent import build_video_from_photo

    mode = ("липсинк готовой озвучки" if args.audio
            else "клонирование голоса" if args.voice_sample
            else "голос из библиотеки")
    print(f"▶ Режим: {mode}")
    print("▶ Отправляю в HeyGen. Это занимает от 2 до 10 минут — не закрывай окно...")

    try:
        result = build_video_from_photo(
            photo_path=args.photo,
            audio_path=args.audio,
            script=args.script,
            voice_id=args.voice_id,
            clone_voice_from=args.voice_sample,
            voice_name=args.voice_name,
            avatar_name=args.avatar_name,
            title=args.title,
            duration_seconds=0,          # не подгонять текст под длительность
            resolution=args.resolution,
            aspect_ratio=args.aspect_ratio,
            background=args.background,
            wait=True,
            timeout=args.timeout,
        )
    except Exception as e:
        print(f"❌ Сбой запроса: {e}")
        return 1

    if result.get("error"):
        print(f"❌ Ошибка HeyGen: {result['error']}")
        return 1

    url = result.get("video_url")
    if url:
        print("✅ Видео готово, скачиваю...")
        _download(url, args.out)
        print(f"   Сохранено: {os.path.abspath(args.out)}")
        print(f"   Ссылка (временная): {url}")
        if result.get("voice_used"):
            print(f"   ID твоего клонированного голоса: {result['voice_used']}")
            print("   Сохрани его — в следующий раз можно передать --voice-id "
                  "и не клонировать заново.")
    else:
        print("⏳ Видео ещё рендерится. Ответ сервиса:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
