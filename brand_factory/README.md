# Brand Factory OS — Фабрика Агентов для бренда / лидов / автопродаж

Единое веб-приложение (FastAPI + vanilla JS) которое ведет эксперта от 0 до автопродаж через сеть из 21 агента.

## Быстрый старт
```bash
pip install fastapi uvicorn pydantic python-multipart
python -m brand_factory.server
# открой http://localhost:8002
```

Порт по умолчанию 8002 (переменная PORT).

## Архитектура
- `manifest.py` — полный путь 7 фаз, подфазы, задачи, агенты (что улучшено)
- `models.py` — унифицированные модели AgentManifest, Artifact, Project, AgentRunState
- `storage.py` — файловое хранилище проектов + artifacts (md, json, картинки, видео)
- `orchestrator.py` — запуск агентов с учетом dependencies
- `agents/phase1_agents.py` — полная реализация 7 агентов фазы 1 (real generation)
- `agents/generic_agents.py` — стабы для фаз 2-7 (видимы, можно запускать, генерят шаблоны)
- `agents/base.py` — базовый класс BaseAgent
- `ui/index.html + app.js` — единый UI: проекты слева, табы фаз, pipeline агентов, approval flow, artifacts, factory graph, journey map

## Единый интерфейс агента (важно)
Каждый агент:
- id, name, icon, role, description
- inputs_required[] — какие артефакты / поля нужны
- outputs_produced[] — что генерит
- dependencies[] — кто должен быть approved до него
- tasks[] — конкретные задачи внутри
- human_checkpoints[] — где человек обязательно смотрит
- status: idle | waiting_input | ready | running | needs_review | approved | failed
- В UI: видишь входы, выходы, превью md, логи, прогресс, кнопки Run / Approve / Reject

Передача данных: агент пишет md/json/картинки в `/projects/{id}/artifacts/` → следующий читает через `get_artifact_content()`.

## Phase 1 — пример полностью
Фаза 1 реализована как пример с детальной проработкой:

Подфазы:
1.1 Валидация ниши — market_researcher
1.2 Распаковка эксперта — expert_auditor
1.3 ICP и JTBD — icp_architect
1.4 Позиционирование и Big Idea — positioning_strategist
1.5 Доказательства — proof_collector
1.6 Конкуренты и gaps — competitor_analyst
1.7 Brand Manifest — manifesto_synthesizer (сводит все в 07_brand_manifest.md + 07_brand_brief.json)

Человек заполняет входные данные (ниша, эксперт, истории, proof, конкуренты) → запускает агентов по очереди → смотрит md → Approve → следующий агент разблокируется.

После Approve манифеста — он становится брифом для всех фаз 2-7.

## Интеграция с HeyGen (из основного репо)
Агент `heygen_video_factory` (Phase 6) использует `heygen_client.py` и `photo_video_agent.py`:
- Берет сценарии Reels из 14_reels_30.md
- Берет фото эксперта из artifacts
- Генерит говорящие аватар-видео через HeyGen API (или LTX-2 локально)
- Возвращает video_url в 21_heygen_videos.json

## Что улучшено vs обычный путь
См. `docs/JOURNEY_MAP.md` — подробно по каждой фазе проблемы до и улучшения.

Кратко:
- Система вместо хаоса
- Фабрика Reels 30 шт сразу + HeyGen без съемок
- DM триггеры по слову = 35% в лида
- Единый Brand Manifest md+json
- Human-in-the-loop утверждение
- Одно приложение вместо Notion+Docs+Figma+Miro

## Дальше
- Подключить LLM (OpenAI) в run() методы
- Подключить генерацию картинок
- Подключить n8n вебхуки
- Добавить импорт instagram graph

