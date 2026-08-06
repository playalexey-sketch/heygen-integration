#!/usr/bin/env python3
"""
LTX-2 photo→video agent (CLI).

Фото + текст (или аудио) → видео, где человек на фото говорит вашим голосом.
Использует открытые модели: Silero TTS (озвучка) + LTX-2 A2Vid (аудио→видео с
image-conditioning по фото).

Требует GPU (LTX-2.3 — 22B модель). См. setup_ltx2.sh.

Примеры:
    python ltx2_agent.py --photo me.jpg --text "Я родилась 05 февраля 1987 года и я красотка"
    python ltx2_agent.py --photo me.jpg --text "..." --duration 15 --aspect portrait
    python ltx2_agent.py --photo me.jpg --audio voice.wav --dry-run
    python ltx2_agent.py --check-env
"""

import argparse
import json
import os

from ltx2.agent import build_talking_video, check_prerequisites


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ltx2_agent",
        description="Фото + голос → видео с цифровым аватаром (LTX-2 + Silero TTS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--photo", help="Путь к фото (портрет человека)")
    parser.add_argument("--text", help="Текст, который скажет человек на фото")
    parser.add_argument("--audio", help="Готовая аудиодорожка (вместо text)")
    parser.add_argument("--voice-reference", help="Аудио-образец вашего голоса (для клонирования XTTS)")
    parser.add_argument("--clone-voice", action="store_true", help="Клонировать голос из --voice-reference")
    parser.add_argument("--language", default="ru", help="Язык озвучки (ru/en)")
    parser.add_argument("--tts-speaker", default="aidar", help="Silero голос (aidar/baya/ksenia/xenia/eugene)")
    parser.add_argument("--duration", type=int, default=15, help="Длительность видео, сек (по умолчанию 15)")
    parser.add_argument("--fps", type=float, default=24, help="Кадров в секунду")
    parser.add_argument("--aspect", default="portrait",
                        choices=["portrait", "landscape", "square", "auto"],
                        help="Соотношение сторон")
    parser.add_argument("--resolution", default="720p",
                        choices=["720p", "1080p", "4K"],
                        help="Разрешение (по умолчанию 720p)")
    parser.add_argument("--width", type=int, default=None, help="Явная ширина (делится на 64)")
    parser.add_argument("--height", type=int, default=None, help="Явная высота (делится на 64)")
    parser.add_argument("--prompt", default=None, help="Промпт для LTX-2 (иначе строится автоматически)")
    parser.add_argument("--image-strength", type=float, default=0.8, help="Сила привязки к фото (0-1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--enhance-prompt", action="store_true")
    parser.add_argument("--quantization", choices=["fp8-cast", "fp8-scaled-mm"], default=None,
                        help="Снизить потребление VRAM")
    parser.add_argument("--offload", choices=["none", "cpu", "disk"], default="none",
                        help="Выгрузка весов: cpu/disk для малой VRAM")
    parser.add_argument("--out", default="talking_avatar.mp4", help="Выходной файл видео")
    parser.add_argument("--workdir", default=".", help="Рабочая папка для временных файлов")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только собрать и показать команду, не запускать")
    parser.add_argument("--check-env", action="store_true", help="Проверить окружение и выйти")

    args = parser.parse_args()

    if args.check_env:
        print(json.dumps(check_prerequisites(), ensure_ascii=False, indent=2))
        return

    if not args.photo:
        parser.error("Укажите --photo (фото человека).")
    if not args.text and not args.audio:
        parser.error("Укажите --text (текст) или --audio (аудиодорожка).")

    try:
        result = build_talking_video(
            args.photo,
            args.out,
            text=args.text,
            audio_path=args.audio,
            voice_reference=args.voice_reference,
            clone_voice=args.clone_voice,
            language=args.language,
            tts_speaker=args.tts_speaker,
            duration_seconds=args.duration,
            fps=args.fps,
            aspect=args.aspect,
            resolution=args.resolution,
            width=args.width,
            height=args.height,
            prompt=args.prompt,
            image_strength=args.image_strength,
            seed=args.seed,
            enhance_prompt=args.enhance_prompt,
            quantization=args.quantization,
            offload=args.offload,
            workdir=args.workdir,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))

    if result.get("dry_run"):
        print("\n--- Команда LTX-2 (--dry-run) ---")
        print(" \\\n    ".join(result["command"]))
        print(f"\nОзвучка готова: {result['audio_path']}")
        return

    if result.get("error"):
        print(f"❌ {result['error']}")
        if result.get("audio_path"):
            print(f"   Озвучка сохранена: {result['audio_path']}")
        return

    print(f"✅ Готово! Видео: {result['output_path']}")
    print(f"   Озвучка: {result['audio_path']}")


if __name__ == "__main__":
    main()
