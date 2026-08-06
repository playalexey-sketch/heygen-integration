# Развёртывание на RunPod (Serverless GPU)

RunPod даёт GPU подежно и может запускать наш Docker-образ.

## 1. Подготовка (одноразово)

Соберите и отправьте образ в Docker Hub (или используйте RunPod's build).
У вас должен быть Docker с GPU (`nvidia-container-toolkit`), либо соберите
образ локально и запушьте.

```bash
cd heygen-integration

# Вход в Docker Hub
docker login

# Соберите и запушьте образ
docker build -f deploy/Dockerfile -t YOUR_DOCKERHUB/ltx2-webui:latest .
docker push YOUR_DOCKERHUB/ltx2-webui:latest
```

> Внимание: образ большой (~50 ГБ с весами). Лучше собрать веса в сам образ
> или смонтировать их с сетевого хранилища (volume). На больших GPU-нодах
> RunPod можно собрать прямо на ноде.

## 2. Запуск Serverless endpoint

1. В RunPod откройте **Serverless** → **New Endpoint**.
2. Выберите GPU: **A100 80GB** или **H100** (LTX-2.3 — 22B, нужно ≥40 ГБ VRAM).
3. В поле **Docker Image** укажите: `YOUR_DOCKERHUB/ltx2-webui:latest`.
4. Container Start Command: `python run_webui.py`
5. Environment variables — скопируйте из `deploy/env.example`.
6. Создайте эндпоинт. RunPod выдаст HTTP-ссылку.

## 3. Проверка

```bash
curl -X POST <RUNPOD_URL>/api/generate \
  -F "photo=@me.jpg" -F "text=Я родилась 05 февраля 1987 года и я красотка" \
  -F "resolution=720p"
```

Ответ вернёт `job_id`. Следите за статусом:

```bash
curl <RUNPOD_URL>/api/jobs/<job_id>
```

Когда `status=completed` — скачивайте видео по `/output/<job_id>`.

## Примечания

- Веса скачивайте в контейнер или монтируйте через volume (см. `download_models.sh`).
- Остановите endpoint после работы, чтобы не платить за простой.
