# Full Brand → Leads → Auto Sales Journey Map
## Эксперт / Бизнес с нуля

Этот документ - эталонный путь, улучшенный фабрикой агентов.

### Phase 1: Foundation & Brand DNA (1 день)
**Проблема обычно:** 2-3 месяца самокопаний, непонятно кто клиент, позиционирование "эксперт по всему", нет доказательств.

**Улучшено фабрикой:**
- market_researcher: сканит нишу, собирает 20 вопросов аудитории, тренды, топ конкурентов с gaps
- expert_auditor: 30 вопросов распаковки, суперсила, банк историй 7 типов для Reels
- icp_architect: 3 аватара с JTBD, болями, языком клиента, триггерами покупки
- positioning_strategist: формула позиционирования + Big Idea + враг + one-liners для шапок
- proof_collector: упаковка кейсов по CASE, Authority Stack, чек-лист что собрать
- competitor_analyst: gap-матрица, 5 идей отстройки
- manifesto_synthesizer: сводит в Brand Manifest md + json briefing для всех следующих агентов

**Артефакты:** 01_market_report.md, 02_expert_dossier.md, 03_icp_avatars.md, 04_positioning.md, 05_proof_board.md, 06_competitor_map.md, 07_brand_manifest.md (главный)

**Human checkpoints:** утверждение ниши, ICP, позиционирования, манифеста.

### Phase 2: Offer & Money Model
**Обычно:** один продукт, нет лестницы, нет апселла, цена с потолка.
**Улучшено:** Offer Architect собирает 4 уровня Free→990→35k→150k + юнит-экономика. Mechanism Creator именует метод. Guarantee.
**Артефакты:** 08_offer_ladder.md, 09_mechanism.md

### Phase 3: Visual & Social Setup
**Обычно:** визуал на вкус, шапка не продает.
**Улучшено:** Visual Director дает палитру json + мудборд + ТЗ. Profile Optimizer 5 вариантов био под IG/TG/YT + хайлайты.
**Артефакты:** 11_visual_board.md, 12_profile_pack.md

### Phase 4: Content Machine (главный ускоритель)
**Обычно:** думают над каждым Reels час, посты без CTA, выгорание, 0 системы.
**Улучшено:**
- Content Strategist: матрица 50% охват 30% доверие 20% продажи, 4-6 рубрик
- Reels Factory: 30 хуков с сценарием Hook-Context-Twist-Value-CTA, банк CTA
- Carousel Factory: 10 каруселей
- Editorial Planner: календарь 30 дней с привязкой к воронкам и продуктам
- Интеграция HeyGen: фото → говорящее видео (используем heygen_client.py из репо)

**Артефакты:** 13_content_strategy.md, 14_reels_30.md, 15_carousels.md, 16_editorial_30days.json

### Phase 5: Lead System
**Обычно:** "подпишись" = 0.5% конверсия, лиды теряются в директе.
**Улучшено:**
- Lead Magnet Architect: квиз-магнит "Где сливаешь лидов" с авто-результатом, 35-60% конверсия
- Landing Builder: сценарий бота Manychat/Salebot, квиз, ленд
- CRM Integrator: n8n/Make схема, теги, пайплайн, автонапоминания

**Артефакты:** 17_lead_magnets.md, 18_landing_structure.md, 19_crm_schema.md, automation.json

### Phase 6: Funnel & Distribution + HeyGen Factory (уникально)
**Обычно:** сторис руками, Reels не перепостятся, комментарии без ответа.
**Улучшено:**
- AutoWarmup: 7-дневный прогрев через бота/email/Reels из банка историй
- HeyGen Video Factory: берет 14_reels_30.md + фото эксперта → генерирует 10 говорящих аватаров видео через HeyGen API (photo_video_agent), автосубтитры
- DM Automation: триггеры по кодовому слову ГАЙД/РАЗБОР, автоответы, сегментация

**Артефакты:** 20_warmup_7days.md, 21_heygen_videos.json (video_url), 22_dm_flows.json

### Phase 7: Sales OS & Scale
**Обычно:** продажи в лоб, боятся продавать, все на себе.
**Улучшено:**
- Sales Script: DM скрипт, созвон 30 мин, отработка возражений
- Webinar Automator: структура автовеба 60 мин + оффер
- Scale Ops: KPI дашборд (лиды, конверсия, выручка), hiring план (контент, трафик, продажи)

**Артефакты:** 23_sales_scripts.md, 24_webinar_plan.md, 25_kpi_dashboard.md

## Сеть агентов — как передают данные
Каждый агент:
- Читает artifacts из предыдущих (md, json, картинки)
- Генерит новые artifacts
- Обновляет свой статус: idle → waiting_input → ready → running → needs_review → approved
- Человек видит в UI: входы, выходы, превью md, прогресс, логи, кнопки Approve/Reject/Run

Поток:
```
Input (niche, expert, stories, proof, competitors) 
→ market_researcher (01_*)
→ expert_auditor (02_*) + competitor_analyst (06_*)
→ icp_architect (03_*)
→ positioning_strategist (04_*) + proof_collector (05_*)
→ manifesto_synthesizer (07_*)  — человек утверждает → brand_brief.json

→ Phase2 offer_architect (08_*) → mechanism...
→ Phase3 visual_director (11_*)
→ Phase4 content_strategist → reels_factory + carousel → editorial
→ Phase5 lead_magnet...
→ Phase6 warmup + heygen_video_factory (использует heygen_client.create_avatar_video) + dm
→ Phase7 sales + webinar + scale
```

Все хранится в /brand_factory/projects/proj_*/artifacts/

## Что можно улучшить еще (после MVP)
- Добавить LLM вызовы (OpenAI API) вместо мок-генерации (сейчас templates, но интерфейс готов)
- Добавить реальную интеграцию с Instagram Graph API для автопостинга
- Добавить n8n workflow generation в виде JSON для импорта
- Добавить генерацию каруселей в виде картинок через generate_image tool
- Добавить voice cloning для HeyGen через heygen_tools
- Добавить мульти-агент дебаты: 2 агента спорят о позиционировании, человек выбирает
- Дашборд реального времени лидов
