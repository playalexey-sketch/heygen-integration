"""
Brand Factory Manifest - Complete journey from 0 to auto sales
8 phases, each with subphases, tasks, agents
"""

from .models import Phase, SubPhase, TaskItem, AgentManifest

def make_tasks(prefix, items):
    tasks = []
    for i, (title, desc) in enumerate(items, 1):
        tasks.append(TaskItem(id=f"{prefix}_t{i}", title=title, description=desc))
    return tasks

# === Phase definitions ===
PHASES = []

# Phase 1: FOUNDATION / BRAND DNA
phase1_agents = [
    AgentManifest(
        id="market_researcher",
        name="Market Researcher",
        icon="🔍",
        phase_id="phase_1",
        role="Исследует нишу, спрос, тренды, болотистые боли",
        description="Анализирует нишу: объем, тренды, вопросы аудитории, поисковый спрос, конкуренты в соцсетях",
        inputs_required=["niche", "competitors", "socials"],
        outputs_produced=["01_market_report.md", "01_trends.json", "01_keywords.md"],
        dependencies=[],
        tasks=["Собрать поисковые запросы", "Проанализировать топ-10 конкурентов", "Выявить тренды в нише", "Сформировать карту боли → желания"],
        estimated_time="8 min",
        human_checkpoints=["Утвердить нишу и угол входа"],
        ui_hints={"form_fields": ["niche", "competitors"]}
    ),
    AgentManifest(
        id="expert_auditor",
        name="Expert Auditor",
        icon="🧠",
        phase_id="phase_1",
        role="Распаковать эксперта",
        description="Глубокая распаковка опыта, кейсов, суперсилы, историй",
        inputs_required=["expert_name", "expert_current", "superpowers", "stories", "proof_existing"],
        outputs_produced=["02_expert_dossier.md", "02_superpowers.md", "02_stories_bank.md"],
        dependencies=["market_researcher"],
        tasks=["Распаковать 30 вопросов", "Выявить суперсилу и метод", "Собрать 5-7 историй", "Оцифровать результаты клиентов"],
        estimated_time="10 min",
        human_checkpoints=["Проверить истории и суперсилу"],
    ),
    AgentManifest(
        id="icp_architect",
        name="ICP Architect",
        icon="🎯",
        phase_id="phase_1",
        role="Строит аватар идеального клиента",
        description="Создает 2-3 ICP с болями, желаниями, возражениями, JTBD",
        inputs_required=["niche", "expert_dossier", "market_report"],
        outputs_produced=["03_icp_avatars.md", "03_icp_map.json", "03_objections.md"],
        dependencies=["expert_auditor"],
        tasks=["Сегментировать аудиторию", "Описать 3 аватара", "Прописать JTBD и боли", "Собрать возражения и язык клиента"],
        estimated_time="7 min",
        human_checkpoints=["Утвердить основного ICP"]
    ),
    AgentManifest(
        id="positioning_strategist",
        name="Positioning Strategist",
        icon="💎",
        phase_id="phase_1",
        role="Формирует позиционирование и Big Idea",
        description="Формула: кому, что, как, почему ты, отличие, обещание",
        inputs_required=["icp_avatars", "expert_dossier", "market_report"],
        outputs_produced=["04_positioning.md", "04_big_idea.md", "04_one_liners.md"],
        dependencies=["icp_architect"],
        tasks=["Сформулировать позиционирование в 1 фразе", "Big Idea / Enemy / Mission", "3 One-liner для шапки профиля", "Тест на уникальность vs конкуренты"],
        estimated_time="6 min",
        human_checkpoints=["Выбрать 1 вариант позиционирования"]
    ),
    AgentManifest(
        id="proof_collector",
        name="Proof Collector",
        icon="🏆",
        phase_id="phase_1",
        role="Собирает доказательства",
        description="Скелет доказательств: кейсы, цифры, отзывы, своя история, медийность",
        inputs_required=["stories_bank", "proof_existing"],
        outputs_produced=["05_proof_board.md", "05_case_templates.md", "05_authority_stack.md"],
        dependencies=["expert_auditor"],
        tasks=["Структурировать кейсы по формуле", "Собрать цифры и скрины", "Составить Authority Stack"],
        estimated_time="5 min",
        human_checkpoints=["Загрузить скрины/фото доказательств"]
    ),
    AgentManifest(
        id="competitor_analyst",
        name="Competitor Analyst",
        icon="⚔️",
        phase_id="phase_1",
        role="Анализ конкурентов на gaps",
        description="Анализ 5-7 конкурентов: контент, офферы, визуал, монетизация, слабые места",
        inputs_required=["competitors", "market_report"],
        outputs_produced=["06_competitor_map.md", "06_gap_opportunities.md"],
        dependencies=["market_researcher"],
        tasks=["Разбор аккаунтов", "Разбор офферов", "Найти гэпы", "Сформулировать возможности"],
        estimated_time="6 min",
        human_checkpoints=[]
    ),
    AgentManifest(
        id="manifesto_synthesizer",
        name="Manifesto Synthesizer",
        icon="📜",
        phase_id="phase_1",
        role="Сводит все в Brand Manifest",
        description="Сводит весь фундамент в единый манифест бренда",
        inputs_required=["positioning", "icp", "proof_board", "competitor_map"],
        outputs_produced=["07_brand_manifest.md", "07_brand_brief.json", "07_next_steps.md"],
        dependencies=["positioning_strategist", "proof_collector", "competitor_analyst"],
        tasks=["Собрать манифест", "Brief для всех следующих агентов", "План на фазу 2"],
        estimated_time="5 min",
        human_checkpoints=["Утвердить Brand Manifest - это основа всего дальше"]
    ),
]

phase1_subphases = [
    SubPhase(
        id="1_1_market",
        title="1.1 Валидация ниши и рынка",
        goal="Понять где деньги, где спрос, где конкуренты ослабли",
        problems_before=["Выбирают нишу наугад", "Нет данных о спросе"],
        improvements=["Agent сканирует YouTube/TG/Insta, собирает вопросы", "Дает heatmap трендов + оценку чека"],
        tasks=make_tasks("1_1", [
            ("Сбор поисковых интентов", "Yandex Wordstat, YouTube, TikTok поиск"),
            ("Топ-10 конкурентов - что продают, как", "Таблица офферов"),
            ("Тренд-анализ", "Что растет в ближайшие 6 мес"),
            ("Карта болей → желаний", "20 болей / 20 желаний"),
        ]),
        agents=["market_researcher"],
        artifacts=["01_market_report.md"]
    ),
    SubPhase(
        id="1_2_expert",
        title="1.2 Распаковка эксперта",
        goal="Вытащить суперсилу, метод, истории",
        problems_before=["Эксперт не может сформулировать чем он уникален", "Контент без личности"],
        improvements=["AI-интервью 30 вопросов + голосовые", "Сразу генерит story-bank для Reels"],
        tasks=make_tasks("1_2", [
            ("Superpower интервью", "30 вопросов"),
            ("Оцифровка кейсов", "До/После цифры"),
            ("Банк историй", "5 типов: провал, прорыв, клиент, закулисье, миссия"),
            ("Методология", "Назвать и упаковать метод в 3-5 шагов"),
        ]),
        agents=["expert_auditor"],
        artifacts=["02_expert_dossier.md", "02_stories_bank.md"]
    ),
    SubPhase(
        id="1_3_icp",
        title="1.3 ICP и JTBD",
        goal="Точно описать кого ведем к результату",
        problems_before=["Для всех", "Нет языка клиента"],
        improvements=["Генерим 3 аватара с фото, цитатами, триггерами покупки"],
        tasks=make_tasks("1_3", [
            ("Сегментация", "3 уровня: новичок, продвинутый, профи"),
            ("JTBD интервью-прототип", "Когда, хочу, чтобы, но мешает"),
            ("Возражения", "Топ-10 возражений + ответы"),
            ("Триггеры покупки", "Что заставит купить сейчас"),
        ]),
        agents=["icp_architect"],
        artifacts=["03_icp_avatars.md"]
    ),
    SubPhase(
        id="1_4_positioning",
        title="1.4 Позиционирование и Big Idea",
        goal="Занять место в голове",
        problems_before=["Я эксперт по всему", "Не запоминается"],
        improvements=["Формула + Big Idea + Enemy + One-liners для шапок"],
        tasks=make_tasks("1_4", [
            ("Формула позиционирования", "Я помогаю [кому] получить [что] через [как] за [срок] без [боль]"),
            ("Big Idea и враг", "Против чего боремся"),
            ("One-liners", "3 варианта для био"),
            ("Тест уникальности", "Отстройка от 5 конкурентов"),
        ]),
        agents=["positioning_strategist"],
        artifacts=["04_positioning.md", "04_big_idea.md"]
    ),
    SubPhase(
        id="1_5_proof",
        title="1.5 Доказательства и Authority",
        goal="Доверие за 7 секунд",
        problems_before=["Нет кейсов", "Нет доказательств"],
        improvements=["Автопакует кейсы по формуле CASE: Context-Action-Specific-Effect"],
        tasks=make_tasks("1_5", [
            ("Кейсы", "3 кейса минимум по шаблону"),
            ("Цифры", "Сколько клиентов, какой результат средний"),
            ("Медийность и регалии", "Где выступал, дипломы"),
            ("Социальное доказательство", "Как собирать отзывы автоматом"),
        ]),
        agents=["proof_collector"],
        artifacts=["05_proof_board.md"]
    ),
    SubPhase(
        id="1_6_gaps",
        title="1.6 Конкуренты и возможности",
        goal="Найти голубой океан в красном",
        problems_before=["Копируют конкурентов", "Не видят возможностей"],
        improvements=["Gap-матрица + 5 идей как отстроиться"],
        tasks=make_tasks("1_6", [
            ("Разбор 5-7 аккаунтов", "Что делают сильно/слабо"),
            ("Разбор продуктов", "Цены, funnel"),
            ("Gap анализ", "Чего им не хватает"),
            ("Ideas Bank", "5 идей отстройки"),
        ]),
        agents=["competitor_analyst"],
        artifacts=["06_gap_opportunities.md"]
    ),
    SubPhase(
        id="1_7_manifest",
        title="1.7 Brand Manifest и Brief",
        goal="Единый документ - правда бренда",
        problems_before=["Хаос, нет единого видения"],
        improvements=["Один манифест = бриф для всех следующих агентов и дизайнеров"],
        tasks=make_tasks("1_7", [
            ("Свести манифест", "Миссия, ценности, тон, ICP, позиционирование, оффер-наметки, визуал-наметки"),
            ("Brand Brief json", "Машиночитаемый бриф для фабрики агентов"),
            ("Approval", "Утвердить у человека"),
        ]),
        agents=["manifesto_synthesizer"],
        artifacts=["07_brand_manifest.md", "07_brand_brief.json"]
    ),
]

phase1 = Phase(
    id="phase_1",
    title="Phase 1: Foundation & Brand DNA",
    subtitle="Фундамент - кто ты, для кого, почему тебе верить",
    icon="🧱",
    color="#FF6B6B",
    goal="За 1 день собрать весь фундамент бренда, который обычно собирают месяцами",
    outcome="Brand Manifest + ICP + Positioning + Proof Board - готово чтобы строить контент и продажи",
    subphases=phase1_subphases,
    agents=phase1_agents
)

# Phase 2: Offer Architecture
phase2_agents = [
    AgentManifest(id="offer_architect", name="Offer Architect", icon="📦", phase_id="phase_2", role="Строит лестницу продуктов", description="От лид-магнита до high-ticket, Tripwire, Core, Profit Maximizer", inputs_required=["brand_manifest", "icp"], outputs_produced=["08_offer_ladder.md", "08_pricing.json"], dependencies=[], tasks=["Продуктовая лестница", "Ценообразование", "Обещания"], human_checkpoints=["Утвердить цены и лестницу"]),
    AgentManifest(id="mechanism_creator", name="Mechanism Creator", icon="⚙️", phase_id="phase_2", role="Создает уникальный механизм", description="Название метода, 3-5 шагов, почему работает", inputs_required=["expert_dossier"], outputs_produced=["09_mechanism.md"], dependencies=["offer_architect"], tasks=["Назвать метод", "Прописать шаги"], human_checkpoints=[]),
    AgentManifest(id="guarantee_copy", name="Guarantee & USP", icon="🛡️", phase_id="phase_2", role="Гарантии и УТП", description="", inputs_required=["offer_ladder"], outputs_produced=["10_guarantee.md"], dependencies=["offer_architect"], tasks=[], human_checkpoints=[]),
]

phase2 = Phase(
    id="phase_2",
    title="Phase 2: Offer & Money Model",
    subtitle="Что продаем, как упаковано, сколько стоит",
    icon="💰",
    color="#4ECDC4",
    goal="Собрать продуктовую лестницу и офферы под каждый ICP",
    outcome="Offer Ladder + 3 оффера + прайс + механизм",
    subphases=[
        SubPhase(id="2_1_ladder", title="2.1 Лестница продуктов", goal="От 0 до 500к", problems_before=["Один продукт", "Нет апселла"], improvements=["Авто сборка лестницы под чек"], tasks=make_tasks("2_1", [("Ladder", "Free -> Tripwire 990р -> Core 30к -> High 150к"), ("Unit-экономика", "CAC LTV")]), agents=["offer_architect"], artifacts=["08_offer_ladder.md"]),
        SubPhase(id="2_2_mech", title="2.2 Механизм и название метода", goal="Отстройка", problems_before=["Как у всех"], improvements=["Уникальный механизм = запоминание"], tasks=make_tasks("2_2", [("Название", "Метод ..."), ("Шаги", "3-5 шагов")]), agents=["mechanism_creator"], artifacts=["09_mechanism.md"]),
    ],
    agents=phase2_agents
)

# Phase 3: Visual Identity + Social Setup
phase3_agents = [
    AgentManifest(id="visual_director", name="Visual Director", icon="🎨", phase_id="phase_3", role="Визуальная система", description="Цвета, шрифты, стиль, референсы, мудборд", inputs_required=["brand_manifest"], outputs_produced=["11_visual_board.md", "11_palette.json", "moodboard_images"], dependencies=[], tasks=["Палитра", "Шрифты", "Мудборд"], human_checkpoints=["Утвердить визуал"]),
    AgentManifest(id="profile_optimizer", name="Profile Optimizer", icon="📱", phase_id="phase_3", role="Упаковка профилей", description="Шапки, хайлайты, аватар, линк, CTA для IG, TG, YT, LinkedIn", inputs_required=["positioning", "visual_board"], outputs_produced=["12_profile_pack.md", "12_bio_variants.md"], dependencies=["visual_director"], tasks=["Био", "Хайлайты", "Аватар ТЗ"], human_checkpoints=["Сделать скрин до/после"]),
]

phase3 = Phase(
    id="phase_3",
    title="Phase 3: Visual & Social Setup",
    subtitle="Упаковка которая продает за 3 сек",
    icon="✨",
    color="#FFE66D",
    goal="Визуал + упаковка всех соцсетей",
    outcome="Brandbook lite + упакованные профили + ТЗ на дизайнера",
    subphases=[
        SubPhase(id="3_1_visual", title="3.1 Визуальная система", goal="Узнаваемость", problems_before=["Все разное"], improvements=["Параметры в json для генерации"], tasks=make_tasks("3_1", [("Палитра 3-5 цветов", ""), ("Шрифты", ""), ("Мудборд 9 картинок", "")]), agents=["visual_director"], artifacts=["11_visual_board.md"]),
        SubPhase(id="3_2_profile", title="3.2 Упаковка профилей", goal="Конверсия в подписку", problems_before=["Шапка не цепляет"], improvements=["Генерация био под каждую платформу + A/B"], tasks=make_tasks("3_2", [("Био 5 вариантов", ""), ("Хайлайты обложки + названия", ""), ("Linkbio", "")]), agents=["profile_optimizer"], artifacts=["12_profile_pack.md"]),
    ],
    agents=phase3_agents
)

# Phase 4: Content Machine
phase4_agents = [
    AgentManifest(id="content_strategist", name="Content Strategist", icon="🗺️", phase_id="phase_4", role="Стратегия контента", description="Рубрики, воронка контента, % типы", inputs_required=["brand_manifest", "icp"], outputs_produced=["13_content_strategy.md", "13_rubrics.json"], dependencies=[], tasks=["Рубрики", "Воронка: охват, доверие, продажа"], human_checkpoints=["Утвердить рубрики"]),
    AgentManifest(id="reels_factory", name="Reels Factory", icon="🎬", phase_id="phase_4", role="Генерация Reels", description="30 хуков, сценарии, триггеры, сторителлинг, интеграция HeyGen", inputs_required=["stories_bank", "content_strategy"], outputs_produced=["14_reels_30.md", "14_scripts_w_manifests.json"], dependencies=["content_strategist"], tasks=["30 идей Reels", "Сценарии с хуками"], human_checkpoints=["Отобрать 10"]),
    AgentManifest(id="carousel_factory", name="Carousel Factory", icon="🎠", phase_id="phase_4", role="Карусели и посты", description="10 каруселей + лонгриды", inputs_required=["content_strategy"], outputs_produced=["15_carousels.md"], dependencies=["content_strategist"], tasks=["Карусели"], human_checkpoints=[]),
    AgentManifest(id="editorial_planner", name="Editorial Planner", icon="📅", phase_id="phase_4", role="Контент-план 30 дней", description="Календарь с CTA и автоворонками", inputs_required=["reels_30", "carousels"], outputs_produced=["16_editorial_30days.json", "16_editorial.md"], dependencies=["reels_factory", "carousel_factory"], tasks=["План 30 дней", "CTA в каждом"], human_checkpoints=["Утвердить план"]),
]

phase4 = Phase(
    id="phase_4",
    title="Phase 4: Content Machine",
    subtitle="Контент который работает на охват, доверие, продажу",
    icon="🚀",
    color="#6C5CE7",
    goal="Система, а не случайный постинг",
    outcome="30 Reels сценариев + 10 каруселей + план 30 дней + HeyGen видео",
    subphases=[
        SubPhase(id="4_1_strategy", title="4.1 Стратегия и рубрики", goal="Закрыть все этапы воронки", problems_before=["Только экспертный контент", "Нет охватных"], improvements=["Матрица 4x4: охват, триггер, эксперт, продажа x 4 рубрики"], tasks=make_tasks("4_1", [("Рубрики 4-6", ""), ("Соотношение 50/30/20", "охват/доверие/продажа")]), agents=["content_strategist"], artifacts=["13_content_strategy.md"]),
        SubPhase(id="4_2_production", title="4.2 Производство сценариев", goal="Быстро делать контент", problems_before=["Долго думать над каждым Reels"], improvements=["HeyGen аватары + автосубтитры + шаблоны"], tasks=make_tasks("4_2", [("30 Reels хуков", ""), ("10 каруселей", ""), ("CTA банк", "20 призывов")]), agents=["reels_factory", "carousel_factory"], artifacts=["14_reels_30.md"]),
        SubPhase(id="4_3_plan", title="4.3 План публикаций", goal="Дисциплина", problems_before=["Постят когда вспомнят"], improvements=["Календарь с привязкой к воронкам и продуктам"], tasks=make_tasks("4_3", [("Календарь 30 дней", ""), ("Автоперепосты TG-YT Shorts-IG", "")]), agents=["editorial_planner"], artifacts=["16_editorial.md"]),
    ],
    agents=phase4_agents
)

# Phase 5: Lead System
phase5_agents = [
    AgentManifest(id="lead_magnet_architect", name="Lead Magnet Architect", icon="🧲", phase_id="phase_5", role="Магниты", description="3-5 лид-магнитов под каждый ICP", inputs_required=["icp", "content_strategy"], outputs_produced=["17_lead_magnets.md"], dependencies=[], tasks=["Идеи магнитов", "Структура"], human_checkpoints=["Выбрать 1-2 магнита"]),
    AgentManifest(id="landing_builder", name="Landing Builder", icon="🌐", phase_id="phase_5", role="Ленд/бот", description="Структура бота, квиз, лендос", inputs_required=["lead_magnets"], outputs_produced=["18_landing_structure.md"], dependencies=["lead_magnet_architect"], tasks=["Квиз", "Бот сценарий"], human_checkpoints=[]),
    AgentManifest(id="crm_integrator", name="CRM Integrator", icon="🔗", phase_id="phase_5", role="CRM и автоматизация", description="n8n/Make схема, теги, пайплайн", inputs_required=["landing_structure"], outputs_produced=["19_crm_schema.md", "19_automation.json"], dependencies=["landing_builder"], tasks=["Схема автоматизации", "Интеграция"], human_checkpoints=[]),
]

phase5 = Phase(
    id="phase_5",
    title="Phase 5: Lead System",
    subtitle="Трафик → лид → база",
    icon="🧲",
    color="#00B894",
    goal="Автосбор базы без твоего участия",
    outcome="Лид-магнит + воронка + CRM + ежедневные лиды",
    subphases=[
        SubPhase(id="5_1_magnet", title="5.1 Магниты", goal="Дать ценность за контакт", problems_before=["Подпишись просто"], improvements=["Квиз-магнит + проверка за 2 мин + pdf с результатом"], tasks=make_tasks("5_1", [("3 идеи магнитов", ""), ("Один в работу", "")]), agents=["lead_magnet_architect"], artifacts=["17_lead_magnets.md"]),
        SubPhase(id="5_2_funnel", title="5.2 Воронка захвата", goal="Конверсия 35-60%", problems_before=["Нет воронки"], improvements=["Bot + ленд + автопроверка"], tasks=make_tasks("5_2", [("Сценарий бота Manychat/Salebot", ""), ("Квиз", "")]), agents=["landing_builder"], artifacts=["18_landing_structure.md"]),
        SubPhase(id="5_3_crm", title="5.3 CRM", goal="Все лиды на учете", problems_before=["Лиды в личке теряются"], improvements=["Автотеги + напоминания + дашборд"], tasks=make_tasks("5_3", [("Пайплайн лидов", ""), ("Автоответы", "")]), agents=["crm_integrator"], artifacts=["19_crm_schema.md"]),
    ],
    agents=phase5_agents
)

# Phase 6: Funnel & Content Automation
phase6_agents = [
    AgentManifest(id="autowarmup", name="AutoWarmup Engine", icon="🔥", phase_id="phase_6", role="Прогревная воронка", description="7-дневный автопрогрев в боте/email/Reels", inputs_required=["brand_manifest", "stories_bank"], outputs_produced=["20_warmup_7days.md"], dependencies=[], tasks=["Сторителлинг на 7 дней"], human_checkpoints=["Утвердить тон прогрева"]),
    AgentManifest(id="heygen_video_factory", name="HeyGen Video Factory", icon="🎥", phase_id="phase_6", role="Видео-аватары", description="Генерит говорящие аватары из фото + сценарии, для Reels, сторис, воронки", inputs_required=["reels_30", "photo"], outputs_produced=["21_heygen_videos.json", "avatar_videos"], dependencies=["autowarmup"], tasks=["Генерация через HeyGen API", "Субтитры", "Рендер"], human_checkpoints=["Выбрать аватар"]),
    AgentManifest(id="dm_automation", name="DM Automation", icon="💬", phase_id="phase_6", role="Автоворонки в директ", description="Триггеры: коммент слово, ответ на сторис, реакция", inputs_required=["warmup_7days"], outputs_produced=["22_dm_flows.json", "22_triggers.md"], dependencies=["autowarmup"], tasks=["Слова-триггеры", "Автоответы", "Сегментация"], human_checkpoints=[]),
]

phase6 = Phase(
    id="phase_6",
    title="Phase 6: Funnel & Distribution",
    subtitle="Контент и прогрев на автомате, HeyGen аватары",
    icon="⚡",
    color="#0984E3",
    goal="Автозапуск контента и прогревов",
    outcome="Автоворонки + 10 HeyGen видео + DM автоматизация",
    subphases=[
        SubPhase(id="6_1_warmup", title="6.1 Автопрогрев 7 дней", goal="Доверие без твоего участия", problems_before=["Греют вручную в сторис"], improvements=["Серия 7 писем/сообщений + 7 Reels из банка"], tasks=make_tasks("6_1", [("Storyline 7 дней", ""), ("CTA каждого дня", "")]), agents=["autowarmup"], artifacts=["20_warmup_7days.md"]),
        SubPhase(id="6_2_heyg_avatar", title="6.2 HeyGen фабрика", goal="Видео без съемок", problems_before=["Нет времени снимать"], improvements=["Фото → говорящий аватар с липсинком, интеграция с нашим репо"], tasks=make_tasks("6_2", [("Фото эксперта", "Загрузить"), ("10 видео из сценариев", "Сгенерить"), ("Автосабы", "")]), agents=["heygen_video_factory"], artifacts=["21_heygen_videos.json"]),
        SubPhase(id="6_3_dm", title="6.3 DM триггеры", goal="Автоответы на комментарии и реакции", problems_before=["Потеря лидов из комментов"], improvements=["ManyChat / Salebot триггер по слову"], tasks=make_tasks("6_3", [("Триггер-слова", "Напиши ГАЙД, РАЗБОР и тд"), ("Флоу", "")]), agents=["dm_automation"], artifacts=["22_dm_flows.json"]),
    ],
    agents=phase6_agents
)

# Phase 7: Sales OS
phase7_agents = [
    AgentManifest(id="sales_script", name="Sales Script Master", icon="📞", phase_id="phase_7", role="Скрипты продаж", description="DM скрипты, созвон, оффер в переписке", inputs_required=["icp", "offer_ladder", "objections"], outputs_produced=["23_sales_scripts.md", "23_close_templates.md"], dependencies=[], tasks=["Скрипт DM", "Скрипт созвона", "Закрытие возражений"], human_checkpoints=["Протестить на 3 лидах"]),
    AgentManifest(id="webinar_auto", name="Webinar Automator", icon="🎙️", phase_id="phase_7", role="Автовебинар / эфир", description="Структура веба + автопродажи", inputs_required=["mechanism", "proof_board"], outputs_produced=["24_webinar_plan.md"], dependencies=["sales_script"], tasks=["Структура веба", "Оффер слайд"], human_checkpoints=[]),
    AgentManifest(id="scale_ops", name="Scale Ops", icon="📈", phase_id="phase_7", role="Делегирование и масштаб", description="Команда, KPI, дашборд", inputs_required=["editorial_plan", "crm_schema"], outputs_produced=["25_kpi_dashboard.md", "25_hiring_plan.md"], dependencies=["webinar_auto"], tasks=["KPI дашборд", "Кто нужен в команду"], human_checkpoints=["Утвердить план масштаба"]),
]

phase7 = Phase(
    id="phase_7",
    title="Phase 7: Sales OS & Scale",
    subtitle="Продажи на автомате и команда",
    icon="💵",
    color="#E17055",
    goal="Система закрывает без тебя 24/7",
    outcome="Скрипты + автовеб + KPI + план команды",
    subphases=[
        SubPhase(id="7_1_sales", title="7.1 Скрипты закрытия", goal="Конверсия 20-40% в продажу", problems_before=["Продают в лоб", "Боятся продаж"], tasks=make_tasks("7_1", [("DM скрипт", ""), ("Созвон 30 мин", ""), ("Отработка возражений", "")]), agents=["sales_script"], artifacts=["23_sales_scripts.md"]),
        SubPhase(id="7_2_auto", title="7.2 Автовеб и трипваеры", goal="Продажи без созвонов", problems_before=["Только ручные продажи"], improvements=["Автовеб каждые 2 дня + трипваер"], tasks=make_tasks("7_2", [("Автовеб 60 мин", ""), ("Письма после", "")]), agents=["webinar_auto"], artifacts=["24_webinar_plan.md"]),
        SubPhase(id="7_3_scale", title="7.3 Масштаб", goal="Выйти из операционки", problems_before=["Все на себе"], improvements=["Дашборд + роли"], tasks=make_tasks("7_3", [("KPI", "Лиды, конверсия, выручка"), ("Команда", "Контент, трафик, продажи")]), agents=["scale_ops"], artifacts=["25_kpi_dashboard.md"]),
    ],
    agents=phase7_agents
)

PHASES = [phase1, phase2, phase3, phase4, phase5, phase6, phase7]

ALL_AGENTS = {}
for p in PHASES:
    for a in p.agents:
        ALL_AGENTS[a.id] = a

def get_phase(phase_id: str):
    for p in PHASES:
        if p.id == phase_id:
            return p
    return None

def get_agent(agent_id: str):
    return ALL_AGENTS.get(agent_id)
