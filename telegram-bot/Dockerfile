FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Каталог с этапами (stages.json) — см. volume в docker-compose.yml
VOLUME ["/app/bot_data"]

CMD ["python", "main.py"]
