# -*- coding: utf-8 -*-
"""
Движок каруселей — СТАНДАРТ v2.

Правила стандарта (не менять без явного запроса):
  1. Формат 1080x1350 (4:5).
  2. Вверху слева — ТОЛЬКО номер слайда («01»), без тегов и подписей.
  3. Внизу НЕТ никаких подписей («свайпай» и т.п.).
  4. На последнем слайде под основным CTA всегда добавляется
     дополнительный микро-призыв, выбранный СЛУЧАЙНО из ACTION_CTAS
     (подписаться / сохранить / отправить близкому / поставить лайк).
  5. Палитра: чёрно-золотая. Белый = заголовки, золото = ключевая мысль,
     серый = основной текст.
  6. Размер шрифта авто-подгоняется, чтобы текст всегда влезал.

Использование: см. slides_*.py — там только контент + вызов build().
"""
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ------------------------------------------------------------------ константы
W, H = 1080, 1350
MARGIN = 96
SAFE_TOP = 150
SAFE_BOTTOM = 130

ROOT = os.path.dirname(os.path.abspath(__file__))
FDIR = os.path.join(ROOT, "fonts")
BGDIR = os.path.join(ROOT, "bg")

GOLD = (214, 175, 106)
GOLD_BRIGHT = (240, 205, 140)
WHITE = (245, 242, 236)
GREY = (176, 172, 165)

# дополнительные микро-призывы для последнего слайда (выбор случайный)
ACTION_CTAS = [
    "Подпишись, чтобы не потерять.",
    "Сохрани этот пост, чтобы вернуться.",
    "Отправь близкому человеку,\nкоторому это откликнется.",
    "Поставь лайк, если узнал свой Род.",
]


def font(name, size):
    return ImageFont.truetype(os.path.join(FDIR, name), size)


def F_BOLD(s):
    return font("Roboto-Bold.ttf", s)


# --------------------------------------------------------------------- стили
# style: (шрифт, размер, цвет, интерлиньяж, отступ снизу, капс)
STYLES = {
    "h1":     ("Roboto-Black.ttf",   74, WHITE,       1.14, 34, True),
    "h2":     ("Roboto-Bold.ttf",    58, WHITE,       1.18, 30, False),
    "gold":   ("Roboto-Bold.ttf",    50, GOLD_BRIGHT, 1.24, 28, False),
    "body":   ("Roboto-Regular.ttf", 40, GREY,        1.36, 26, False),
    "bodyw":  ("Roboto-Medium.ttf",  42, WHITE,       1.32, 26, False),
    "small":  ("Roboto-Regular.ttf", 32, GREY,        1.36, 20, False),
    "cta":    ("Roboto-Black.ttf",   64, WHITE,       1.16, 30, True),
    "zero":   ("Roboto-Black.ttf",  150, GOLD_BRIGHT, 1.05, 22, False),
    "action": ("Roboto-Medium.ttf",  36, GOLD,        1.30, 20, False),
    "rule":   (None,                  0, GOLD,        1.0,  34, False),
}


# ---------------------------------------------------------------------- фон
def make_bg(path, darken=0.55, blur=2, veil=90):
    im = Image.open(path).convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 1), int(im.height * r + 1)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(darken)
    mask = Image.new("L", (W, H), veil)
    im = Image.composite(Image.new("RGB", (W, H), (6, 8, 14)), im, mask)
    return im


# --------------------------------------------------------------------- текст
def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
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


def glow_text(img, xy, text, fnt, fill, anchor="mm", radius=12):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=(0, 0, 0, 200), anchor=anchor)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def layout(blocks, maxw, scale=1.0):
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    prepared, total = [], 0
    for style, text in blocks:
        fname, size, color, lh, sp, caps = STYLES[style]
        sp = int(sp * scale)
        if style == "rule":
            prepared.append((style, None, color, 0, ["-"]))
            total += 4 + sp
            continue
        fsize = max(18, int(size * scale))
        fnt = font(fname, fsize)
        t = text.upper() if caps else text
        lines = []
        for para in t.split("\n"):
            lines += wrap(d, para, fnt, maxw) if para.strip() else [""]
        step = int(fsize * lh)
        prepared.append((style, fnt, color, step, lines))
        total += step * len(lines) + sp
    return prepared, total


# ------------------------------------------------------------------- рендер
def render_slide(idx, bgfile, blocks, out_path, darken=0.55):
    base = make_bg(os.path.join(BGDIR, bgfile), darken=darken).convert("RGBA")
    maxw = W - 2 * MARGIN
    avail = H - SAFE_TOP - SAFE_BOTTOM

    scale = 1.0
    prepared, total = layout(blocks, maxw, scale)
    while total > avail and scale > 0.5:
        scale -= 0.03
        prepared, total = layout(blocks, maxw, scale)

    y = (H - total) / 2 + 14

    # номер слайда — и больше ничего в шапке
    d = ImageDraw.Draw(base)
    d.text((MARGIN, 76), f"{idx:02d}", font=F_BOLD(30), fill=GOLD, anchor="lm")
    d.line([(MARGIN + 50, 76), (MARGIN + 112, 76)], fill=GOLD, width=2)

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
                glow_text(base, (W / 2, y + step / 2), ln, fnt, color)
            y += step
        y += sp

    base.convert("RGB").save(out_path, quality=95)
    return out_path


def build(slides, outdir, seed=None, action_cta=None):
    """slides: список кортежей (bg_file, blocks, darken|None).
    На последний слайд автоматически добавляется случайный микро-призыв."""
    os.makedirs(outdir, exist_ok=True)
    if seed is not None:
        random.seed(seed)
    chosen = action_cta or random.choice(ACTION_CTAS)

    paths = []
    n = len(slides)
    for i, item in enumerate(slides, start=1):
        bgfile, blocks = item[0], list(item[1])
        darken = item[2] if len(item) > 2 and item[2] else (0.5 if "1" in bgfile else 0.62)
        if i == n:
            blocks = blocks + [("rule", ""), ("action", chosen)]
        p = render_slide(i, bgfile, blocks, os.path.join(outdir, f"slide_{i}.png"), darken)
        paths.append(p)
        print("saved", p)

    # контактный лист
    ims = [Image.open(p).resize((360, 450)) for p in paths]
    cols = 4
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 370 + 10, rows * 460 + 10), (12, 12, 14))
    for i, im in enumerate(ims):
        sheet.paste(im, (10 + (i % cols) * 370, 10 + (i // cols) * 460))
    sheet.save(os.path.join(outdir, "preview_all.jpg"), quality=90)
    print("action CTA:", chosen.replace("\n", " "))
    return paths
