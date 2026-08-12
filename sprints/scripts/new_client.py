#!/usr/bin/env python3
"""Заводит рабочую папку клиента со всеми 10 шаблонами конвейера
и файлом статуса, чтобы отслеживать прогресс по спринтам.

Использование:
    python sprints/scripts/new_client.py "Имя_Клиента"
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"
DELIVERABLES_DIR = ROOT / "deliverables"

SPRINTS = [
    ("01", "dosye_eksperta", "Досье эксперта", "autoexpert-profile.com"),
    ("02", "karta_rynka", "Карта рынка", "marketmap.ai"),
    ("03", "pozicionirovanie", "Стратегия позиционирования", "positioning.pro"),
    ("04", "skriptbook_bot", "Скриптбук Telegram-бота", "botscripts.ru"),
    ("05", "test_dialogov", "Тестирование диалогов", "bottest.ai"),
    ("06", "kontent_plan", "Контент-стратегия на 30 дней", "contentplan.pro"),
    ("07", "reels_scripts", "Сценарии Reels", "reelscripts.io"),
    ("08", "visual_pack", "Визуальный пакет", "visualpack.design"),
    ("09", "production_pack", "Production Pack", "productionpack.video"),
    ("10", "publish_pack", "Publishing Pack", "publishpack.io"),
]


def build_status_md(client: str) -> str:
    rows = "\n".join(
        f"| {n} | {title} | {domain} | ⬜ не начат | |"
        for n, _, title, domain in SPRINTS
    )
    return f"""# 📊 Статус конвейера — {client}
Создано: {date.today().isoformat()}

Отмечайте статус: ⬜ не начат · 🔵 в работе · ✅ сдан клиенту

| № | Спринт | Домен | Статус | Дата сдачи |
|---|--------|-------|--------|------------|
{rows}

> Правило конвейера: нельзя начинать спринт, если не закрыт (✅) хотя бы один
> из его обязательных входов — см. колонку «Вход» в `../SPRINTS.md`.
"""


def main() -> None:
    if len(sys.argv) != 2:
        print("Использование: python new_client.py \"Имя_Клиента\"")
        sys.exit(1)

    client = sys.argv[1].strip()
    safe_name = "_".join(client.split())
    client_dir = DELIVERABLES_DIR / safe_name

    if client_dir.exists():
        print(f"Папка уже существует: {client_dir}")
        sys.exit(1)

    client_dir.mkdir(parents=True)

    for num, slug, _title, _domain in SPRINTS:
        src = TEMPLATES_DIR / f"{num}_{slug}.md"
        dst = client_dir / f"{num}_{slug}.md"
        if src.exists():
            shutil.copy(src, dst)
        else:
            print(f"⚠️  Шаблон не найден: {src}")

    (client_dir / "00_STATUS.md").write_text(build_status_md(client), encoding="utf-8")

    print(f"✅ Клиент создан: {client_dir}")
    print("   Начните с 00_STATUS.md, затем 01_dosye_eksperta.md")


if __name__ == "__main__":
    main()
