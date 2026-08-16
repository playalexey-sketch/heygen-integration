# Instagram Reels Intelligence Agent

Агент `instagram_reels_agent.py` собирает Reels публичного профиля, обогащает метрики, строго фильтрует победителей и выпускает отчёты в JSON, CSV, Markdown и HTML.

## Выбранный стек

### 1. Discovery и транскрипты

[Apify Instagram Reel Scraper](https://apify.com/apify/instagram-reel-scraper)

- до 1 000 Reels профиля;
- лайки, комментарии, просмотры, дата, длительность, подпись, аудио;
- опциональный share count;
- опциональный transcript;
- поддерживается Apify.

### 2. Saves/shares enrichment

[Instagram Reel & Post Analytics by URL](https://apify.com/patient_discovery/instagram-reel-analytics-by-url)

- пакетный ввод Reel URL;
- likes, comments, plays, shares, saves и reposts;
- 128 полей;
- отдельный проход только по Reel, которые уже прошли дешёвый порог лайков.

## Почему два Actor

Первый Actor обходит весь профиль и извлекает контент. Второй точечно обогащает только потенциальных победителей закрытыми метриками. Это экономит запросы и не подменяет отсутствующее значение нулём.

## Ограничение официального Meta API

Meta Graph API отдаёт saves, shares, reach и watch time только владельцу или аккаунту, который авторизовал приложение. Для произвольного конкурента официальный Insights endpoint не работает. Поэтому конкурентный аудит использует scraper provider, а каждая метрика хранит источник и статус верификации.

## Быстрый запуск

### 1. Создать Apify token

Откройте [Apify Console](https://console.apify.com/account/integrations), создайте API token и сохраните его локально. Не вставляйте токен в код, Git или публичный чат.

### 2. Экспортировать переменную

```bash
export APIFY_TOKEN='ваш_токен'
```

### 3. Проверить конфигурацию

```bash
python instagram_reels_agent.py doctor --profile bartsevmatvei
```

### 4. Выполнить строгий анализ

```bash
python instagram_reels_agent.py analyze \
  --profile bartsevmatvei \
  --min-likes 1000 \
  --min-saves 100 \
  --min-shares 100 \
  --match all \
  --max-results 1000 \
  --output-dir reports/reels-agent-live
```

`--match all` означает: лайки ≥ 1 000 **И** saves ≥ 100 **И** shares ≥ 100.

Если достаточно, чтобы saves или shares прошли порог:

```bash
--match any
```

## Политика отсутствующих метрик

По умолчанию используется безопасный режим:

```bash
--missing-metrics exclude
```

- `exclude` — Reel не проходит строгий фильтр;
- `error` — агент завершает работу и показывает проблемный Reel;
- `include-unverified` — Reel попадает в отдельный список кандидатов, но не называется подтверждённым.

Значение `null` никогда не превращается в `0`.

## Анализ текста

Агент может использовать любой OpenAI-compatible endpoint:

```bash
export LLM_BASE_URL='https://api.example.com/v1'
export LLM_API_KEY='...'
export LLM_MODEL='...'
```

Если LLM не настроен, используется детерминированный clean-room анализ:

- тема;
- механика хука;
- удержание;
- триггер сохранения;
- триггер пересылки;
- риск поляризации;
- оригинальный Reel-сценарий;
- CTA с цифрой 2;
- обложка, подпись, закреплённый комментарий и альтернативные хуки.

## Результаты

В `--output-dir` создаются:

- `all_reels.json` — все найденные Reels и статусы метрик;
- `qualified_reels.json` — только прошедшие/разрешённые кандидаты с анализом;
- `qualified_reels.csv` — таблица для Excel/Google Sheets;
- `report.md` — полный отчёт;
- `report.html` — стилизованный отчёт для браузера/PDF.

## Публичный snapshot

В репозитории есть подтверждённый публичный срез:

```bash
python instagram_reels_agent.py analyze \
  --snapshot reports/data/bartsevmatvei_public_snapshot.json \
  --min-likes 1000 \
  --min-saves 100 \
  --min-shares 100 \
  --match all \
  --missing-metrics include-unverified \
  --output-dir reports/reels-agent-snapshot
```

Snapshot содержит 12 доступных Reels и 6 кандидатов с 1 000+ лайков. Saves/shares в публичной витрине отсутствуют, поэтому они честно помечены `н/д`, а кандидаты — `unverified-candidate`.

## Тесты

```bash
python -m unittest discover -s tests -p 'test_instagram_reels_agent.py' -v
```
