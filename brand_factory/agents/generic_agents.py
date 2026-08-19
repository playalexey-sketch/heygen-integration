"""
Generic stub agents for other phases - they reuse base but produce template MDs
Allows full factory to be visible even if phase1 is the only fully implemented.
"""
from .base import BaseAgent
from ..storage import add_artifact
from typing import List

def make_stub_agent(agent_id, filename, title, content_template):
    class StubAgent(BaseAgent):
        id = agent_id
        def run(self, project, context):
            content = content_template.format(
                niche=project.input.niche or "эксперты",
                expert_name=project.input.expert_name or "Эксперт",
                project_name=project.name,
                agent_id=self.id
            )
            art = add_artifact(project.id, filename, content, self.id, title)
            return [art]
    StubAgent.__name__ = f"{agent_id}_agent"
    return StubAgent

# Phase2
OfferArchitect = make_stub_agent(
    "offer_architect",
    "08_offer_ladder.md",
    "Лестница продуктов",
    """# Offer Ladder — {project_name} / {niche}

## Лестница 4 уровня
1. **Free — Lead Magnet:** Квиз "Где ты сливаешь лидов?" + pdf результат
2. **Tripwire 990р:** Набор из 30 Reels хуков + 5 DM шаблонов
3. **Core 35k:** AUTO-EXPERT OS 14 дней: бренд + контент + лиды
4. **High 150k:** Наставничество 8 недель + HeyGen фабрика под ключ

## Юнит-экономика
- Цель 300k/мес: 6 продаж Core = 210k + 3 Tripwire апсел + 1 High
- CAC через Reels + DM триггеры ≈ 0, органика

## Что в каждом продукте (для следующей фазы)
...
"""
)

MechanismCreator = make_stub_agent(
    "mechanism_creator",
    "09_mechanism.md",
    "Механизм",
    """# Механизм {expert_name} — AUTO-EXPERT OS
## Название метода
AUTO-EXPERT OS

## 3 столпа
1. BRAND DNA (2 дня) -> позиционирование, ICP, proof
2. CONTENT FACTORY (3 дня) -> 30 Reels + HeyGen + план
3. LEAD & SALE ENGINE (7 дней) -> магнит + DM + прогрев + скрипты

## Почему работает
Система закрывает все дыры: если нет позиционирования - не покупают, если нет контента - нет охвата, если нет лидов - нет продаж.
"""
)

GuaranteeCopy = make_stub_agent(
    "guarantee_creator",
    "10_guarantee.md",
    "Гарантии",
    """# Гарантии
- Сделаешь по чек-листу 7 дней -> 3 лида или возвращаю
- Личный разбор если не получилось
"""
)

# Phase3
VisualDirector = make_stub_agent(
    "visual_director",
    "11_visual_board.md",
    "Visual Board",
    """# Visual Board — {project_name}
## Палитра
- Primary #FF6B6B (акцент)
- Dark #0F1420 (фон)
- Light #FFFFFF
- Secondary #4ECDC4

## Шрифты
- Заголовки: Inter Bold 700
- Тело: Inter Regular

## Мудборд
- Минимализм, воздух, процесс, скринкасты системы
- Референсы: @... 

## ТЗ на дизайнера
- Хайлайты 6 шт обложки
- Шаблоны каруселей 3 шт
"""
)

ProfileOptimizer = make_stub_agent(
    "profile_optimizer",
    "12_profile_pack.md",
    "Упаковка профилей",
    """# Profile Pack
## Instagram Bio (5 вариантов)
1. Система лидов для экспертов → 5-15 заявок/нед без плясок | AUTO-EXPERT OS 👇 Квиз где сливаешь лидов
...

## Highlights
- Кейсы | Система | Метод | Отзывы | HeyGen | Обучение

## Аватар
Живое фото, без очков, плечи, улыбка, фон темный
"""
)

# Phase4
ContentStrategist = make_stub_agent(
    "content_strategist",
    "13_content_strategy.md",
    "Контент стратегия",
    """# Content Strategy — {niche}
## Рубрики
1. Охватные (50%): Разоблачения, Мифы, Тренды, Реакции
2. Доверие (30%): Кейсы, Закулисье, Метод, Провалы
3. Продажи (20%): Оффер, Возможность, Сравнение

## Соотношение
Пн охват, Вт доверие, Ср охват, Чт продажи, Пт охват...
"""
)

ReelsFactory = make_stub_agent(
    "reels_factory",
    "14_reels_30.md",
    "30 Reels",
    """# 30 Reels идей — {project_name}
1. Hook: "90% экспертов делают эту ошибку и остаются без лидов" ...
2. Hook: "Как я делаю контент за 2ч в неделю с HeyGen" ...
...
30 идей, каждая с хуком 3с + сценарий + CTA "Пиши ГАЙД"
"""
)

CarouselFactory = make_stub_agent(
    "carousel_factory",
    "15_carousels.md",
    "Карусели",
    """# 10 Каруселей
1. Карусель "3 дыры где ты теряешь лидов"
...
"""
)

EditorialPlanner = make_stub_agent(
    "editorial_planner",
    "16_editorial.md",
    "Эдиториал 30 дней",
    """# Editorial 30 days
| День | Формат | Тема | CTA | Воронка |
| 1 | Reels | Разоблачение | Пиши ГАЙД | Lead |
...
"""
)

# Phase5-7 stubs
LeadMagnetArchitect = make_stub_agent("lead_magnet_architect", "17_lead_magnets.md", "Лид-магниты", "# Lead Magnets\n- Квиз\n- Чек-лист\n- Гайд")
LandingBuilder = make_stub_agent("landing_builder", "18_landing_structure.md", "Ленд", "# Landing \nбот структура")
CRMIntegrator = make_stub_agent("crm_integrator", "19_crm_schema.md", "CRM", "# CRM Schema\nn8n flow")

AutoWarmup = make_stub_agent("autowarmup", "20_warmup_7days.md", "Прогрев 7 дней", "# Warmup 7 days\nДень1-7")
HeygenFactory = make_stub_agent("heygen_video_factory", "21_heygen_videos.json", "HeyGen Видео", '{ "videos": [{"script": "30 Reels идея", "status": "queued"}] }')
DMAutomation = make_stub_agent("dm_automation", "22_dm_flows.json", "DM Flows", '{ "triggers": ["ГАЙД","РАЗБОР"] }')

SalesScript = make_stub_agent("sales_script", "23_sales_scripts.md", "Sales Scripts", "# Sales Scripts\nDM + созвон")
WebinarAuto = make_stub_agent("webinar_auto", "24_webinar_plan.md", "Вебинар", "# Webinar 60 мин структура")
ScaleOps = make_stub_agent("scale_ops", "25_kpi_dashboard.md", "KPI Dashboard", "# KPI\nЛиды, конверсия, выручка")

STUB_AGENTS = {
    "offer_architect": OfferArchitect,
    "mechanism_creator": MechanismCreator,
    "guarantee_copy": GuaranteeCopy,
    "visual_director": VisualDirector,
    "profile_optimizer": ProfileOptimizer,
    "content_strategist": ContentStrategist,
    "reels_factory": ReelsFactory,
    "carousel_factory": CarouselFactory,
    "editorial_planner": EditorialPlanner,
    "lead_magnet_architect": LeadMagnetArchitect,
    "landing_builder": LandingBuilder,
    "crm_integrator": CRMIntegrator,
    "autowarmup": AutoWarmup,
    "heygen_video_factory": HeygenFactory,
    "dm_automation": DMAutomation,
    "sales_script": SalesScript,
    "webinar_auto": WebinarAuto,
    "scale_ops": ScaleOps,
}
