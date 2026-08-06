"""
LTX-2 photo→video agent.

Пайплайн: фото + текст (или готовое аудио) -> озвучка (Silero TTS / XTTS) ->
видео, где человек на фото говорит (LTX-2 A2Vid audio-to-video).

LTX-2 A2Vid (A2VidPipelineTwoStage) генерирует видео, синхронизированное с
аудиодорожкой, и принимает фото как image-conditioning (первый кадр) — то есть
получается «цифровой аватар на фото», повторяющий голос.

Запуск требует GPU с достаточной памятью (22B модель). Для облегчения памяти
используйте --offload cpu/disk и/или --quantization fp8-cast.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from ltx2 import tts as tts_mod

# ═══════════════════════════════════════════════════════════════
# Конфигурация путей к моделям LTX-2 (можно переопределить env/CLI)
# ═══════════════════════════════════════════════════════════════

DEFAULT_MODEL_DIR = "models/ltx-2.3"
DEFAULT_GEMMA_DIR = "models/gemma-3-12b"

LTX2_CHECKPOINT = os.getenv(
    "LTX2_CHECKPOINT",
    os.path.join(DEFAULT_MODEL_DIR, "ltx-2.3-22b-dev.safetensors"),
)
LTX2_SPATIAL_UPSAMPLER = os.getenv(
    "LTX2_SPATIAL_UPSAMPLER",
    os.path.join(DEFAULT_MODEL_DIR, "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),
)
LTX2_DISTILLED_LORA = os.getenv(
    "LTX2_DISTILLED_LORA",
    os.path.join(DEFAULT_MODEL_DIR, "ltx-2.3-22b-distilled-lora-384-1.1.safetensors"),
)
LTX2_GEMMA_ROOT = os.getenv("LTX2_GEMMA_ROOT", DEFAULT_GEMMA_DIR)

# Пресеты разрешений: aspect -> (width, height). Оба делятся на 64 (2-stage).
# Три уровня качества; "720p" — разрешение по умолчанию.
ASPECT_PRESETS = {
    "portrait": (768, 1280),    # 9:16 — вертикально (Reels/Shorts)
    "landscape": (1280, 768),   # 16:9-ish — горизонтально
    "square": (768, 768),       # 1:1 — квадрат
    "auto": (768, 1280),        # по умолчанию портрет
}

# Уровни качества (разрешения), валидные для LTX-2 (кратны 64).
# Ключ -> dict(aspect -> (width, height))
RESOLUTION_PRESETS = {
    "720p": {   # по умолчанию
        "portrait": (576, 1024),     # 9:16  (576/64=9, 1024/64=16)
        "landscape": (1024, 576),    # 16:9
        "square": (704, 704),        # 1:1   (704/64=11)
        "auto": (576, 1024),
    },
    "1080p": {
        "portrait": (768, 1280),
        "landscape": (1280, 768),
        "square": (768, 768),
        "auto": (768, 1280),
    },
    "4K": {
        "portrait": (1152, 2048),    # 9:16
        "landscape": (2048, 1152),   # 16:9
        "square": (1280, 1280),
        "auto": (1152, 2048),
    },
}


def get_dimensions(aspect: str, resolution: str, width=None, height=None):
    """
    Вернуть (width, height) для LTX-2 с учётом выбранных аспекта и разрешения.
    Явные width/height имеют приоритет, иначе берём из пресета.
    """
    if width and height:
        return int(width), int(height)
    res = RESOLUTION_PRESETS.get(resolution, RESOLUTION_PRESETS["720p"])
    return res.get(aspect, res["auto"])

DEFAULT_NEGATIVE_PROMPT = (
    "blurry, out of focus, overexposed, underexposed, low contrast, distorted proportions, "
    "deformed facial features, asymmetrical face, extra limbs, disfigured hands, cartoonish "
    "rendering, 3D CGI look, uncanny valley, mismatched lip sync, silent or muted audio, "
    "distorted voice, robotic voice, off-sync audio, jittery movement, AI artifacts"
)


def _prereq_errors() -> str:
    """Вернуть понятное описание невыполненных требований, либо пустую строку."""
    missing = []

    if not os.path.exists(LTX2_CHECKPOINT):
        missing.append(f"нет весов LTX-2: {LTX2_CHECKPOINT}")
    if not os.path.exists(LTX2_SPATIAL_UPSAMPLER):
        missing.append(f"нет апскейлера: {LTX2_SPATIAL_UPSAMPLER}")
    if not os.path.exists(LTX2_DISTILLED_LORA):
        missing.append(f"нет distilled LoRA: {LTX2_DISTILLED_LORA}")
    if not os.path.isdir(LTX2_GEMMA_ROOT):
        missing.append(f"нет Gemma text-encoder: {LTX2_GEMMA_ROOT}")

    try:
        import torch  # noqa: PLC0415
        if not torch.cuda.is_available():
            missing.append("нет GPU (LTX-2 требует видеокарту NVIDIA с CUDA)")
    except Exception:  # noqa: BLE001
        missing.append("не установлен torch")

    try:
        import ltx_pipelines  # noqa: PLC0415, F401
    except Exception:  # noqa: BLE001
        missing.append("не установлен пакет ltx_pipelines (нужен setup_ltx2.sh)")

    if not missing:
        return ""
    return "Не выполнены требования LTX-2:\n  • " + "\n  • ".join(missing)


def _snap_frames(num_frames: int) -> int:
    """LTX-2 требует num_frames = 8*k + 1."""
    k = max(0, round((num_frames - 1) / 8))
    return 8 * k + 1


def build_ltx2_command(
    photo_path: str,
    audio_path: str,
    output_path: str,
    prompt: str,
    *,
    duration_seconds: int = 15,
    fps: float = 24,
    aspect: str = "portrait",
    resolution: str = "720p",
    width: int | None = None,
    height: int | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    image_strength: float = 0.8,
    seed: int = 42,
    enhance_prompt: bool = False,
    quantization: str | None = None,
    offload: str = "none",
    python: str | None = None,
    ltx2_root: str | None = None,
) -> list[str]:
    """
    Build the exact `python -m ltx_pipelines.a2vid_two_stage ...` command.

    duration_seconds/fps -> num_frames snapped to 8*k+1.
    aspect + resolution presets set width/height unless explicit values given.
    """
    width, height = get_dimensions(aspect, resolution, width, height)

    num_frames = _snap_frames(int(duration_seconds * fps))

    cmd = [
        python or sys.executable,
        "-m",
        "ltx_pipelines.a2vid_two_stage",
        "--checkpoint-path", os.path.abspath(LTX2_CHECKPOINT),
        "--distilled-lora", os.path.abspath(LTX2_DISTILLED_LORA),
        "--spatial-upsampler-path", os.path.abspath(LTX2_SPATIAL_UPSAMPLER),
        "--gemma-root", os.path.abspath(LTX2_GEMMA_ROOT),
        "--prompt", prompt,
        "--negative-prompt", negative_prompt,
        "--image", os.path.abspath(photo_path), "0", str(image_strength),
        "--audio-path", os.path.abspath(audio_path),
        "--num-frames", str(num_frames),
        "--frame-rate", str(fps),
        "--height", str(height),
        "--width", str(width),
        "--seed", str(seed),
        "--output-path", os.path.abspath(output_path),
    ]
    if enhance_prompt:
        cmd.append("--enhance-prompt")
    if quantization:
        cmd += ["--quantization", quantization]
    if offload and offload != "none":
        cmd += ["--offload", offload]
    return cmd


def build_talking_video(
    photo_path: str,
    output_path: str,
    *,
    text: str | None = None,
    audio_path: str | None = None,
    voice_reference: str | None = None,
    clone_voice: bool = False,
    language: str = "ru",
    tts_speaker: str = "aidar",
    duration_seconds: int = 15,
    fps: float = 24,
    aspect: str = "portrait",
    resolution: str = "720p",
    width: int | None = None,
    height: int | None = None,
    prompt: str | None = None,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    image_strength: float = 0.8,
    seed: int = 42,
    enhance_prompt: bool = False,
    quantization: str | None = None,
    offload: str = "none",
    workdir: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Собрать видео «человек на фото говорит» на базе LTX-2.

    Голос задаётся ОДНИМ из способов:
      * text (без аудио)            -> озвучка через Silero TTS
      * text + voice_reference + clone_voice -> клонирование голоса (XTTS)
      * audio_path                  -> готовая аудиодорожка

    Возвращает dict с аудио-путём, собранной командой и результатом запуска.
    """
    if not os.path.exists(photo_path):
        raise FileNotFoundError(f"Фото не найдено: {photo_path}")
    if not (text or audio_path):
        raise ValueError("Укажите text (скрипт) или audio_path (аудио).")

    workdir = workdir or "."
    os.makedirs(workdir, exist_ok=True)

    # ── 1. Озвучка ─────────────────────────────────────────────
    if audio_path:
        voice_wav = audio_path
        if not os.path.exists(voice_wav):
            raise FileNotFoundError(f"Аудио не найдено: {voice_wav}")
    else:
        voice_wav = os.path.join(workdir, "voiceover.wav")
        print(f"🔊 Генерирую озвучку (Silero TTS): {text!r}")
        tts_mod.generate_voiceover(
            text,
            output_path=voice_wav,
            voice_reference=voice_reference,
            language=language,
            speaker=tts_speaker,
            clone_voice=clone_voice,
        )

    # ── 2. Промпт ──────────────────────────────────────────────
    if not prompt:
        prompt = (
            "A medium close-up of a single person, facing the camera and talking "
            "directly to the viewer. The person's face and identity match the "
            "reference image exactly. Natural head movements, subtle blinking and "
            "gestures, realistic lip sync matching the speech. Stable, calm, "
            "studio-like lighting, shallow depth of field, background softly blurred. "
            "The camera stays static."
        )
        if enhance_prompt:
            prompt = prompt  # the pipeline will enhance it automatically

    # ── 3. Команда LTX-2 A2Vid ─────────────────────────────────
    cmd = build_ltx2_command(
        photo_path, voice_wav, output_path, prompt,
        duration_seconds=duration_seconds, fps=fps, aspect=aspect,
        resolution=resolution, width=width, height=height,
        negative_prompt=negative_prompt,
        image_strength=image_strength, seed=seed, enhance_prompt=enhance_prompt,
        quantization=quantization, offload=offload,
    )

    print("🎬 Запускаю LTX-2 A2Vid (audio-to-video)…")
    print("   " + " \\\n   ".join(cmd))

    if dry_run:
        return {"dry_run": True, "audio_path": voice_wav, "command": cmd}

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")

    # Проверяем предпосылки ДО запуска, чтобы выдать понятную ошибку.
    prereq = _prereq_errors()
    if prereq:
        return {
            "error": prereq,
            "detail": "LTX-2 не запускался (не выполнены требования). "
                      "Настройте на вашем ПК с GPU: ./setup_ltx2.sh, затем запустите локально.",
            "audio_path": voice_wav,
            "command": cmd,
        }

    result = subprocess.run(cmd, env=env, cwd=os.getcwd(), capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        detail = tail[-8:] if tail else []
        return {
            "error": f"LTX-2 завершился с кодом {result.returncode}",
            "detail": "\n".join(detail) or result.stdout or "без подробностей",
            "audio_path": voice_wav,
            "command": cmd,
        }

    if not os.path.exists(output_path):
        return {"error": "Видео не создано (нет выходного файла)", "audio_path": voice_wav, "command": cmd}

    return {
        "status": "completed",
        "output_path": os.path.abspath(output_path),
        "audio_path": os.path.abspath(voice_wav),
        "photo_path": os.path.abspath(photo_path),
        "duration_seconds": duration_seconds,
        "aspect": aspect,
    }


def check_prerequisites() -> dict:
    """Вернуть состояние окружения для диагностики."""
    checks = {
        "ltx2_pipelines": shutil.which("uv") is not None or _has_ltx_pipelines(),
        "checkpoint": os.path.exists(LTX2_CHECKPOINT),
        "spatial_upsampler": os.path.exists(LTX2_SPATIAL_UPSAMPLER),
        "distilled_lora": os.path.exists(LTX2_DISTILLED_LORA),
        "gemma_root": os.path.isdir(LTX2_GEMMA_ROOT),
        "torch": tts_mod._has_cuda(),  # noqa: SLF001
    }
    try:
        import torch  # noqa: PLC0415
        checks["torch"] = True
        checks["cuda"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            checks["gpu"] = torch.cuda.get_device_name(0)
    except Exception:  # noqa: BLE001
        checks["torch"] = False
        checks["cuda"] = False
    return checks


def _has_ltx_pipelines() -> bool:
    try:
        import ltx_pipelines  # noqa: PLC0415, F401
        return True
    except Exception:  # noqa: BLE001
        return False
