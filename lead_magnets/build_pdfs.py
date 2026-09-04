# -*- coding: utf-8 -*-
"""
Сборка двух PDF-лид-магнитов (автор: Екатерина Сернова).

Дизайн строится на «самодостаточных» flowable-блоках (CompositeBox), которые
рисуются вручную: без таблиц и KeepTogether — это исключает баги ReportLab с
переносом блоков между страницами. Разрывы страниц вычисляются заранее.
"""
import os

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
    PageBreak, Flowable,
)

# ----------------------------------------------------------------------------
# Шрифты (DejaVu — есть кириллица)
# ----------------------------------------------------------------------------
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("Sans",      os.path.join(FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Serif",     os.path.join(FONT_DIR, "DejaVuSerif.ttf")))
pdfmetrics.registerFont(TTFont("Serif-Bold", os.path.join(FONT_DIR, "DejaVuSerif-Bold.ttf")))

SANS_A = pdfmetrics.getAscent("Sans-Bold") / 2048.0
SANS_D = -pdfmetrics.getDescent("Sans-Bold") / 2048.0

# ----------------------------------------------------------------------------
# Палитра
# ----------------------------------------------------------------------------
DEEP    = HexColor("#1E4631")
ACCENT  = HexColor("#6F9F45")
SAND    = HexColor("#F6F1E5")
CARDBG  = HexColor("#F1F6EC")
CARDBAR = HexColor("#4C7B3F")
TIPBG   = HexColor("#E7EFDC")
GOLD    = HexColor("#C9A24B")
INK     = HexColor("#26291F")
MUTED   = HexColor("#62695B")
LINEC   = HexColor("#DCE4D2")
WHITE   = colors.white
TERRA   = HexColor("#B4552F")
TERRABG = HexColor("#FBEFE8")
TERRACB = HexColor("#C96A41")
SOFT    = HexColor("#8A9283")

BUTTON_URL = "https://telegram.me/EkaterinaGarden_bot"
BOT_HANDLE = "@EkaterinaGarden_bot"

PAGE_W, PAGE_H = A4
MARGIN = 50
CW = PAGE_W - 2 * MARGIN      # ширина контента
FRAME_TOP = 42
FRAME_BOTTOM = 64
FRAME_H = PAGE_H - FRAME_TOP - FRAME_BOTTOM
FRAME_Y0 = FRAME_BOTTOM


# ----------------------------------------------------------------------------
# Кастомные flowables
# ----------------------------------------------------------------------------

class CompositeBox(Flowable):
    """Атомарный блок с фоном, полосой слева/сверху и параграфами внутри."""

    def __init__(self, paras, *, width=CW, bg=None, bar=None, top=None,
                 pad=(12, 15, 12, 14), radius=0):
        super().__init__()
        self.paras = paras
        self.W = width
        self.bg = bg
        self.bar = bar
        self.top = top
        self.padT, self.padL, self.padB, self.padR = pad
        self.radius = radius

    def wrap(self, availWidth, availHeight):
        iw = self.W - self.padL - self.padR
        self._items = []
        y = 0.0
        for i, p in enumerate(self.paras):
            _, h = p.wrap(iw, 100000)
            sep = getattr(p.style, "spaceAfter", 0) if i < len(self.paras) - 1 else 0
            self._items.append((p, h, sep))
            y += h + sep
        self.H = y + self.padT + self.padB
        if self.top:
            self.H += self.top[0]
        return (self.W, self.H)

    def draw(self):
        c = self.canv
        c.saveState()
        if self.bg is not None:
            c.setFillColor(self.bg)
            if self.radius:
                c.roundRect(0, 0, self.W, self.H, self.radius, stroke=0, fill=1)
            else:
                c.rect(0, 0, self.W, self.H, stroke=0, fill=1)
        top_h = 0
        if self.top:
            th, col = self.top
            top_h = th
            c.setFillColor(col)
            c.rect(0, self.H - th, self.W, th, stroke=0, fill=1)
        if self.bar:
            bw, col = self.bar
            c.setFillColor(col)
            c.rect(0, 0, bw, self.H, stroke=0, fill=1)
        y = self.H - self.padT - top_h
        for p, h, sep in self._items:
            p.drawOn(c, self.padL, y - h)
            y -= h + sep
        c.restoreState()


class TitleBand(Flowable):
    """Полноширинная «шапка» первой страницы."""

    def __init__(self, lines, band_color=DEEP, height=None):
        super().__init__()
        self.lines = lines
        self.band_color = band_color
        total = 44
        for _, _, size, _, sp in lines:
            total += size * 1.26 + sp
        self._h = height or max(150, total + 26)

    def wrap(self, availWidth, availHeight):
        return (availWidth, self._h)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.band_color)
        c.rect(-MARGIN, 0, PAGE_W, self._h, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.rect(-MARGIN, 0, PAGE_W, 3, stroke=0, fill=1)
        cx = CW / 2.0
        y = self._h - 38
        for text, font, size, color, sp in self.lines:
            y -= sp
            c.setFont(font, size)
            c.setFillColor(color)
            c.drawCentredString(cx, y - size * 0.8, text)
            y -= size * 1.26
        c.restoreState()


class Divider(Flowable):
    """Линия — точка — линия."""

    def __init__(self, color=ACCENT, width=220, thickness=1.1):
        super().__init__()
        self.color = color
        self.width = width
        self.thick = thickness

    def wrap(self, availWidth, availHeight):
        return (self.width, 16)

    def draw(self):
        c = self.canv
        c.saveState()
        half = (self.width - 12) / 2.0
        cy = 8
        c.setStrokeColor(self.color)
        c.setLineWidth(self.thick)
        c.line(0, cy, half, cy)
        c.line(self.width - half, cy, self.width, cy)
        c.setFillColor(self.color)
        c.circle(self.width / 2.0, cy, 3.4, stroke=0, fill=1)
        c.restoreState()


class LinkButton(Flowable):
    """Кликабельная кнопка: вся область — аннотация-ссылка."""

    def __init__(self, label, url=BUTTON_URL, width=330, height=62,
                 bg=DEEP, fg=WHITE, size=15.5, radius=12):
        super().__init__()
        self.label = label
        self.url = url
        self.w = width
        self.h = height
        self.bg = bg
        self.fg = fg
        self.size = size
        self.radius = radius

    def wrap(self, availWidth, availHeight):
        self._aw = availWidth
        return (availWidth, self.h)

    def draw(self):
        c = self.canv
        c.saveState()
        w = min(self.w, self._aw - 30)
        x = (self._aw - w) / 2.0
        c.setFillColor(self.bg)
        c.roundRect(x, 0, w, self.h, self.radius, stroke=0, fill=1)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.15))
        c.roundRect(x + 6, self.h - 14, w - 12, 8, 4, stroke=0, fill=1)
        c.linkURL(self.url, (x, 0, x + w, self.h), relative=1, thickness=0)
        size = self.size
        while pdfmetrics.stringWidth(self.label, "Sans-Bold", size) > w - 40 and size > 10:
            size -= 0.5
        c.setFont("Sans-Bold", size)
        c.setFillColor(self.fg)
        baseline = self.h / 2.0 - (SANS_A - SANS_D) * size / 2.0
        c.drawCentredString(x + w / 2.0, baseline, self.label)
        c.restoreState()


def footer(canv, doc, title):
    canv.saveState()
    canv.setStrokeColor(LINEC)
    canv.setLineWidth(0.7)
    y = 40
    canv.line(MARGIN, y, PAGE_W - MARGIN, y)
    canv.setFont("Sans", 8)
    canv.setFillColor(SOFT)
    canv.drawString(MARGIN, y - 14, title)
    canv.drawRightString(PAGE_W - MARGIN, y - 14, f"стр. {canv.getPageNumber()}")
    canv.restoreState()


# ----------------------------------------------------------------------------
# Стили
# ----------------------------------------------------------------------------

def styles_for(palette):
    st = {}
    st["intro"] = ParagraphStyle(
        "intro", fontName="Sans", fontSize=10.6, leading=16.6,
        textColor=INK, alignment=TA_JUSTIFY)
    st["body"] = ParagraphStyle(
        "body", fontName="Sans", fontSize=10.2, leading=15.4,
        textColor=INK, alignment=TA_JUSTIFY, spaceAfter=3)
    st["li"] = ParagraphStyle(
        "li", fontName="Sans", fontSize=10.1, leading=14.9,
        textColor=INK, alignment=TA_JUSTIFY,
        leftIndent=16, bulletIndent=2, spaceAfter=2.5,
        bulletFontName="Sans", bulletFontSize=9.4)
    st["card_title"] = ParagraphStyle(
        "card_title", fontName="Serif-Bold", fontSize=13.6, leading=17.5,
        textColor=INK, spaceAfter=6)
    st["tip"] = ParagraphStyle(
        "tip", fontName="Sans", fontSize=9.7, leading=14.4,
        textColor=INK, alignment=TA_JUSTIFY,
        backColor=TIPBG, borderPadding=7, spaceBefore=4)
    st["panel_h"] = ParagraphStyle(
        "panel_h", fontName="Serif-Bold", fontSize=14.5, leading=19,
        textColor=DEEP, spaceAfter=7)
    st["check"] = ParagraphStyle(
        "check", fontName="Sans", fontSize=10.1, leading=15.2,
        textColor=INK, leftIndent=18, bulletIndent=0, spaceAfter=3.5,
        bulletFontName="Sans", bulletFontSize=10)
    st["cta_h"] = ParagraphStyle(
        "cta_h", fontName="Serif-Bold", fontSize=20.5, leading=26,
        textColor=DEEP, alignment=TA_CENTER, spaceAfter=4)
    st["cta_body"] = ParagraphStyle(
        "cta_body", fontName="Sans", fontSize=11, leading=17.5,
        textColor=MUTED, alignment=TA_CENTER)
    st["botline"] = ParagraphStyle(
        "botline", fontName="Sans", fontSize=10.6, leading=15,
        textColor=DEEP, alignment=TA_CENTER)
    st["tiny"] = ParagraphStyle(
        "tiny", fontName="Sans", fontSize=8.6, leading=12,
        textColor=SOFT, alignment=TA_CENTER)
    return st


# ----------------------------------------------------------------------------
# Построители блоков
# ----------------------------------------------------------------------------

def para(html, s):
    return Paragraph(html, s)


def bullets(items, S):
    return [Paragraph(it, S["li"], bulletText="•") for it in items]


def tip(html, S, lead="Совет", color="#4C7B3F"):
    return Paragraph(
        f'<b><font color="{color}">{lead}. </font></b>{html}', S["tip"])


def card(title_html, paras, *, W, S, bar=0, bg=None, bar_color=None):
    bg = bg or CARDBG
    bar_color = bar_color or CARDBAR
    content = [Paragraph(title_html, S["card_title"])] + list(paras)
    return CompositeBox(
        content, width=W, bg=bg,
        bar=(bar, bar_color) if bar else None,
        pad=(12, 16, 13, 15))


def panel(title_html, items, *, W, S, bg=SAND, bullet="\u2713", bar_color=GOLD):
    paras = [Paragraph(title_html, S["panel_h"])]
    for it in items:
        paras.append(Paragraph(it, S["check"], bulletText=bullet))
    return CompositeBox(paras, width=W, bg=bg, top=(3.4, bar_color),
                        pad=(16, 19, 15, 17))


def cta_page(*, S, heading, body_html, W):
    flow = []
    flow.append(Spacer(1, 150))
    flow.append(Divider(color=ACCENT, width=240))
    flow.append(Spacer(1, 26))
    flow.append(Paragraph(heading, S["cta_h"]))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph(body_html, S["cta_body"]))
    flow.append(Spacer(1, 34))
    flow.append(LinkButton("Перейти в Telegram  \u2192"))
    flow.append(Spacer(1, 22))
    flow.append(Paragraph(
        f'<a href="{BUTTON_URL}" color="#1E4631"><b>{BOT_HANDLE}</b></a> '
        "— нажми, чтобы открыть бота", S["botline"]))
    flow.append(Spacer(1, 40))
    flow.append(Paragraph("Екатерина Сернова · цветник, который радует", S["tiny"]))
    return flow


# ----------------------------------------------------------------------------
# Сборка документа
# ----------------------------------------------------------------------------

def paginate(story, usable=FRAME_H, width=CW):
    atomic = (CompositeBox, TitleBand, LinkButton)
    out = []
    used = 0.0
    for fl in story:
        if isinstance(fl, PageBreak):
            out.append(fl)
            used = 0.0
            continue
        try:
            _, h = fl.wrap(width, usable)
        except Exception:
            h = getattr(fl, "height", 0)
        if isinstance(fl, Spacer) and h > usable:
            h = usable
        if used + h > usable + 0.6 and used > 0.5 and isinstance(fl, atomic):
            out.append(PageBreak())
            used = 0.0
        out.append(fl)
        if not isinstance(fl, Spacer) or h < usable:
            used += h
    return out


def build_doc(path, *, band_lines, title_footer, palette, story_maker):
    S = styles_for(palette)
    if palette is not None:
        S["tip"].backColor = palette[3]

    doc = BaseDocTemplate(path, pagesize=A4,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=FRAME_TOP, bottomMargin=FRAME_BOTTOM,
                          title=title_footer, author="Екатерина Сернова")
    frame = Frame(MARGIN, FRAME_Y0, CW, FRAME_H, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    def foot(c, d):
        footer(c, d, title_footer)

    doc.addPageTemplates([PageTemplate(id="P", frames=[frame], onPage=foot)])

    story = [TitleBand(band_lines)]
    story_maker(story, S, CW)
    story = paginate(story)
    doc.build(story)
    print("saved:", path)
