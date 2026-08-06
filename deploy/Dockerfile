# ─────────────────────────────────────────────────────────────
#  LTX-2 photo→video agent — облачный GPU-контейнер
#  Образ: NVIDIA CUDA 12.x + PyTorch (GPU)
# ─────────────────────────────────────────────────────────────

# GPU-база с CUDA 12.1 и Python 3.11
FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_HOME=/root/.cache/torch \
    HF_HOME=/root/.cache/huggingface

# ── Базовые системные пакеты ────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        python3-pip git curl ffmpeg \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python 3.11 как python3 ──────────────────────────────────
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# ── Рабочая директория ───────────────────────────────────────
WORKDIR /app

# ── Сначала только requirements (для кеша слоёв) ─────────────
COPY requirements.txt requirements-web.txt* ./ 2>/dev/null || true
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt && \
    python3 -m pip install \
        torch torchaudio --index-url https://download.pytorch.org/whl/cu121 \
        huggingface_hub omegaconf

# ── Код проекта ──────────────────────────────────────────────
COPY . .

# ── Готовим точку входа ───────────────────────────────────────
RUN chmod +x run_webui.py
EXPOSE 8001

ENV HOST=0.0.0.0 \
    PORT=8001

CMD ["python", "run_webui.py"]
