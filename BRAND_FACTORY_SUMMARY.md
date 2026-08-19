# Brand Factory OS — Резюме для пользователя

## Что сделано

1. **Проанализирован типичный путь** эксперта с нуля → бренд → лиды → продажи на автомате. Найдены узкие места: ниша наугад, нет ICP, нет позиционирования, нет доказательств, контент без системы, лиды теряются, продажи руками, выгорание.

2. **Спроектирована улучшенная система из 7 фаз, 21 агент, 25 артефактов**:
   - Phase1 Foundation (7 агентов) — полностью реализована как пример
   - Phase2 Offer, Phase3 Visual, Phase4 Content, Phase5 Leads, Phase6 Funnel+HeyGen, Phase7 Sales — агенты-заглушки с шаблонами, видимы в UI, готовы к подключению LLM

3. **Реализована фабрика агентов в коде**:
   - `brand_factory/manifest.py` — весь путь, подфазы, задачи, что улучшено
   - `brand_factory/models.py` — унифицированные модели проекта, агента, артефакта
   - `brand_factory/storage.py` — файловое хранилище проектов/artifacts (md, json, image, video)
   - `brand_factory/orchestrator.py` — оркестрация с учетом dependencies, approve разблокирует следующих
   - `brand_factory/agents/phase1_agents.py` — 7 агентов с реальной генерацией md (market, expert auditor, ICP, positioning, proof, competitor, manifesto)
   - `brand_factory/agents/generic_agents.py` — стабы для остальных фаз
   - `brand_factory/agents/base.py` — BaseAgent единый интерфейс

4. **Единое веб-приложение**:
   - FastAPI сервер `brand_factory/server.py` (порт 8002)
   - UI `brand_factory/ui/index.html + app.js` — Tailwind, темная тема, табы фаз, pipeline агентов, human-in-the-loop
   - Вкладки: Phase1 Foundation (детально), Phase2-7, Overview, Factory Graph, Artifacts, Full Journey Map
   - Phase1 мастер: форма входных данных (ниша, эксперт, истории, proof, конкуренты, файлы), 7 подфаз с проблемами ДО / улучшениями / задачами-чеклистами, сеть агентов с виджетами: статус, входы, выходы, логи, прогресс, кнопки Run / Preview / Approve / Reject
   - Передача данных: md, json манифесты, картинки, описания → каждый агент читает `get_artifact_content`, пишет `add_artifact`, следующий получает

5. **Пример Phase1** уже прогнан:
   - Проект `proj_ebde53d7` — 20 артефактов, включая `07_brand_manifest.md` и `07_brand_brief.json`
   - Файлы лежат в `brand_factory/projects/proj_ebde53d7/artifacts/`
   - Проверить: `cat brand_factory/projects/proj_ebde53d7/artifacts/07_brand_manifest.md`

## Как пользоваться

```bash
pip install fastapi uvicorn pydantic python-multipart --break-system-packages
PORT=8002 python -m brand_factory.server
# открыть http://localhost:8002
```

1. Нажми "+ Новый проект" — введи название, нишу, имя эксперта
2. Перейди в Phase1 — заполни входные данные слева, нажми "Сохранить и разблокировать агентов"
3. Запускай агентов по очереди: Run → Preview → Approve. Каждый Approved разблокирует зависимых.
4. После всех 7 — смотри итоговый Brand Manifest в Artifacts.
5. Дальше Phase2-7 по той же логике (сейчас стабы, но уже видишь интерфейс).

## Интеграция с HeyGen (из этого репо)

- Агент `heygen_video_factory` (Phase6) использует `heygen_client.py` и `photo_video_agent.py`
- В мастер Phase1 можно загрузить фото эксперта → оно станет артефактом image и уйдет в HeyGen factory
- В Phase6 укажешь сценарии из `14_reels_30.md` → агент сгенерит видео через HeyGen API, вернет `video_url` в `21_heygen_videos.json`

## Где смотреть детальный разбор

- `brand_factory/docs/ANALYSIS_FULL.md` — полный анализ пути, подфаз, задач, что улучшено
- `brand_factory/docs/JOURNEY_MAP.md` — техническая карта пути
- `brand_factory/manifest.py` — код-определение всех фаз и агентов (источник правды)
- `brand_factory/projects/` — примеры проектов

## Что дальше (если хочешь продолжить)

- Подключить LLM в `run()` методы (OpenAI)
- Подключить генерацию каруселей картинками
- Импортировать референс `autoexpert.html` если пришлешь содержимое (сейчас файл не попал в среду)
- Добавить n8n воркфлоу генератор

## Ссылка на превью

Запусти через Arena preview:

```bash
python -m brand_factory.server
# откроется на https://8002-{sandboxId}.e2b.app
```

Порт 8002 уже слушает 0.0.0.0 для превью.

