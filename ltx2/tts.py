"""
Open-source TTS for the LTX-2 photo→video agent.

Primary engine: Silero TTS (ru/en, CPU-friendly, ~40 MB) — used to turn the
script text into a voiceover .wav. Silero is a clean, fully open model.

Optional voice cloning: Coqui XTTS-v2 — clones your *actual voice* from a short
reference audio sample (open weights). Heavier; only used when a reference
audio file is provided.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import warnings


def _warn(msg: str) -> None:
    warnings.warn(msg, stacklevel=2)


def install_torch_if_missing() -> None:
    """Ensure torch + torchaudio are importable (CPU wheel)."""
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        return
    except Exception:  # noqa: BLE001
        pass
    print("torch/torchaudio не найдены. Устанавливаю CPU-версию (~200 МБ)…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"])


# ═══════════════════════════════════════════════════════════════
# Silero TTS (текст → речь)
# ═══════════════════════════════════════════════════════════════

_SILERO_LOADED = None


def _silero(language: str = "ru", speaker: str = "aidar", sample_rate: int = 48000):
    """Lazy-load a Silero TTS model. Uses a local model file if
    SILERO_MODEL_PATH is set (pre-downloaded v4_ru.pt), else torch.hub."""
    global _SILERO_LOADED  # noqa: PLW0603
    install_torch_if_missing()
    import torch

    if _SILERO_LOADED is not None:
        return _SILERO_LOADED

    local_model = os.getenv("SILERO_MODEL_PATH", "")
    if local_model and os.path.exists(local_model):
        # Silero v4 is a JIT (.pt) model loaded with torch.jit.load.
        model = torch.jit.load(local_model, map_location="cpu")
        model.eval()
        _SILERO_LOADED = (model, speaker, sample_rate)
        return _SILERO_LOADED

    # Avoid torch.hub prompt about 'allow_local_dir'.
    os.environ.setdefault("TORCH_HOME", os.path.join(tempfile.gettempdir(), "torch_cache"))

    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language=language,
        speaker=f"v4_{language}",
        trust_repo=True,
        verbose=False,
    )
    _SILERO_LOADED = (model, speaker, sample_rate)
    return _SILERO_LOADED


def silero_tts(
    text: str,
    language: str = "ru",
    speaker: str = "aidar",
    sample_rate: int = 48000,
    output_path: str = "voiceover.wav",
) -> str:
    """
    Generate speech from `text` using Silero TTS and write a .wav.

    Speakers (ru): aidar / baya / kseniya / xenia / eugene / random
    Speakers (en): en_0 .. en_117
    """
    model, spk, sr = _silero(language, speaker, sample_rate)

    # torch.jit.load gives a raw JIT model; torch.hub gives a wrapper.
    if hasattr(model, "apply_tts"):
        try:
            audio = model.apply_tts(text=text, speaker=speaker, sample_rate=sample_rate)
        except TypeError:
            audio = model.apply_tts(text=text, speaker=speaker)
    else:
        audio = model(text, speaker, sample_rate)
        if audio.dim() == 1:
            audio = audio.unsqueeze(0)

    import torchaudio
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)
    torchaudio.save(output_path, audio, sample_rate)
    return output_path


# ═══════════════════════════════════════════════════════════════
# Coqui XTTS-v2 (клонирование голоса по образцу) — опционально
# ═══════════════════════════════════════════════════════════════

def xtts_clone(
    text: str,
    reference_audio: str,
    reference_text: str = "",
    language: str = "ru",
    output_path: str = "voice_clone.wav",
) -> str:
    """
    Clone a voice from `reference_audio` and speak `text` (Coqui XTTS-v2).
    Heavy; runs best on GPU. Falls back to Silero if Coqui is unavailable.
    """
    try:
        from TTS.api import TTS  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        _warn("Coqui TTS не установлен (pip install TTS). Использую Silero TTS вместо клонирования голоса.")
        return silero_tts(text, language=language, output_path=output_path)

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda" if _has_cuda() else "cpu")
    tts.tts_to_file(
        text=text,
        speaker_wav=reference_audio,
        language=language,
        file_path=output_path,
        split_sentences=True,
    )
    return output_path


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


# ═══════════════════════════════════════════════════════════════
# High-level: pick engine
# ═══════════════════════════════════════════════════════════════

def generate_voiceover(
    text: str,
    output_path: str = "voiceover.wav",
    voice_reference: str | None = None,
    language: str = "ru",
    speaker: str = "aidar",
    clone_voice: bool = False,
) -> str:
    """
    Generate the voiceover audio for the video.

    * voice_reference + clone_voice=True -> clone that voice (XTTS)
    * otherwise                          -> Silero TTS with a preset speaker
    """
    if voice_reference and clone_voice:
        return xtts_clone(
            text,
            reference_audio=voice_reference,
            language=language,
            output_path=output_path,
        )
    return silero_tts(text, language=language, speaker=speaker, output_path=output_path)
