# Open-source Instagram Reels Agent

## Выбранный стек

| Компонент | Репозиторий | Лицензия | Роль |
|---|---|---|---|
| Instaloader 4.15.3 | [instaloader/instaloader](https://github.com/instaloader/instaloader) | MIT | Полный обход вкладки Reels через `Profile.get_reels()` |
| Reels Vault | [Overusedhydra/reels-vault](https://github.com/Overusedhydra/reels-vault) | MIT | yt-dlp/Playwright, FFmpeg и локальный Whisper |
| parth-dl | [parthmax2/parth-dl](https://github.com/parthmax2/parth-dl) | MIT | Zero-dependency fallback для отдельного публичного Reel |

Зафиксированные проверенные коммиты:

- Instaloader: `5434692` от 26.07.2026;
- Reels Vault: `959c120` от 30.06.2026;
- parth-dl: `5cc1525` от 25.07.2026.

## Почему этот стек

Instaloader — зрелый open-source инструмент с отдельным `get_reels()`, пагинацией профиля, caption, likes, comments, video URL и JSON metadata. Reels Vault добавляет локальную аудиорасшифровку, а parth-dl даёт независимый fallback для открытого Reel без runtime-зависимостей.

## Установка

Базовая версия:

```bash
bash scripts/bootstrap_open_source_reels_stack.sh --base
```

С локальным Whisper:

```bash
bash scripts/bootstrap_open_source_reels_stack.sh --transcription
```

Установка выполняется в отдельное окружение `.venv-reels`, которое не нужно коммитить.

## Проверка

```bash
.venv-reels/bin/python open_source_reels_agent.py doctor
```

## Полный обход профиля

```bash
.venv-reels/bin/python open_source_reels_agent.py run \
  --profile bartsevmatvei \
  --max-results 1000 \
  --output-dir deliverables/open_source_reels_live
```

## Обход и локальная расшифровка

```bash
.venv-reels/bin/python open_source_reels_agent.py run \
  --profile bartsevmatvei \
  --max-results 1000 \
  --transcribe \
  --cookies-from chrome \
  --whisper-model small \
  --output-dir deliverables/open_source_reels_live
```

Используйте только собственную уже существующую браузерную сессию локально. Не передавайте cookie или session file в чат и не добавляйте их в Git.

## Что создаётся

- `open_source_reels.json` — все Reels, доступные метрики, captions, transcripts и анализ;
- `open_source_reels.csv` — таблица;
- `report.md` — отчёт;
- `report.html` — стилизованный HTML.

## Статус закрытых метрик

Open-source profile scraping надёжно получает публичные likes, comments, caption, дату, duration, video URL и, когда Instagram отдаёт поле, plays. Saves и shares не являются стабильными публичными полями конкурента. Агент оставляет их `null/н/д`, а не заменяет нулём.

Точные saves/shares официально доступны владельцу аккаунта через Instagram Insights. Любой scraper, обещающий эти значения для произвольного конкурента, использует закрытый endpoint, авторизованную сессию либо оценивает метрику. Источник должен быть обозначен.

## Ограничение текущей среды

В Arena sandbox исходный код трёх проектов был найден, клонирован с GitHub и проверен. Однако прямые TLS-запросы из shell к Instagram заблокированы сетевой политикой среды, а Instagram-сессия отсутствует. Поэтому live-скан не выдаётся за выполненный.

Для результата этого запуска агент обработал подтверждённый публичный snapshot из 12 доступных Reels. Интерактивная библиотека находится в:

- `deliverables/bartsev_all_reels_library/index.html`;
- `deliverables/bartsev_all_reels_library/bartsevmatvei_all_reels.json`.

После запуска агента в среде с доступом к Instagram тот же пайплайн пересоберёт данные с exact local transcripts.
