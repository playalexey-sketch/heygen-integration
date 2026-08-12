#!/usr/bin/env python3
"""Собирает 10 статических лендингов + витрину index.html из data.py.

Запуск:
    python sprints/site/generate_site.py
"""
from __future__ import annotations

from pathlib import Path

from data import BY_NUM, PRODUCTS

SITE_DIR = Path(__file__).resolve().parent
CSS = (SITE_DIR / "css" / "style.css").read_text(encoding="utf-8")

PAGE_TMPL = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} — Спринт {num} · {domain}</title>
<meta name="description" content="{hero}">
<style>
__CSS__
</style>
</head>
<body>
<div class="container">
  <nav class="nav">
    <div class="logo">AI-конвейер <span>«Личный бренд»</span></div>
    <a class="back" href="index.html">← Все 10 продуктов</a>
  </nav>

  <div class="hero">
    <div class="badge">Спринт <b>{num}/10</b> · {domain}</div>
    <h1>{hero}</h1>
    <p class="lead">{product_desc}</p>
    <div class="cta-row">
      <a class="btn" href="#order">{cta} — {price}</a>
      <a class="btn secondary" href="../SPRINTS.md">Открыть бэклог спринта</a>
    </div>
    <p class="price-note">Стоимость и сроки — по объёму данных клиента.</p>
  </div>

  <section>
    <h2><span class="num">01</span>Боль клиента</h2>
    <div class="pain">«{pain}»</div>
  </section>

  <section>
    <h2><span class="num">02</span>Что вы получаете (продукт спринта)</h2>
    <div class="product-grid">
      {product_cards}
    </div>
  </section>

  <section>
    <h2><span class="num">03</span>Социальное доказательство</h2>
    <div class="proof">{proof}</div>
  </section>

  <section>
    <h2><span class="num">04</span>Как в этом помогает AI</h2>
    <div class="ai-box">
      <div class="k">AI-инструмент этого спринта</div>
      <p>{ai}</p>
    </div>
  </section>

  <section class="needs">
    <h2><span class="num">05</span>Что нужно от вас, чтобы начать</h2>
    <ul>
      {needs_items}
    </ul>
  </section>

  <section>
    <h2><span class="num">06</span>Место в конвейере из 10 продуктов</h2>
    {deps_in_html}
    {deps_out_html}
  </section>

  <section id="order">
    <h2><span class="num">07</span>Заказать «{name}»</h2>
    <p class="lead" style="font-size:1rem;">Цена: <b>{price}</b>. Напишите нам, приложив то, что указано в разделе «Что нужно от вас» — и мы стартуем спринт.</p>
    <a class="btn" href="mailto:hello@{domain}?subject=Заказ:%20{name}">Написать на hello@{domain}</a>
  </section>

  <footer>
    Продукт {num} из 10 в конвейере «Личный бренд под ключ». Полная карта конвейера и бэклог — в
    <a href="../SPRINTS.md">SPRINTS.md</a>. Домен-заглушка для демонстрации: <b>{domain}</b>.
  </footer>
</div>
</body>
</html>
"""

INDEX_TMPL = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI-конвейер «Личный бренд под ключ» — 10 продуктов, 10 спринтов</title>
<style>
__CSS__
</style>
</head>
<body>
<div class="container">
  <nav class="nav">
    <div class="logo">AI-конвейер <span>«Личный бренд»</span></div>
  </nav>

  <div class="hero">
    <div class="badge">10 спринтов · 10 самостоятельных продуктов</div>
    <h1>От «кто вы» до «работающей контент-машины» — <em>за 10 спринтов</em></h1>
    <p class="lead">Каждый спринт закрывается отдельным продуктом, который можно продать и использовать
    сам по себе. Вместе они образуют полный конвейер упаковки личного бренда: от досье эксперта
    до автопостинга готового контента.</p>
  </div>

  <section>
    <h2>Карта конвейера</h2>
    <div class="product-grid">
      {cards}
    </div>
  </section>

  <footer>
    Мастер-бэклог, чек-листы приёмки и шаблоны продуктов — в <a href="../SPRINTS.md">SPRINTS.md</a> и
    <a href="../templates/">sprints/templates/</a>.
  </footer>
</div>
</body>
</html>
"""


def render_product_page(p: dict) -> str:
    product_cards = "\n      ".join(
        f'<div class="product-card"><div class="k">Входит в продукт</div>{item}</div>'
        for item in p["product_items"]
    )
    needs_items = "\n      ".join(f"<li>{n}</li>" for n in p["needs"])

    deps_in_html = ""
    if p["deps_in"]:
        links = "".join(
            f'<a href="{BY_NUM[d]["slug"]}.html">← {d}. {BY_NUM[d]["name"]}</a>'
            for d in p["deps_in"]
        )
        deps_in_html = f'<p class="lead" style="font-size:.95rem;">Использует результаты:</p><div class="dep">{links}</div>'

    deps_out_html = ""
    if p["deps_out"]:
        links = "".join(
            f'<a href="{BY_NUM[d]["slug"]}.html">{d}. {BY_NUM[d]["name"]} →</a>'
            for d in p["deps_out"]
        )
        deps_out_html = f'<p class="lead" style="font-size:.95rem;margin-top:14px;">Открывает дорогу к:</p><div class="dep">{links}</div>'

    html = PAGE_TMPL.format(
        name=p["name"],
        num=p["num"],
        domain=p["domain"],
        hero=p["hero"],
        pain=p["pain"],
        product_desc=p["product_desc"],
        product_cards=product_cards,
        proof=p["proof"],
        ai=p["ai"],
        needs_items=needs_items,
        deps_in_html=deps_in_html,
        deps_out_html=deps_out_html,
        cta=p["cta"],
        price=p["price"],
    )
    return html.replace("__CSS__", CSS)


def render_index() -> str:
    cards = "\n      ".join(
        f'''<a href="{p["slug"]}.html" style="text-decoration:none;">
          <div class="product-card">
            <div class="k">Спринт {p["num"]} · {p["domain"]}</div>
            <div style="font-weight:800;font-size:1.05rem;margin-bottom:6px;">{p["name"]}</div>
            <div style="color:var(--muted);font-size:.9rem;">{p["product_desc"]}</div>
            <div style="margin-top:10px;color:var(--accent-2);font-weight:700;">{p["price"]} →</div>
          </div>
        </a>'''
        for p in PRODUCTS
    )
    return INDEX_TMPL.format(cards=cards).replace("__CSS__", CSS)


def main() -> None:
    for p in PRODUCTS:
        out = SITE_DIR / f"{p['slug']}.html"
        out.write_text(render_product_page(p), encoding="utf-8")
        print(f"✅ {out.name}")

    (SITE_DIR / "index.html").write_text(render_index(), encoding="utf-8")
    print("✅ index.html")


if __name__ == "__main__":
    main()
