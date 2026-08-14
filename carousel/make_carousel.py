# -*- coding: utf-8 -*-
"""Генератор карусели «Ты следующий?» — 8 слайдов 1080x1350."""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1080, 1350
MARGIN = 96
FDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bg")
os.makedirs(OUT, exist_ok=True)

GOLD = (214, 175, 106)
GOLD_BRIGHT = (240, 205, 140)
WHITE = (245, 242, 236)
GREY = (176, 172, 165)


def font(name, size):
    return ImageFont.truetype(os.path.join(FDIR, name), size)


def F_BOLD(s):
    return font("Roboto-Bold.ttf", s)


def F_XBOLD(s):
    return font("Roboto-Black.ttf", s)


def F_REG(s):
    return font("Roboto-Regular.ttf", s)


def F_SEMI(s):
    return font("Roboto-Medium.ttf", s)


# ---------------------------------------------------------------- background
def make_bg(path, darken=0.62, blur=2):
    im = Image.open(path).convert("RGB")
    # cover-crop to 1080x1350
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 1), int(im.height * r + 1)), Image.LANCZOS)
    x = (im.width - W) // 2
    y = (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(darken)
    # центральное затемнение под текст
    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, H], fill=90)
    veil = Image.new("RGB", (W, H), (6, 8, 14))
    im = Image.composite(veil, im, ov)
    return im


# ---------------------------------------------------------------- text engine
def wrap(draw, text, fnt, maxw):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def glow_text(img, xy, text, fnt, fill, anchor="mm", glow=(0, 0, 0), radius=10):
    """тень/свечение под текстом для читаемости"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=fnt, fill=glow + (200,), anchor=anchor)
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.text(xy, text, font=fnt, fill=fill, anchor=anchor)


# style: (font_file, size, color, line_height, space_after, caps)
STYLES = {
    "h1":    ("Roboto-Black.ttf",   74,  WHITE,       1.14, 34, True),
    "h2":    ("Roboto-Bold.ttf",    58,  WHITE,       1.18, 30, False),
    "gold":  ("Roboto-Bold.ttf",    50,  GOLD_BRIGHT, 1.24, 28, False),
    "body":  ("Roboto-Regular.ttf", 40,  GREY,        1.36, 26, False),
    "bodyw": ("Roboto-Medium.ttf",  42,  WHITE,       1.32, 26, False),
    "small": ("Roboto-Regular.ttf", 32,  GREY,        1.36, 20, False),
    "cta":   ("Roboto-Black.ttf",   64,  WHITE,       1.16, 30, True),
    "zero":  ("Roboto-Black.ttf",  150,  GOLD_BRIGHT, 1.05, 22, False),
    "rule":  (None,                  0,  GOLD,        1.0,  34, False),
}


def layout(blocks, maxw, scale=1.0):
    """Разбивает блоки на строки и считает общую высоту."""
    tmp = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(tmp)
    prepared, total = [], 0
    for i, (style, text) in enumerate(blocks):
        fname, size, color, lh, sp, caps = STYLES[style]
        sp = int(sp * scale)
        if style == "rule":
            prepared.append((style, None, color, 0, ["-"]))
            total += 4 + sp
            continue
        fsize = max(20, int(size * scale))
        fnt = font(fname, fsize)
        t = text.upper() if caps else text
        lines = []
        for para in t.split("\n"):
            lines += wrap(d, para, fnt, maxw) if para.strip() else [""]
        step = int(fsize * lh)
        prepared.append((style, fnt, color, step, lines))
        total += step * len(lines) + sp
    return prepared, total


def render(idx, bgfile, blocks, tag=None, darken=0.55):
    base = make_bg(os.path.join(BG, bgfile), darken=darken).convert("RGBA")
    maxw = W - 2 * MARGIN
    avail = H - 2 * 150  # безопасная зона по вертикали

    scale = 1.0
    prepared, total = layout(blocks, maxw, scale)
    while total > avail and scale > 0.55:
        scale -= 0.03
        prepared, total = layout(blocks, maxw, scale)

    y = (H - total) / 2 + 20

    d = ImageDraw.Draw(base)
    d.text((MARGIN, 76), f"{idx:02d}", font=F_BOLD(28), fill=GOLD, anchor="lm")
    d.line([(MARGIN + 46, 76), (MARGIN + 104, 76)], fill=GOLD, width=2)
    if tag:
        d.text((MARGIN + 122, 78), tag.upper(), font=F_SEMI(23),
               fill=(150, 140, 122), anchor="lm")

    for style, fnt, color, step, lines in prepared:
        sp = int(STYLES[style][4] * scale)
        if style == "rule":
            cy = int(y + 2)
            ImageDraw.Draw(base).line([(W / 2 - 70, cy), (W / 2 + 70, cy)],
                                      fill=GOLD, width=3)
            y += 4 + sp
            continue
        for ln in lines:
            if ln:
                glow_text(base, (W / 2, y + step / 2), ln, fnt, color,
                          anchor="mm", glow=(0, 0, 0), radius=12)
            y += step
        y += sp

    d = ImageDraw.Draw(base)
    foot = "СВАЙПАЙ ДАЛЬШЕ" if idx < 8 else "ЖДУ ТВОЮ 0 В ДИРЕКТЕ"
    d.text((W / 2, H - 64), foot, font=F_SEMI(25), fill=(142, 132, 116), anchor="mm")

    path = os.path.join(OUT, f"slide_{idx}.png")
    base.convert("RGB").save(path, quality=95)
    print("saved", path)


# ---------------------------------------------------------------- slides
SLIDES = [
    (1, "bg1.png", "хук", [
        ("h1", "Ты уже\nзаметил?"),
        ("rule", ""),
        ("bodyw", "В твоём Роду"),
        ("gold", "всё повторяется по кругу."),
        ("body", "Одни и те же сценарии.\nОдни и те же проблемы.\nОдни и те же судьбы."),
        ("h2", "А если следующий — ты?"),
    ]),
    (2, "bg2.png", "узнавание", [
        ("h2", "Посмотри внимательно\nна свой Род."),
        ("rule", ""),
        ("body", "Женщины снова оказываются\nс мужчинами, которые пьют."),
        ("body", "Мужчины зарабатывают —\nи снова теряют деньги."),
        ("body", "Разводы повторяются."),
        ("body", "Кредиты передаются\nиз одного этапа жизни в другой."),
        ("body", "Болезни появляются\nслишком рано."),
        ("gold", "Совпадение? Или сценарий,\nкоторый никто не остановил?"),
    ]),
    (3, "bg1.png", "раскачивание", [
        ("h2", "А теперь представь:\nты ничего не меняешь."),
        ("rule", ""),
        ("body", "Проходит 10 лет.\nТы продолжаешь жить\nпо привычной схеме."),
        ("body", "Твои дети наблюдают это.\nИ однажды замечаешь:"),
        ("gold", "твоя дочь повторяет тебя.\nтвой сын повторяет отца."),
        ("body", "Не потому что они этого хотят.\nА потому что именно это\nони видели как норму."),
    ]),
    (4, "bg2.png", "цена бездействия", [
        ("h2", "То, что не осознанно тобой,\nможет повторяться\nснова и снова."),
        ("rule", ""),
        ("body", "Сценарии отношений.\nОтношение к деньгам.\nСтрах перемен.\nЧувство вины.\nЖизнь «через усилие»."),
        ("bodyw", "И самое страшное:"),
        ("gold", "ты можешь передать дальше\nто, от чего сам хотел избавиться."),
        ("body", "Пока кто-то не решит\nостановить этот круг."),
    ]),
    (5, "bg1.png", "поворот", [
        ("h2", "Этим человеком\nможешь стать ты."),
        ("rule", ""),
        ("body", "Не для того, чтобы «спасти весь Род».\nА для того, чтобы"),
        ("gold", "начать менять свою часть истории."),
        ("bodyw", "Разобраться:"),
        ("body", "— что именно повторяется;\n— где ты живёшь не своим сценарием;\n— какие финансовые установки держат;\n— что пора перестать нести в будущее."),
        ("gold", "Перемены начинаются\nс одного человека."),
    ]),
    (6, "bg2.png", "что внутри", [
        ("bodyw", "Обряд"),
        ("gold", "«Долги и кредиты —\nкак от них избавиться\nбыстро и навсегда»"),
        ("rule", ""),
        ("body", "В работе ты смотришь\nне только на сам долг. А глубже:"),
        ("bodyw", "что стоит за отношением\nк деньгам и обязательствам."),
        ("body", "Что ты повторяешь.\nЧто удерживает тебя\nв привычном сценарии.\nИ что необходимо изменить\nв своей жизни уже сейчас."),
    ]),
    (7, "bg1.png", "формат", [
        ("h1", "Одна\nвстреча"),
        ("rule", ""),
        ("body", "Ты приходишь со своим запросом.\nМы разбираем ситуацию\nи проходим практику."),
        ("body", "Без многолетнего хождения по кругу.\nБез попытки просто\n«перетерпеть ещё немного»."),
        ("gold", "Твоя задача — не только увидеть\nсценарий, но и начать\nдействовать иначе."),
    ]),
    (8, "bg2.png", "действие", [
        ("cta", "Хочешь сдвинуться\nс мёртвой точки?"),
        ("rule", ""),
        ("body", "Напиши мне в директ цифру"),
        ("zero", "0"),
        ("body", "И я пришлю тебе первые 4 шага,\nс которых можно начать разбираться\nс ситуацией с долгами и кредитами."),
        ("gold", "Сейчас доступно 12 мест."),
    ]),
]

for idx, bg, tag, blocks in SLIDES:
    render(idx, bg, blocks, tag=tag, darken=0.5 if bg == "bg1.png" else 0.62)
