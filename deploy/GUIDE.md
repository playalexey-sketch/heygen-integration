# 🚀 Развёртывание LTX-2 photo→video агента в облаке с GPU

Здесь — пошаговый план, как поднять наш веб-интерфейс на облачной GPU-машине,
чтобы генерация видео работала по ссылке (без своей видеокарты).

---

## 0. Что вам понадобится

1. **Аккаунт Hugging Face** + **Read-токен** с доступом к gated-репозиториям
   (нужен для скачивания весов LTX-2.3):
   - https://huggingface.co/settings/tokens
   - Разрешите доступ к `Lightricks/LTX-2.3` (кнопка "Agree" на странице модели).
2. **GPU-машина** (одна из платформ ниже).
3. Копия этого проекта (у вас уже есть).

---

## 1. Загрузка весов модели (главный шаг)

LTX-2.3 — модель ~22 млрд параметров. Веса занимают **десятки ГБ** и обязательны.

На GPU-машине (после клонирования проекта):

```bash
cd heygen-integration
pip install -U huggingface_hub
huggingface-cli login   # вставьте Read-токен

# Скачать веса + Gemma text-encoder
bash deploy/download_models.sh
```

Либо через переменную окружения:
```bash
export HF_TOKEN=hf_xxxx
bash deploy/download_models.sh
```

Проверка, что всё на месте:
```bash
ls models/ltx-2.3/           # 3 файла .safetensors
ls models/gemma-3-12b/       # файлы Gemma
```

---

## 2. Установка зависимостей

```bash
cd heygen-integration
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install omegaconf
```

Проверка GPU:
```bash
python -c "import torch; print(torch.cuda.get_device_name(0))"
# Должен напечатать название видеокарты, например "NVIDIA A100"
```

---

## 3. Запуск веб-интерфейса

```bash
export HOST=0.0.0.0 PORT=8001
export LTX2_OUTPUT_DIR=/app/ltx2_output
export LTX2_CHECKPOINT=...   # см. deploy/env.example

python run_webui.py
```

Откройте `http://<IP-машины>:8001`.

---

## 4. Варианты облачных GPU-платформ

| Платформа | Гайд | Особенности |
|-----------|------|-------------|
| **RunPod** | [runpod.md](runpod.md) | Serverless, лёгкий запуск Docker-образа |
| **Vast.ai** | [vast.md](vast.md) | Дёшево, подежная аренда |
| **Modal** | modal.md | На основе серверлесс-функций (код-как-конфиг) |
| **Lightning.ai** | lightning.md | Простые ноутбуки/приложения с GPU |
| **Google Cloud / AWS / Azure** | docker-compose + GPU VM | Классика: GPU-инстанс + Docker |

> Обычно проще всего **RunPod** или **Vast.ai** для одного GPU-инстанса.

---

## 5. Проверка после развёртывания

```bash
# Статус среды
curl http://<IP>:8001/api/env

# Отправить задачу
curl -X POST http://<IP>:8001/api/generate \
  -F "photo=@me.jpg" \
  -F "text=Я родилась 05 февраля 1987 года и я красотка" \
  -F "resolution=720p"

# Статус по job_id
curl http://<IP>:8001/api/jobs/<job_id>

# Готовое видео
# http://<IP>:8001/output/<job_id>
```

---

## 6. Остановка и экономия

- **RunPod**: удалите/остановите endpoint, когда не работаете.
- **Vast.ai**: завершите аренду (поминутная оплата).
- Закоммитьте код в git, чтобы пересоздавать машину при необходимости.

---

## 7. Рекомендации по GPU

- **Минимум**: 40 ГБ VRAM (A6000, A100-40G) + `--offload cpu`.
- **Комфортно**: 80 ГБ VRAM (A100-80G, H100) — все разрешения без offload.
- ОЗУ ≥ 64 ГБ, диск ≥ 100 ГБ свободно (веса).

---

_Подробности об архитектуре и решении ошибок — в [`OPERATIONS_LOG.md`](../OPERATIONS_LOG.md)._
