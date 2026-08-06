"""
Photo → Video agent (простой агент "фото + голос → видео").

Загружаете фото человека и озвучку (или текст), получаете видео ~15 секунд,
где цифровой аватар (человек на фото) говорит вашим голосом.

Как пользоваться:
    from photo_video_agent import build_video_from_photo

    result = build_video_from_photo(
        photo_path="me.jpg",      # фото (портрет)
        audio_path="voice.mp3",   # озвучка (или задайте script + voice_id)
        duration_seconds=15,
        resolution="1080p",
        aspect_ratio="16:9",
        wait=True,                # дождаться готового видео
    )
    print(result["video_url"])

Или из командной строки:
    python photo_video_agent.py --photo me.jpg --audio voice.mp3 --out video.mp4
"""

import argparse
import os

from heygen_tools import heygen_create_photo_video


# ── Настройки по умолчанию ─────────────────────────────────────
DEFAULT_DURATION = 15          # целевая длительность видео, секунд
DEFAULT_RESOLUTION = "1080p"
DEFAULT_ASPECT_RATIO = "16:9"


def build_video_from_photo(
    photo_path: str,
    audio_path: str | None = None,
    audio_url: str | None = None,
    script: str | None = None,
    voice_id: str | None = None,
    clone_voice_from: str | None = None,
    voice_name: str = "My Voice",
    avatar_name: str = "My Photo Avatar",
    title: str = "",
    duration_seconds: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    background: str | None = None,
    wait: bool = True,
    poll_interval: int = 10,
    timeout: int = 600,
) -> dict:
    """
    Собрать видео из фото + голоса.

    Голос задаётся ОДНИМ из способов:
      * audio_path / audio_url            -> аватар липсинкает загруженную аудиодорожку
      * script (+ voice_id)               -> аватар произносит текст голосом из библиотеки
      * clone_voice_from (файл) + script  -> ваш голос клонируется и озвучивает текст

    duration_seconds — целевая длительность (по умолчанию 15 c).
    Для audio_path длительность видео = длительности аудио, поэтому нарежьте
    аудио под ~15 секунд заранее.
    """
    if not audio_path and not audio_url and not script and not clone_voice_from:
        raise ValueError(
            "Укажите голос: audio_path/audio_url (аудио) или script+voice_id "
            "(текст) или clone_voice_from (клонирование голоса)."
        )

    # Если текста нет, но голос клонируется — подскажем дать текст.
    if clone_voice_from and not script:
        raise ValueError("Для клонированного голоса укажите script (что аватар должен сказать).")

    # Если длительность задана и есть только текст — поможем уложиться в ~N секунд.
    if script and not audio_path and duration_seconds:
        script = _pad_to_duration(script, duration_seconds)

    return heygen_create_photo_video(
        photo_path=photo_path,
        audio_path=audio_path,
        audio_url=audio_url,
        script=script,
        voice_id=voice_id,
        clone_voice_from=clone_voice_from,
        voice_name=voice_name,
        avatar_name=avatar_name,
        title=title or "Photo Avatar Video",
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        background=background,
        wait=wait,
        poll_interval=poll_interval,
        timeout=timeout,
    )


def _pad_to_duration(script: str, target_seconds: int) -> str:
    """
    Простая эвристика: ~2 слова в секунду речи. Добавляет продолжение,
    если текст слишком короткий, или обрезает, если слишком длинный.
    """
    target_words = max(8, int(target_seconds * 2))
    words = script.split()
    if len(words) < target_words:
        filler_sentences = [
            "Это короткий ролик, созданный автоматически из вашей фотографии.",
            "Спасибо за внимание и хорошего дня.",
            "Надеюсь, вам понравится этот ролик.",
        ]
        i = 0
        while len(words) < target_words:
            for part in filler_sentences[i % len(filler_sentences)].split():
                words.append(part)
            i += 1
    return " ".join(words[:target_words])


def _download(url: str, out_path: str) -> str:
    import requests
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Фото + голос → видео с цифровым аватаром.")
    parser.add_argument("--photo", required=True, help="Путь к фото (портрет)")
    parser.add_argument("--audio", help="Путь к аудио-озвучке (mp3/wav)")
    parser.add_argument("--script", help="Текст, который скажет аватар")
    parser.add_argument("--voice-id", help="ID голоса из библиотеки (для script)")
    parser.add_argument("--voice-name", default="My Voice", help="Имя клонированного голоса")
    parser.add_argument("--avatar-name", default="My Photo Avatar", help="Имя фото-аватара")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Целевая длительность видео, сек (по умолчанию {DEFAULT_DURATION})")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                        choices=["720p", "1080p"], help="Разрешение")
    parser.add_argument("--aspect-ratio", default=DEFAULT_ASPECT_RATIO,
                        choices=["16:9", "9:16", "1:1", "auto"], help="Соотношение сторон")
    parser.add_argument("--background", help="Цвет фона (hex) или URL изображения")
    parser.add_argument("--out", default="photo_video.mp4", help="Куда сохранить видео")
    args = parser.parse_args(argv)

    if not args.audio and not args.script:
        parser.error("Укажите --audio ИЛИ --script.")

    print(f"▶ Собираю видео из фото '{args.photo}' длительностью ~{args.duration} сек...")
    result = build_video_from_photo(
        photo_path=args.photo,
        audio_path=args.audio,
        script=args.script,
        voice_id=args.voice_id,
        voice_name=args.voice_name,
        avatar_name=args.avatar_name,
        duration_seconds=args.duration,
        resolution=args.resolution,
        aspect_ratio=args.aspect_ratio,
        background=args.background,
    )

    if result.get("error"):
        print(f"❌ Ошибка: {result['error']}")
        return
    if result.get("video_url"):
        print(f"✅ Видео готово! Скачиваю в '{args.out}'...")
        _download(result["video_url"], args.out)
        print(f"   Сохранено: {os.path.abspath(args.out)}")
    else:
        print("⏳ Видео создаётся. Результат:")
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
