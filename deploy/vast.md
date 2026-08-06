# Развёртывание на Vast.ai

Vast.ai — маркетплейс дешёвых GPU-аренд. Подойдёт для подежной аренды
с предустановленным Docker.

## 1. Найти GPU

1. Откройте [vast.ai](https://vast.ai) → **Create**.
2. Выберите фильтры:
   - **CUDA** версии 12.x
   - **VRAM** ≥ 40 ГБ (для LTX-2.3 — 22B): A100, H100, L40S, A6000.
   - ОС: любая с Docker.
3. Выберите машину по цене/доступности.

## 2. Развернуть контейнер

Vast.ai поддерживает Docker-образы. Укажите:

- **Docker image**: `nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04` (или наш собранный).
- **Docker command**:
  ```bash
  bash -c "
    apt-get update && apt-get install -y python3.11 python3-pip git ffmpeg &&
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 &&
    git clone https://github.com/playalexey-sketch/heygen-integration.git /app &&
    cd /app && pip install -r requirements.txt &&
    bash deploy/download_models.sh &&
    python run_webui.py
  "
  ```
- **On-start script** (для скачивания весов) — по желанию.

## 3. Порт и доступ

- Vast.ai откроет **port 8001** публично (настройте в разделе портов: `8001`).
- Получите публичный URL вида `http://<ip>:8001`.

## 4. Проверка

```bash
curl -X POST http://<ip>:8001/api/generate \
  -F "photo=@me.jpg" -F "text=Я родилась 05 февраля 1987 года и я красотка"
curl http://<ip>:8001/api/jobs/<job_id>
```

## Примечания

- Проект доступен на GitHub: `https://github.com/playalexey-sketch/heygen-integration`.
- Убедитесь, что `HF_TOKEN` задан для скачивания gated-моделей LTX-2.3.
- Завершайте аренду после работы — Vast платится поминутно.
