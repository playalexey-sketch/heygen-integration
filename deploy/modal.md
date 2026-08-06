# Развёртывание на Modal (serverless GPU)

[MODAL](https://modal.com) — платформа, где приложение описывается Python-кодом,
а GPU выделяется по запросу. Подходит для по-запросной генерации.

## 1. Установите Modal

```bash
pip install modal
modal token new        # войдите в аккаунт
```

## 2. Файл `modal_app.py` (в корне проекта)

```python
import subprocess
import modal

app = modal.App("ltx2-webui")

# Образ с GPU-зависимостями
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch", "torchaudio", "--index-url",
        "https://download.pytorch.org/whl/cu121",
    )
    .pip_install("fastapi", "uvicorn", "python-multipart", "requests", "omegaconf")
    .pip_install("huggingface_hub")
)

VOL = modal.Volume.from_name("ltx2-models", create_if_missing=True)

@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=1200,
    allow_concurrent_inputs=1,
    mounts=[modal.Mount.from_local_dir(".", remote_path="/app")],
    volumes={"/app/models": VOL},
    secrets=[modal.Secret.from_name("hf_token")],  # создайте secret с HF_TOKEN
)
def generate(photo_path: str, text: str) -> str:
    # Код агента запускаем как подпроцесс (использует GPU)
    cmd = [
        "python", "/app/ltx2_agent.py",
        "--photo", photo_path,
        "--text", text,
        "--resolution", "720p",
        "--out", "/app/ltx2_output/result.mp4",
    ]
    subprocess.run(cmd, check=True)
    # Загрузим результат на Modal Volume/файлы
    return "/app/ltx2_output/result.mp4"


@app.function(image=image, gpu="A100-80GB")
@modal.web_endpoint(method="POST")
def api(photo: modal.functions.Function, text: str):
    # сохранить photo, вызвать generate, вернуть URL
    ...
```

## 3. Запуск

```bash
modal deploy modal_app.py
modal run modal_app.py::generate --photo me.jpg --text "Я родилась 05 февраля 1987 года"
```

## 4. Скачивание весов

Веса загрузите один раз в Volume:
```bash
modal volume put ltx2-models models/ltx-2.3/ltx-2.3-22b-dev.safetensors ...
# или первым запуском download_models.sh внутри функции
```

## Примечания

- Modal платит за фактическое использование GPU (поминутно), а не за простой.
- `gpu="A100-80GB"` — рекомендуемая минимальная конфигурация.
- Создайте secret `hf_token` с переменной `HF_TOKEN` для скачивания весов.
