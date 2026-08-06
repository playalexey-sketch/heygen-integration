# Развёртывание на Lightning.ai

[Lightning.ai](https://lightning.ai) — платформа с готовыми GPU-ноутбуками и
приложениями. Хорошо подходит для запуска вручную с веб-интерфейсом.

## 1. Создайте GPU-ноутбук

1. Войдите на [lightning.ai](https://lightning.ai).
2. **Create Studio** → выберите шаблон **Standalone**.
3. Выберите GPU: **A100 80GB** или **A100 40GB** (≥40 ГБ VRAM).
4. Подождите запуск (студия поднимется за ~1-2 мин).

## 2. Клонируйте проект и установите

В терминале студии (пробейте в интерфейсе студии терминал):

```bash
git clone https://github.com/playalexey-sketch/heygen-integration.git
cd heygen-integration
pip install -r requirements.txt
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install omegaconf
```

## 3. Скачайте веса

```bash
export HF_TOKEN=hf_xxxx        # ваш Read-токен
bash deploy/download_models.sh
```

## 4. Запустите веб-интерфейс

Lightning отдаёт внешний адрес для портов. Запустите:

```bash
export HOST=0.0.0.0 PORT=8001
python run_webui.py
```

Lightning.ai покажет публичную ссылку (обычно вида
`https://<studio>-8001.lightning.ai`).

## 5. Проверка

```bash
curl http://<studio>-8001.lightning.ai/api/env
```

## Примечания

- Lightning платит за время работы студии. Останавливайте, когда не нужно.
- Первый запуск может быть медленным из-за загрузки весов.
