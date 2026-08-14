# -*- coding: utf-8 -*-
"""
Разбор свободного описания задачи в параметры генерации.

Пользователь пишет обычным текстом, что он хочет получить,
а агент подбирает все настройки, кроме голоса и фото —
их человек выбирает сам.

Работает без внешних сервисов: правила + морфология русского языка.
Возвращает не только параметры, но и объяснение каждого решения,
чтобы человек мог согласовать или поправить.
"""
from __future__ import annotations

import re

# Поля, которые агент НИКОГДА не трогает — их задаёт человек
NEVER_TOUCH = {"голос", "фото"}


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _find_quoted(text: str) -> str:
    """Достаёт текст речи из кавычек любого вида."""
    for pat in (r'«([^»]{8,})»', r'"([^"]{8,})"', r'„([^“]{8,})“',
                r'\'\'([^\']{8,})\'\''):
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    # после маркеров "текст:", "скажет:", "говорит:"
    m = re.search(r'(?:текст|скажет|говорит|произнесёт|произносит|реплика)\s*[:—-]\s*(.{10,})',
                  text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip().strip('"«»')
    return ""


def analyse(text: str) -> dict:
    """Возвращает {params, explain, questions, script_found}."""
    t = (text or "").lower()
    p: dict = {}
    ex: dict = {}
    q: list[str] = []

    # ── Соотношение сторон ───────────────────────────────────
    if _has(t, "reels", "рилс", "сторис", "stories", "shorts", "шортс",
            "тикток", "tiktok", "вертикал", "9:16", "вертик"):
        p["aspect_ratio"] = "9:16"
        ex["aspect_ratio"] = "вертикальное 9:16 — упомянуты вертикальные форматы"
    elif _has(t, "youtube", "ютуб", "горизонт", "16:9", "презентац", "вебинар"):
        p["aspect_ratio"] = "16:9"
        ex["aspect_ratio"] = "горизонтальное 16:9 — упомянут YouTube или презентация"
    elif _has(t, "лента", "пост в инстаграм", "4:5", "карусел"):
        p["aspect_ratio"] = "4:5"
        ex["aspect_ratio"] = "4:5 — формат ленты Instagram"
    elif _has(t, "квадрат", "1:1"):
        p["aspect_ratio"] = "1:1"
        ex["aspect_ratio"] = "квадрат 1:1 — прямо указано"
    else:
        p["aspect_ratio"] = "9:16"
        ex["aspect_ratio"] = "вертикальное 9:16 — формат по умолчанию для соцсетей"
        q.append("Формат не указан — поставил вертикальный 9:16. Нужен другой?")

    # ── Разрешение ───────────────────────────────────────────
    if _has(t, "4k", "4к", "максимальн качеств", "самое высокое качество"):
        p["resolution"] = "4k"
        ex["resolution"] = "4K — запрошено максимальное качество"
    elif _has(t, "720", "полегче", "побыстрее", "черновик", "быстро и дёшево",
              "тест", "пробн"):
        p["resolution"] = "720p"
        ex["resolution"] = "720p — нужен быстрый или черновой результат"
    else:
        p["resolution"] = "1080p"
        ex["resolution"] = "1080p — оптимально по качеству и цене"

    # ── Формат файла ─────────────────────────────────────────
    if _has(t, "прозрачн", "без фона", "альфа", "webm", "для монтаж", "наложить"):
        p["output_format"] = "webm"
        p["background_type"] = "remove"
        ex["output_format"] = "WebM с прозрачным фоном — нужно накладывать на другое видео"
        ex["background_type"] = "фон удалён — следует из запроса на прозрачность"
    else:
        p["output_format"] = "mp4"
        ex["output_format"] = "MP4 — универсальный формат для соцсетей"

    # ── Фон ──────────────────────────────────────────────────
    if "background_type" not in p:
        m = re.search(r'#([0-9a-fA-F]{6})', text)
        if m:
            p["background_type"] = "color"
            p["background_color"] = "#" + m.group(1)
            ex["background_type"] = f"сплошной цвет #{m.group(1)} — указан в тексте"
        elif _has(t, "тёмный фон", "темный фон", "чёрный фон", "черный фон"):
            p["background_type"] = "color"
            p["background_color"] = "#0B0B0F"
            ex["background_type"] = "тёмный фон #0B0B0F — упомянут тёмный фон"
        elif _has(t, "белый фон", "светлый фон"):
            p["background_type"] = "color"
            p["background_color"] = "#F2F2F2"
            ex["background_type"] = "светлый фон — упомянут в тексте"
        else:
            p["background_type"] = "none"
            ex["background_type"] = "фон оставлен как на фото"

    # ── Движок и выразительность ─────────────────────────────
    if _has(t, "максимальн качеств", "лучшее качество", "премиум", "avatar v",
            "дорого-богато", "кинематограф"):
        p["engine"] = "avatar_v"
        ex["engine"] = "Avatar V — запрошено максимальное качество"
    else:
        p["engine"] = "avatar_iv"
        ex["engine"] = "Avatar IV — универсальный движок, поддерживает мимику"

    if _has(t, "эмоцион", "ярко", "энергичн", "экспресс", "живо", "воодушев",
            "драйв", "заряжен"):
        p["expressiveness"] = "high"
        ex["expressiveness"] = "высокая выразительность — нужна яркая подача"
    elif _has(t, "спокойн", "сдержан", "серьёзн", "серьезн", "доверитель",
              "мягк", "камерн", "интимн"):
        p["expressiveness"] = "low"
        ex["expressiveness"] = "сдержанная мимика — нужна спокойная подача"
    else:
        p["expressiveness"] = "medium"
        ex["expressiveness"] = "средняя выразительность — нейтральная подача"

    # ── Сценарий движений ────────────────────────────────────
    motion_bits = []
    if _has(t, "спокойн", "сдержан", "доверитель"):
        motion_bits.append("спокойный уверенный взгляд в камеру")
    if _has(t, "энергичн", "ярко", "драйв", "воодушев"):
        motion_bits.append("живая энергичная подача, активная жестикуляция")
    if _has(t, "жест", "руками", "жестикул"):
        motion_bits.append("естественные жесты руками")
    if _has(t, "улыб", "дружелюб", "тепло"):
        motion_bits.append("тёплая доброжелательная полуулыбка")
    if _has(t, "серьёзн", "серьезн", "строг", "важн"):
        motion_bits.append("серьёзное сосредоточенное выражение лица")
    if _has(t, "эксперт", "professional", "профессионал", "деловой", "бизнес"):
        motion_bits.append("собранная экспертная подача")
    if not motion_bits:
        motion_bits = ["спокойный уверенный взгляд в камеру",
                       "лёгкие естественные жесты"]
    p["motion_prompt"] = ", ".join(motion_bits)
    ex["motion_prompt"] = "составлен из тона и настроения в вашем описании"

    # ── Субтитры ─────────────────────────────────────────────
    if _has(t, "без субтитр", "без титр", "не нужны субтитр", "без текста на экран"):
        p["caption_format"] = ""
        p["caption_style"] = ""
        ex["caption_format"] = "субтитры отключены — прямо просили без них"
    elif _has(t, "субтитр", "титр", "текст на экране", "без звука", "вшит"):
        p["caption_format"] = "srt"
        p["caption_style"] = "default" if _has(t, "вшит", "на экране",
                                               "в кадре", "без звука") else ""
        ex["caption_format"] = "субтитры включены — упомянуты в задаче"
    else:
        p["caption_format"] = "srt"
        p["caption_style"] = "default"
        ex["caption_format"] = ("субтитры вшиты в кадр — большинство смотрит "
                                "соцсети без звука")

    # ── Настройки голоса (кроме выбора самого голоса) ────────
    speed = 1.0
    if _has(t, "быстр", "энергичн", "динамичн", "бодр"):
        speed = 1.12
    if _has(t, "медлен", "размерен", "вдумчив", "спокойн", "мягк"):
        speed = 0.94
    p["voice_speed"] = round(speed, 2)
    ex["voice_speed"] = (f"скорость речи {p['voice_speed']} — "
                         + ("ускорена под динамичную подачу" if speed > 1
                            else "замедлена под спокойную подачу" if speed < 1
                            else "обычная"))

    p["voice_pitch"] = 0
    ex["voice_pitch"] = "высота голоса обычная"

    if _has(t, "воодушев", "энергичн", "ярко", "драйв", "радост"):
        p["voice_emotion"] = "Excited"
        ex["voice_emotion"] = "воодушевлённая подача"
    elif _has(t, "дружелюб", "тепло", "по-доброму", "мягк", "забот"):
        p["voice_emotion"] = "Friendly"
        ex["voice_emotion"] = "дружелюбная подача"
    elif _has(t, "серьёзн", "серьезн", "строг", "важн", "предупрежд"):
        p["voice_emotion"] = "Serious"
        ex["voice_emotion"] = "серьёзная подача"
    elif _has(t, "успокаива", "медитат", "расслаб", "нежн"):
        p["voice_emotion"] = "Soothing"
        ex["voice_emotion"] = "мягкая успокаивающая подача"
    elif _has(t, "диктор", "новост", "объявлен"):
        p["voice_emotion"] = "Broadcaster"
        ex["voice_emotion"] = "дикторская подача"
    else:
        p["voice_emotion"] = ""
        ex["voice_emotion"] = "эмоция не задана — нейтральная подача"

    # ── Язык ─────────────────────────────────────────────────
    if _has(t, "на английск", "in english", "english", "по-английски"):
        p["voice_locale"] = "en-US"
        ex["voice_locale"] = "английский язык — указан в задаче"
    elif _has(t, "на казахск"):
        p["voice_locale"] = "kk-KZ"
        ex["voice_locale"] = "казахский язык"
    elif _has(t, "на украинск"):
        p["voice_locale"] = "uk-UA"
        ex["voice_locale"] = "украинский язык"
    else:
        p["voice_locale"] = "ru-RU"
        ex["voice_locale"] = "русский язык"

    # ── Текст речи ───────────────────────────────────────────
    script = _find_quoted(text)
    if script:
        p["script"] = script
        ex["script"] = "текст взят из вашего описания (был в кавычках или после «текст:»)"
    else:
        q.append("Текст речи в описании не найден — впишите его в блоке 3 "
                 "или добавьте в кавычках.")

    # ── Название ─────────────────────────────────────────────
    title = re.sub(r'\s+', ' ', (text or '').strip())[:60]
    p["title"] = title or "Видео из Студии"
    ex["title"] = "название собрано из вашего описания"

    # ── Длительность → подсказка ─────────────────────────────
    # ловит «20 секунд», «секунд на 20», «на 20 сек», «минуту»
    m = (re.search(r'(\d{1,3})\s*(?:сек|секунд)', t)
         or re.search(r'(?:сек|секунд)\w*\s+(?:на\s+)?(\d{1,3})', t))
    if m:
        sec = int(m.group(1))
        words_needed = int(sec * 2.2)
        q.append(f"Для {sec} секунд нужно примерно {words_needed} слов "
                 f"({words_needed * 6} знаков) — проверьте объём текста.")

    return {"params": p, "explain": ex, "questions": q,
            "script_found": bool(script)}


# Человеческие названия полей для карточки согласования
LABELS = {
    "aspect_ratio": "Соотношение сторон",
    "resolution": "Разрешение",
    "output_format": "Формат файла",
    "engine": "Движок генерации",
    "expressiveness": "Выразительность мимики",
    "motion_prompt": "Поведение в кадре",
    "background_type": "Фон",
    "background_color": "Цвет фона",
    "caption_format": "Файл субтитров",
    "caption_style": "Субтитры в кадре",
    "voice_speed": "Скорость речи",
    "voice_pitch": "Высота голоса",
    "voice_emotion": "Эмоция подачи",
    "voice_locale": "Язык и акцент",
    "script": "Текст речи",
    "title": "Название ролика",
}
