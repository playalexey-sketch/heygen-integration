#!/usr/bin/env python3
"""Instagram competitor Reels intelligence agent.

The agent uses Apify actors to:
1. discover up to 1,000 Reels from a public profile;
2. enrich every Reel with likes, saves, shares, plays and transcripts;
3. apply strict thresholds without treating a missing metric as zero;
4. generate JSON, CSV, Markdown and HTML reports;
5. produce a clean-room Reel concept for each qualifying source Reel.

Secrets are read from environment variables and are never persisted.

Example:
    APIFY_TOKEN=... python instagram_reels_agent.py analyze \
        --profile bartsevmatvei --min-likes 1000 --min-saves 100 \
        --min-shares 100 --match all --max-results 1000 \
        --output-dir reports/reels-agent-live

A public snapshot can be analyzed without credentials:
    python instagram_reels_agent.py analyze \
        --snapshot reports/data/bartsevmatvei_public_snapshot.json \
        --missing-metrics include-unverified \
        --output-dir reports/reels-agent-snapshot
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DISCOVERY_ACTOR = "apify~instagram-reel-scraper"
METRICS_ACTOR = "patient_discovery~instagram-reel-analytics-by-url"
DEFAULT_PROFILE = "bartsevmatvei"


class AgentError(RuntimeError):
    """Expected operational error with a user-actionable message."""


@dataclasses.dataclass(slots=True)
class Thresholds:
    min_likes: int = 1_000
    min_saves: int = 100
    min_shares: int = 100
    match: str = "all"  # "all" requires saves AND shares; "any" requires either.
    missing_metrics: str = "exclude"  # exclude, include-unverified, error


@dataclasses.dataclass(slots=True)
class Reel:
    shortcode: str
    url: str
    owner_username: str = ""
    caption: str = ""
    transcript: str = ""
    published_at: str = ""
    duration_seconds: float | None = None
    likes: int | None = None
    comments: int | None = None
    plays: int | None = None
    saves: int | None = None
    shares: int | None = None
    reposts: int | None = None
    is_pinned: bool | None = None
    audio_title: str = ""
    thumbnail_url: str = ""
    video_url: str = ""
    source: str = ""
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)
    qualification: str = "pending"
    qualification_reason: str = ""

    def metric(self, name: str) -> int | None:
        value = getattr(self, name)
        return value if isinstance(value, int) else None


class ApifyClient:
    """Small dependency-free client for synchronous Apify Actor runs."""

    def __init__(self, token: str, timeout: int = 900) -> None:
        if not token:
            raise AgentError(
                "APIFY_TOKEN is not configured. Create an Apify account, place the token "
                "in the APIFY_TOKEN environment variable, and rerun. Do not commit it."
            )
        self.token = token
        self.timeout = timeout

    def run_sync(self, actor: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        encoded_actor = urllib.parse.quote(actor, safe="~")
        query = urllib.parse.urlencode(
            {
                "token": self.token,
                "format": "json",
                "clean": "true",
                "timeout": self.timeout,
            }
        )
        url = (
            f"https://api.apify.com/v2/acts/{encoded_actor}/"
            f"run-sync-get-dataset-items?{query}"
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "Arena-Reels-Intelligence-Agent/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout + 30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload_text = exc.read().decode("utf-8", "replace")
            if exc.code in (401, 402, 403):
                raise AgentError(
                    f"Apify rejected the run ({exc.code}). Check APIFY_TOKEN, account credits, "
                    f"and Actor access. Response: {payload_text[:500]}"
                ) from exc
            raise AgentError(f"Apify HTTP {exc.code}: {payload_text[:500]}") from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"Cannot reach Apify: {exc.reason}") from exc

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        raise AgentError(f"Unexpected Apify response shape from {actor}: {type(data).__name__}")


class OpenAICompatibleAnalyzer:
    """Optional analysis provider for any OpenAI-compatible chat endpoint."""

    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "")

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def analyze(self, reel: Reel) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        source_text = (reel.transcript or reel.caption).strip()
        if not source_text:
            return None
        system = (
            "Ты аналитик коротких видео. Анализируй только предоставленный текст. "
            "Не копируй фразы длиннее 8 слов. Создай оригинальную clean-room адаптацию. "
            "Верни только JSON с ключами: topic, hook_type, hook_reconstruction, "
            "retention_mechanics (array), save_trigger, share_trigger, controversy, "
            "new_title, new_hook, new_script, cta. CTA должен содержать: "
            "'Напиши цифру 2 — я пришлю Карту трёх скрытых сценариев'."
        )
        user = json.dumps(
            {
                "metrics": reel_to_public_dict(reel),
                "source_text": source_text[:14_000],
            },
            ensure_ascii=False,
        )
        request_body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.35,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=request_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:  # graceful fallback to deterministic analysis
            print(f"warning: LLM analysis failed for {reel.shortcode}: {exc}", file=sys.stderr)
            return None


def nested_get(item: Mapping[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def first_value(item: Mapping[str, Any], paths: Sequence[str]) -> Any:
    for path in paths:
        value = nested_get(item, path)
        if value is not None and value != "":
            return value
    return None


def to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().lower().replace(" ", "").replace(",", "")
        multiplier = 1
        if cleaned.endswith("k"):
            multiplier, cleaned = 1_000, cleaned[:-1]
        elif cleaned.endswith("m"):
            multiplier, cleaned = 1_000_000, cleaned[:-1]
        try:
            return int(float(cleaned) * multiplier)
        except ValueError:
            return None
    return None


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def shortcode_from(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"instagram\.com/(?:reel|reels|p)/([^/?#]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{5,20}", value):
        return value
    return ""


def normalize_reel(item: Mapping[str, Any], source: str) -> Reel:
    url = str(
        first_value(
            item,
            ["url", "reelUrl", "reelURL", "postUrl", "postURL", "inputUrl", "permalink"],
        )
        or ""
    )
    shortcode = str(
        first_value(item, ["shortcode", "shortCode", "code", "media.code", "postCode"])
        or shortcode_from(url)
        or ""
    )
    if not url and shortcode:
        url = f"https://www.instagram.com/reel/{shortcode}/"

    likes = to_int(first_value(item, ["likes", "likesCount", "likeCount", "like_count", "metrics.like_count"]))
    comments = to_int(
        first_value(item, ["comments", "commentsCount", "commentCount", "comment_count", "metrics.comment_count"])
    )
    plays = to_int(
        first_value(
            item,
            [
                "plays",
                "playsCount",
                "playCount",
                "play_count",
                "videoPlayCount",
                "videoViewCount",
                "viewCount",
                "metrics.play_count",
                "metrics.ig_play_count",
            ],
        )
    )
    saves = to_int(
        first_value(item, ["saves", "savesCount", "saveCount", "save_count", "metrics.save_count"])
    )
    shares = to_int(
        first_value(item, ["shares", "sharesCount", "shareCount", "share_count", "metrics.share_count"])
    )
    reposts = to_int(
        first_value(item, ["reposts", "repostsCount", "repostCount", "repost_count", "metrics.repost_count"])
    )
    caption = str(first_value(item, ["caption", "caption.text", "text", "description"]) or "")
    transcript_value = first_value(item, ["transcript", "transcriptText", "transcription", "videoTranscript"])
    if isinstance(transcript_value, list):
        transcript = " ".join(
            str(part.get("text", "") if isinstance(part, Mapping) else part)
            for part in transcript_value
        ).strip()
    else:
        transcript = str(transcript_value or "")

    return Reel(
        shortcode=shortcode,
        url=url,
        owner_username=str(
            first_value(item, ["ownerUsername", "owner_username", "username", "user.username"])
            or ""
        ),
        caption=caption,
        transcript=transcript,
        published_at=str(
            first_value(item, ["timestamp", "takenAt", "taken_at_date", "publishedAt", "date"])
            or ""
        ),
        duration_seconds=to_float(
            first_value(item, ["duration", "videoDuration", "video_duration", "video.duration"])
        ),
        likes=likes,
        comments=comments,
        plays=plays,
        saves=saves,
        shares=shares,
        reposts=reposts,
        is_pinned=first_value(item, ["isPinned", "is_pinned"]),
        audio_title=str(
            first_value(item, ["audioTitle", "audio.title", "musicInfo.songName", "clips_metadata.audio_title"])
            or ""
        ),
        thumbnail_url=str(
            first_value(item, ["thumbnailUrl", "thumbnail_url", "displayUrl", "display_url"])
            or ""
        ),
        video_url=str(first_value(item, ["videoUrl", "video_url"]) or ""),
        source=source,
        raw=dict(item),
    )


def merge_reels(base: Reel, enriched: Reel) -> Reel:
    for field in dataclasses.fields(Reel):
        name = field.name
        if name in {"raw", "source", "qualification", "qualification_reason"}:
            continue
        value = getattr(enriched, name)
        if value not in (None, "", [], {}):
            setattr(base, name, value)
    base.source = ",".join(part for part in [base.source, enriched.source] if part)
    base.raw = {"discovery": base.raw, "enrichment": enriched.raw}
    return base


def reel_key(reel: Reel) -> str:
    return reel.shortcode or reel.url.rstrip("/")


def discover_live(client: ApifyClient, profile: str, max_results: int, transcripts: bool) -> list[Reel]:
    payload = {
        "username": [profile],
        "resultsLimit": max_results,
        "skipPinnedPosts": False,
        "skipTrialReels": False,
        "includeSharesCount": True,
        "includeTranscript": transcripts,
        "includeDownloadedVideo": False,
    }
    items = client.run_sync(DISCOVERY_ACTOR, payload)
    reels = [normalize_reel(item, DISCOVERY_ACTOR) for item in items]
    return deduplicate([reel for reel in reels if reel.shortcode or reel.url])


def enrich_live(client: ApifyClient, reels: list[Reel], batch_size: int = 100) -> list[Reel]:
    index = {reel_key(reel): reel for reel in reels}
    candidates = [reel for reel in reels if reel.url]
    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset : offset + batch_size]
        payload = {"postUrls": [reel.url for reel in batch]}
        items = client.run_sync(METRICS_ACTOR, payload)
        for item in items:
            enriched = normalize_reel(item, METRICS_ACTOR)
            key = reel_key(enriched)
            if key in index:
                merge_reels(index[key], enriched)
                continue
            # Some providers return only a URL variant; match by shortcode.
            if enriched.shortcode:
                for existing_key, existing in index.items():
                    if existing.shortcode == enriched.shortcode:
                        merge_reels(existing, enriched)
                        break
    return list(index.values())


def deduplicate(reels: Iterable[Reel]) -> list[Reel]:
    result: dict[str, Reel] = {}
    for reel in reels:
        key = reel_key(reel)
        if not key:
            continue
        if key in result:
            merge_reels(result[key], reel)
        else:
            result[key] = reel
    return list(result.values())


def load_snapshot(path: Path) -> list[Reel]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("reels", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise AgentError("Snapshot must be a JSON array or an object with a reels array")
    return deduplicate([normalize_reel(item, f"snapshot:{path.name}") for item in items if isinstance(item, dict)])


def qualify(reel: Reel, thresholds: Thresholds) -> bool:
    missing = [name for name in ("likes", "saves", "shares") if reel.metric(name) is None]
    if "likes" in missing:
        reel.qualification = "excluded"
        reel.qualification_reason = "likes metric is missing"
        if thresholds.missing_metrics == "error":
            raise AgentError(f"{reel.url}: likes metric is missing")
        return False

    if reel.likes is not None and reel.likes < thresholds.min_likes:
        reel.qualification = "excluded"
        reel.qualification_reason = f"likes {reel.likes} < {thresholds.min_likes}"
        return False

    private_missing = [name for name in ("saves", "shares") if reel.metric(name) is None]
    if private_missing:
        if thresholds.missing_metrics == "error":
            raise AgentError(f"{reel.url}: missing metrics: {', '.join(private_missing)}")
        if thresholds.missing_metrics == "include-unverified":
            reel.qualification = "unverified-candidate"
            reel.qualification_reason = (
                f"likes threshold passed; missing {', '.join(private_missing)} prevents strict verification"
            )
            return True
        reel.qualification = "excluded"
        reel.qualification_reason = f"missing metrics: {', '.join(private_missing)}"
        return False

    saves_ok = bool(reel.saves is not None and reel.saves >= thresholds.min_saves)
    shares_ok = bool(reel.shares is not None and reel.shares >= thresholds.min_shares)
    engagement_ok = (saves_ok and shares_ok) if thresholds.match == "all" else (saves_ok or shares_ok)
    if engagement_ok:
        reel.qualification = "qualified"
        connector = "and" if thresholds.match == "all" else "or"
        reel.qualification_reason = (
            f"likes >= {thresholds.min_likes}; saves >= {thresholds.min_saves} "
            f"{connector} shares >= {thresholds.min_shares}"
        )
        return True

    reel.qualification = "excluded"
    reel.qualification_reason = (
        f"saves={reel.saves}, shares={reel.shares}; mode={thresholds.match}"
    )
    return False


THEME_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("отношения и партнёрство", ("муж", "жен", "отнош", "партнер", "любов", "супруг")),
    ("семья, дети и родительские сценарии", ("ребен", "дет", "родител", "отец", "мать", "семь")),
    ("деньги, ценность и проявленность", ("деньг", "богат", "бедн", "цен", "миллион", "доход", "скром")),
    ("род, предки и повторяющиеся программы", ("род", "предк", "программ", "поколен")),
    ("предназначение и личная сила", ("предназнач", "сил", "потенциал", "реализац", "путь")),
    ("шаманизм и духовная идентичность", ("шаман", "обряд", "бог", "дух", "посвящ")),
]


def detect_theme(text: str) -> str:
    lowered = text.lower()
    scored = []
    for theme, keywords in THEME_KEYWORDS:
        score = sum(lowered.count(keyword) for keyword in keywords)
        scored.append((score, theme))
    score, theme = max(scored, default=(0, "личная трансформация"))
    return theme if score else "личная трансформация и мировоззрение"


def sentence_list(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]


def deterministic_analysis(reel: Reel) -> dict[str, Any]:
    source_text = (reel.transcript or reel.caption).strip()
    theme = detect_theme(source_text)
    lowered = source_text.lower()
    if theme == "отношения и партнёрство":
        if any(word in lowered for word in ("обид", "груб", "крик", "конфликт")):
            theme = "отношения: обида и восстановление после конфликта"
        elif any(word in lowered for word in ("успех", "цель", "вдохнов", "достижен")):
            theme = "отношения: поддержка, цель и личная ответственность"
        else:
            theme = "отношения: раскрытие или потеря себя рядом с партнёром"
    sentences = sentence_list(source_text)
    observed_hook = sentences[0][:320] if sentences else "Точный хук не извлечён: нужен transcript"
    base = {
        "topic": theme,
        "hook_type": "категоричный тезис или смена привычной причины",
        "hook_reconstruction": observed_hook,
        "retention_mechanics": [
            "массовая узнаваемая боль появляется в первой фразе",
            "привычное объяснение заменяется одной неожиданной причиной",
            "зрителю дают сторону, с которой легко себя идентифицировать",
            "финальный вывод можно вынести на обложку или переслать отдельно",
        ],
        "key_elements": [
            "прямая речь без приветствия",
            "полярность: вверх/вниз, ответственность/перекладывание, видимость/скромность",
            "одна основная мысль на Reel",
            "личная ставка: отношения, дети, деньги или предназначение",
            "открытый вопрос, который продолжает спор в комментариях",
        ],
        "why_it_worked": [
            "тема понятна человеку вне шаманской ниши",
            "диагноз легко примерить на собственную жизнь",
            "ролик имеет конкретного адресата для пересылки",
            "категоричность повышает запоминаемость и одновременно вызывает возражения",
        ],
        "save_trigger": "чек-лист или формула, к которой можно вернуться перед разговором или решением",
        "share_trigger": "ролик можно отправить партнёру, родителю, подруге или специалисту вместо длинного объяснения",
        "controversy": "риск упрощения сложной проблемы и переноса ответственности на одну сторону",
    }
    base.update(script_template_for_theme(theme))
    base.setdefault("new_cover", str(base.get("new_title", "СИЛЬНАЯ МЫСЛЬ"))[:58].upper())
    base.setdefault("useful_content", "Три конкретных вопроса или действия, которые зритель может применить сразу после просмотра.")
    base.setdefault("visual_plan", "Крупный план на хуке; смысловые склейки; ключевые пункты цифрами; финальный CTA произносится голосом.")
    base.setdefault("caption", f"{base.get('new_title', 'Новая тема')}. Напишите цифру 2 — пришлю Карту трёх скрытых сценариев.")
    base.setdefault("pinned_comment", "Цифра 2 — отправлю карту. Как эта тема проявляется в вашей жизни?")
    base.setdefault("alternate_hooks", [
        str(base.get("new_hook", "")),
        "Есть одна причина, которую большинство замечает слишком поздно.",
        "Проверьте себя по трём признакам — третий обычно самый неудобный.",
    ])
    return base


def script_template_for_theme(theme: str) -> dict[str, Any]:
    cta = "Напиши цифру 2 — я пришлю Карту трёх скрытых сценариев с 21 вопросом."
    if "обида" in theme or "конфликт" in theme:
        return {
            "new_title": "Почему одного «прости» иногда недостаточно",
            "new_cover": "ИЗВИНЕНИЕ НЕ ЗАКРЫВАЕТ КОНФЛИКТ",
            "new_hook": "Если человек извинился, а обида осталась, это не всегда означает, что вы слишком долго помните плохое.",
            "new_script": (
                "0–5 с: Если человек извинился, а обида осталась, это не всегда означает, что вы слишком долго помните плохое.\n"
                "5–14 с: Конфликт не закрывается словом 'прости', если никто не назвал, что именно произошло.\n"
                "14–28 с: Первый шаг — признать действие без 'но': я повысил голос, обесценил или нарушил договорённость.\n"
                "28–42 с: Второй — увидеть влияние, а не защищать намерение фразой 'я же не хотел'.\n"
                "42–55 с: Третий — договориться, что конкретно каждый сделает иначе при следующем напряжении.\n"
                "55–64 с: Прощение без нового поведения легко превращается в разрешение повторить старое.\n"
                f"64–70 с: {cta}"
            ),
            "useful_content": "Три шага восстановления: назвать действие, признать влияние, создать новую договорённость.",
            "visual_plan": "Крупный план на хуке; три шага выводятся цифрами; пауза перед финальным афоризмом; без драматичного B-roll.",
            "caption": "Извинение становится восстановлением только тогда, когда за ним следует ясность и новое поведение. Напишите цифру 2 — пришлю карту из 21 вопроса.",
            "pinned_comment": "Цифра 2 — отправлю карту. Что для вас важнее в извинении: слова, признание влияния или изменение поведения?",
            "alternate_hooks": [
                "Обида часто держится не за прошлое, а за риск, что всё повторится.",
                "Фраза 'я же извинился' не восстанавливает доверие автоматически.",
                "Конфликт заканчивается не тогда, когда замолчали, а когда появилась новая договорённость.",
            ],
            "cta": cta,
        }
    if "поддержка" in theme or "личная ответственность" in theme:
        return {
            "new_title": "Партнёр может поддержать успех, но не создать вашу цель",
            "new_cover": "ПОДДЕРЖКА НЕ ЗАМЕНЯЕТ ЦЕЛЬ",
            "new_hook": "Если ваш успех полностью зависит от партнёра, вы отдали другому человеку слишком много власти над своей жизнью.",
            "new_script": (
                "0–6 с: Если ваш успех полностью зависит от партнёра, вы отдали другому человеку слишком много власти над своей жизнью.\n"
                "6–17 с: Близкий человек действительно может усиливать ресурс — или ежедневно забирать его конфликтами и обесцениванием.\n"
                "17–31 с: Но поддержка не должна становиться управлением: партнёр не обязан придумывать вам цель и заставлять действовать.\n"
                "31–45 с: Зрелая поддержка — это когда ваши планы можно обсуждать без насмешки, а успех одного не угрожает другому.\n"
                "45–58 с: Ответственность за движение остаётся у вас. Поддержка добавляет силы, но не заменяет внутренний стержень.\n"
                f"58–64 с: {cta}"
            ),
            "useful_content": "Три критерия зрелой поддержки: планы можно обсуждать, успех не вызывает наказания, ответственность не перекладывается.",
            "visual_plan": "Спокойный монолог; слова 'поддержка', 'управление', 'ответственность' появляются как три контрастных карточки.",
            "caption": "Партнёр влияет на ресурс, но не обязан становиться вашим двигателем. Напишите цифру 2 — пришлю карту трёх скрытых сценариев.",
            "pinned_comment": "Цифра 2 — отправлю карту. Где для вас проходит граница между поддержкой и попыткой управлять жизнью партнёра?",
            "alternate_hooks": [
                "Любящий партнёр не обязан быть вашим личным тренером по успеху.",
                "Поддержка усиливает движение, но не создаёт цель вместо вас.",
                "Опасно делать другого человека единственным источником собственной силы.",
            ],
            "cta": cta,
        }
    if "отношения" in theme:
        return {
            "new_title": "Три признака, что в отношениях вы становитесь меньше",
            "new_cover": "ВЫ РАСКРЫВАЕТЕСЬ ИЛИ ИСЧЕЗАЕТЕ?",
            "new_hook": "Самый честный тест отношений — кем вы становитесь рядом с человеком.",
            "new_script": (
                "0–4 с: Самый честный тест отношений — кем вы становитесь рядом с человеком.\n"
                "4–12 с: Есть три сигнала, что вы постепенно теряете себя.\n"
                "12–23 с: Первый — вы боитесь говорить прямо и заранее подбираете безопасные слова.\n"
                "23–34 с: Второй — вы отказываетесь от целей и близких, чтобы не вызвать недовольство.\n"
                "34–46 с: Третий — после конфликта вы доказываете право на собственные чувства.\n"
                "46–55 с: Зрелая связь не требует стать меньше, чтобы остаться вместе.\n"
                f"55–62 с: {cta}"
            ),
            "useful_content": "Три признака потери себя: страх прямого разговора, отказ от собственной жизни, защита права на чувства.",
            "visual_plan": "Крупный план; три признака выводятся цифрами; финальная фраза на статичном кадре; субтитры по 3–6 слов.",
            "caption": "Отношения видны по тому, какими людьми мы рядом становимся. Напишите цифру 2 — пришлю карту из 21 вопроса.",
            "pinned_comment": "Цифра 2 — отправлю карту. Рядом с близким человеком вы чаще раскрываетесь или сжимаетесь?",
            "alternate_hooks": [
                "Состояние человека рядом с вами честнее любых слов о любви.",
                "Иногда отношения заканчиваются в момент, когда один перестаёт быть собой.",
                "Если ради любви нужно стать меньше, цена связи слишком высока.",
            ],
            "cta": cta,
        }
    if "семья" in theme or "дет" in theme:
        return {
            "new_title": "Перед тем как исправлять ребёнка, проверьте взрослых",
            "new_hook": "Когда ребёнка называют трудным, я первым делом смотрю не на ребёнка.",
            "new_script": (
                "0–4 с: Когда ребёнка называют трудным, я первым делом смотрю не на ребёнка.\n"
                "4–14 с: Его поведение может быть языком напряжения, которое взрослые не замечают.\n"
                "14–28 с: Проверьте первое: одинаковы ли правила сегодня и завтра.\n"
                "28–42 с: Второе: не становится ли ребёнок посредником между родителями.\n"
                "42–55 с: Третье: получает ли он внимание без кризиса.\n"
                "55–68 с: Ответственность не равна вине, а изменения важно обсуждать со специалистом.\n"
                f"68–75 с: {cta}"
            ),
            "cta": cta,
        }
    if "деньги" in theme:
        return {
            "new_title": "Скромность или финансовая невидимость?",
            "new_hook": "Можно быть сильным специалистом и оставаться без денег, если никто не понял вашу ценность.",
            "new_script": (
                "0–4 с: Можно быть сильным специалистом и оставаться без денег, если никто не понял вашу ценность.\n"
                "4–11 с: Скромность — не хвастаться. Молчать о результате — это невидимость.\n"
                "11–18 с: Назовите проблему, которую решаете.\n"
                "18–25 с: Покажите один конкретный результат.\n"
                "25–31 с: Назовите цену без оправданий.\n"
                f"31–36 с: {cta}"
            ),
            "cta": cta,
        }
    if "род" in theme:
        return {
            "new_title": "Как понять, что вы повторяете не свой выбор",
            "new_hook": "Не каждое ваше решение родилось сегодня — некоторые сценарии старше вас.",
            "new_script": (
                "0–4 с: Не каждое ваше решение родилось сегодня — некоторые сценарии старше вас.\n"
                "4–16 с: Первый признак — вы повторяете семейный выбор, хотя он делает вас несчастнее.\n"
                "16–29 с: Второй — фраза 'у нас всегда так было' заменяет собственное решение.\n"
                "29–43 с: Третий — чувство вины появляется, когда вы выбираете иначе.\n"
                "43–54 с: Уважать историю семьи не означает повторять каждую её боль.\n"
                f"54–60 с: {cta}"
            ),
            "cta": cta,
        }
    return {
        "new_title": "Три вопроса перед важным решением",
        "new_hook": "Иногда вы устали не от пути — вы устали жить по чужому сценарию.",
        "new_script": (
            "0–4 с: Иногда вы устали не от пути — вы устали жить по чужому сценарию.\n"
            "4–16 с: Спросите: я правда этого хочу или боюсь разочаровать других?\n"
            "16–29 с: Что я выбрал бы без необходимости что-либо доказывать?\n"
            "29–43 с: Какой один шаг вернёт мне авторство решения?\n"
            "43–54 с: Чужое одобрение не заменяет собственную жизнь.\n"
            f"54–60 с: {cta}"
        ),
        "cta": cta,
    }


def analyze_reels(reels: list[Reel]) -> dict[str, dict[str, Any]]:
    llm = OpenAICompatibleAnalyzer()
    output: dict[str, dict[str, Any]] = {}
    for reel in reels:
        analysis = llm.analyze(reel) or deterministic_analysis(reel)
        output[reel_key(reel)] = analysis
    return output


def reel_to_public_dict(reel: Reel) -> dict[str, Any]:
    return {
        "shortcode": reel.shortcode,
        "url": reel.url,
        "owner_username": reel.owner_username,
        "caption": reel.caption,
        "transcript": reel.transcript,
        "published_at": reel.published_at,
        "duration_seconds": reel.duration_seconds,
        "likes": reel.likes,
        "comments": reel.comments,
        "plays": reel.plays,
        "saves": reel.saves,
        "shares": reel.shares,
        "reposts": reel.reposts,
        "is_pinned": reel.is_pinned,
        "audio_title": reel.audio_title,
        "thumbnail_url": reel.thumbnail_url,
        "video_url": reel.video_url,
        "source": reel.source,
        "qualification": reel.qualification,
        "qualification_reason": reel.qualification_reason,
    }


def fmt_metric(value: int | None) -> str:
    return "н/д" if value is None else f"{value:,}".replace(",", " ")


def report_markdown(
    profile: str,
    all_reels: list[Reel],
    selected: list[Reel],
    analyses: Mapping[str, Mapping[str, Any]],
    thresholds: Thresholds,
    generated_at: str,
) -> str:
    strict_count = sum(reel.qualification == "qualified" for reel in selected)
    unverified_count = sum(reel.qualification == "unverified-candidate" for reel in selected)
    lines = [
        f"# Instagram Reels Intelligence — @{profile}",
        "",
        f"**Сформировано:** {generated_at}  ",
        f"**Просканировано Reels:** {len(all_reels)}  ",
        f"**Строго соответствуют фильтру:** {strict_count}  ",
        f"**Кандидаты с отсутствующими закрытыми метриками:** {unverified_count}",
        "",
        "## Фильтр",
        "",
        f"- лайки ≥ **{thresholds.min_likes}**;",
        f"- сохранения ≥ **{thresholds.min_saves}**;",
        f"- пересылки ≥ **{thresholds.min_shares}**;",
        f"- логика сохранения/пересылки: **{thresholds.match.upper()}**;",
        f"- политика отсутствующих метрик: **{thresholds.missing_metrics}**.",
        "",
        "> Значение «н/д» не считается нулём. В строгом режиме Reel без saves/shares не проходит фильтр.",
        "",
        "## Сводная таблица",
        "",
        "| Reel | Дата | Лайки | Сохранения | Пересылки | Просмотры | Статус |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for reel in selected:
        lines.append(
            f"| [{reel.shortcode or 'Reel'}]({reel.url}) | {reel.published_at or 'н/д'} | "
            f"{fmt_metric(reel.likes)} | {fmt_metric(reel.saves)} | {fmt_metric(reel.shares)} | "
            f"{fmt_metric(reel.plays)} | {reel.qualification} |"
        )

    if not selected:
        lines.extend(
            [
                "",
                "## Результат",
                "",
                "Ни один Reel не прошёл заданный строгий фильтр либо необходимые метрики не были получены.",
            ]
        )

    for index, reel in enumerate(selected, 1):
        analysis = analyses[reel_key(reel)]
        retention = analysis.get("retention_mechanics") or []
        if not isinstance(retention, list):
            retention = [str(retention)]
        key_elements = analysis.get("key_elements") or []
        if not isinstance(key_elements, list):
            key_elements = [str(key_elements)]
        why_it_worked = analysis.get("why_it_worked") or []
        if not isinstance(why_it_worked, list):
            why_it_worked = [str(why_it_worked)]
        alternate_hooks = analysis.get("alternate_hooks") or []
        if not isinstance(alternate_hooks, list):
            alternate_hooks = [str(alternate_hooks)]
        lines.extend(
            [
                "",
                "---",
                "",
                f"# Reel {index}: {reel.shortcode}",
                "",
                f"**Ссылка:** {reel.url}  ",
                f"**Лайки:** {fmt_metric(reel.likes)} · **Сохранения:** {fmt_metric(reel.saves)} · "
                f"**Пересылки:** {fmt_metric(reel.shares)} · **Просмотры:** {fmt_metric(reel.plays)}  ",
                f"**Статус:** {reel.qualification} — {reel.qualification_reason}",
                "",
                "## Аналитика исходника",
                "",
                f"- **Тема:** {analysis.get('topic', 'н/д')}",
                f"- **Тип хука:** {analysis.get('hook_type', 'н/д')}",
                f"- **Восстановленный хук:** {analysis.get('hook_reconstruction', 'н/д')}",
                f"- **Триггер сохранения:** {analysis.get('save_trigger', 'н/д')}",
                f"- **Триггер пересылки:** {analysis.get('share_trigger', 'н/д')}",
                f"- **Риск/поляризация:** {analysis.get('controversy', 'н/д')}",
                "",
                "### Механика удержания",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in retention)
        lines.extend(["", "### Ключевые элементы исходной механики", ""])
        lines.extend(f"- {item}" for item in key_elements)
        lines.extend(["", "### Почему это могло сработать", ""])
        lines.extend(f"- {item}" for item in why_it_worked)
        source_text = reel.transcript or reel.caption
        lines.extend(
            [
                "",
                "### Источник смысла",
                "",
                source_text[:5_000] if source_text else "Транскрипт и подпись не получены; содержательный вывод ограничен.",
                "",
                "## Какой Reel сделать вам",
                "",
                f"### {analysis.get('new_title', 'Оригинальный Reel')}",
                "",
                f"**Обложка:** {analysis.get('new_cover', '')}  ",
                f"**Хук:** {analysis.get('new_hook', '')}",
                "",
                "### Полный сценарий",
                "",
                str(analysis.get("new_script", "")),
                "",
                "### Полезный контент",
                "",
                str(analysis.get("useful_content", "")),
                "",
                "### Визуал и монтаж",
                "",
                str(analysis.get("visual_plan", "")),
                "",
                "### CTA",
                "",
                f"> {analysis.get('cta', '')}",
                "",
                "### Подпись к Reel",
                "",
                str(analysis.get("caption", "")),
                "",
                "### Закреплённый комментарий",
                "",
                f"> {analysis.get('pinned_comment', '')}",
                "",
                "### Три альтернативных хука",
                "",
            ]
        )
        lines.extend(f"{hook_index}. {hook}" for hook_index, hook in enumerate(alternate_hooks, 1))
        lines.extend(
            [
                "",
                "### Лид-магнит",
                "",
                "**«Карта трёх скрытых сценариев: отношения, семья и деньги»** — 21 вопрос, "
                "три блока, расшифровка и план одного изменения на 72 часа.",
            ]
        )
    return "\n".join(lines) + "\n"


def inline_markdown(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(markdown: str, title: str) -> str:
    lines = markdown.splitlines()
    body: list[str] = []
    headings: list[tuple[int, str, str]] = []
    i = 0
    heading_id = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.strip() == "---":
            body.append("<hr>")
            i += 1
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            heading_id += 1
            hid = f"section-{heading_id}"
            text = heading.group(2)
            headings.append((level, text, hid))
            body.append(f'<h{level} id="{hid}">{inline_markdown(text)}</h{level}>')
            i += 1
            continue
        if line.startswith("> "):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i][2:])
                i += 1
            body.append(f"<blockquote>{' '.join(inline_markdown(x) for x in quote)}</blockquote>")
            continue
        if "|" in line and i + 1 < len(lines) and re.match(r"^\|?[\s:|-]+\|", lines[i + 1]):
            headers = [part.strip() for part in line.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([part.strip() for part in lines[i].strip().strip("|").split("|")])
                i += 1
            table = ["<div class=\"table-wrap\"><table><thead><tr>"]
            table.extend(f"<th>{inline_markdown(cell)}</th>" for cell in headers)
            table.append("</tr></thead><tbody>")
            for row in rows:
                row.extend([""] * (len(headers) - len(row)))
                table.append("<tr>" + "".join(f"<td>{inline_markdown(cell)}</td>" for cell in row[: len(headers)]) + "</tr>")
            table.append("</tbody></table></div>")
            body.append("".join(table))
            continue
        if re.match(r"^[-*]\s+", line):
            items: list[str] = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(re.sub(r"^[-*]\s+", "", lines[i]))
                i += 1
            body.append("<ul>" + "".join(f"<li>{inline_markdown(item)}</li>" for item in items) + "</ul>")
            continue
        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i]))
                i += 1
            body.append("<ol>" + "".join(f"<li>{inline_markdown(item)}</li>" for item in items) + "</ol>")
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4})\s+|^[-*]\s+|^\d+\.\s+|^>\s+|^---$", lines[i]):
            if "|" in lines[i] and i + 1 < len(lines) and re.match(r"^\|?[\s:|-]+\|", lines[i + 1]):
                break
            paragraph.append(lines[i])
            i += 1
        body.append("<p>" + "<br>".join(inline_markdown(part) for part in paragraph) + "</p>")

    toc = "".join(
        f'<a class="level-{level}" href="#{hid}">{inline_markdown(text)}</a>'
        for level, text, hid in headings
        if level <= 2
    )
    css = """
:root{--ink:#18251f;--muted:#607069;--paper:#f5f2e9;--card:#fffef9;--forest:#153e33;--gold:#c28e3a;--sage:#e1ebe4;--line:#d9ddd6;--shadow:0 12px 34px rgba(21,62,51,.09)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:radial-gradient(circle at 5% 0,rgba(194,142,58,.13),transparent 28rem),var(--paper);font:16px/1.64 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}a{color:#28604f;text-underline-offset:3px}.wrap{max-width:1180px;margin:auto;padding:28px 22px 80px}.hero{padding:clamp(30px,6vw,68px);border-radius:28px;color:white;background:linear-gradient(135deg,#102d26,#1d5848 68%,#98732e 150%);box-shadow:0 25px 65px rgba(21,62,51,.2)}.hero small{color:#f2d8a4;font-weight:800;letter-spacing:.15em}.hero h1{max-width:930px;margin:12px 0 16px;color:white;font:700 clamp(38px,6vw,66px)/1 Georgia,serif;letter-spacing:-.035em}.hero p{max-width:790px;color:rgba(255,255,255,.8);font-size:18px}.toc{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:20px 0 48px;padding:20px;border:1px solid rgba(21,62,51,.11);border-radius:18px;background:var(--card);box-shadow:var(--shadow)}.toc a{padding:7px 9px;border-radius:8px;text-decoration:none;font-size:13px}.toc a:hover{background:var(--sage)}.toc .level-1{font-weight:800}.toc .level-2{padding-left:16px;color:var(--muted)}article{max-width:1050px;margin:auto}h1,h2,h3,h4{color:var(--forest);scroll-margin-top:24px}article h1{margin:70px 0 18px;padding-top:28px;border-top:3px solid var(--forest);font:700 clamp(34px,5vw,49px)/1.08 Georgia,serif}article h1:first-child{margin-top:0;border-top:0}h2{margin:36px 0 13px;font:700 29px/1.16 Georgia,serif}h3{margin:24px 0 9px;font-size:18px}p{margin:0 0 14px}strong{color:#173f34}hr{height:1px;border:0;background:var(--line);margin:44px 0}blockquote{margin:20px 0;padding:20px 23px;border-left:4px solid var(--gold);border-radius:0 14px 14px 0;background:#fff8e8;color:#314940;font:700 18px/1.5 Georgia,serif}ul,ol{padding-left:23px}li{margin:7px 0}.table-wrap{overflow-x:auto;margin:17px 0 24px;border-radius:14px}table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);font-size:14px}th,td{padding:12px 13px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}th{color:white;background:var(--forest);font-size:12px}tr:last-child td{border-bottom:0}tbody tr:nth-child(even) td{background:#faf8f2}.footer{max-width:1050px;margin:60px auto 0;padding-top:22px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}@media(max-width:760px){.wrap{padding:14px 12px 55px}.hero{border-radius:20px;padding:30px 22px}.hero h1{font-size:36px}.toc{grid-template-columns:1fr}th,td{padding:9px}}@media print{body{background:white;font-size:10.5pt}.wrap{max-width:none;padding:0}.hero{box-shadow:none;border-radius:0;print-color-adjust:exact}.toc{display:none}article{max-width:none}.table-wrap{overflow:visible}table,blockquote{break-inside:avoid}a{color:inherit;text-decoration:none}}
"""
    return (
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{css}</style></head><body><div class=\"wrap\">"
        f"<header class=\"hero\"><small>REELS INTELLIGENCE AGENT · STRICT METRICS</small>"
        f"<h1>{html.escape(title)}</h1><p>Полный профильный скан, строгий фильтр likes/saves/shares, "
        "содержательный анализ и clean-room сценарий для каждого прошедшего Reel.</p></header>"
        f"<nav class=\"toc\">{toc}</nav><article>{''.join(body)}</article>"
        "<div class=\"footer\">Значение н/д не считается нулём. Метрики снабжаются статусом источника. "
        "Сценарии не являются транскриптами или копиями исходников.</div></div></body></html>"
    )


def write_csv(path: Path, reels: Sequence[Reel]) -> None:
    fields = [
        "shortcode", "url", "published_at", "likes", "saves", "shares", "comments",
        "plays", "reposts", "duration_seconds", "qualification", "qualification_reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for reel in reels:
            public = reel_to_public_dict(reel)
            writer.writerow({field: public.get(field) for field in fields})


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze all Reels from a public Instagram profile")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check configuration without starting a paid run")
    doctor.add_argument("--profile", default=DEFAULT_PROFILE)

    analyze = subparsers.add_parser("analyze", help="Run discovery, enrichment, filtering and reporting")
    source = analyze.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile", help="Instagram username, profile URL or profile ID")
    source.add_argument("--snapshot", type=Path, help="Analyze a previously captured JSON snapshot")
    analyze.add_argument("--max-results", type=int, default=1_000)
    analyze.add_argument("--min-likes", type=int, default=1_000)
    analyze.add_argument("--min-saves", type=int, default=100)
    analyze.add_argument("--min-shares", type=int, default=100)
    analyze.add_argument("--match", choices=("all", "any"), default="all")
    analyze.add_argument(
        "--missing-metrics",
        choices=("exclude", "include-unverified", "error"),
        default="exclude",
    )
    analyze.add_argument("--no-transcripts", action="store_true")
    analyze.add_argument("--output-dir", type=Path, default=Path("reports/reels-agent"))
    return parser.parse_args(argv)


def doctor(profile: str) -> int:
    token = bool(os.getenv("APIFY_TOKEN"))
    llm = OpenAICompatibleAnalyzer()
    print("Instagram Reels Intelligence Agent")
    print(f"profile: {profile}")
    print(f"APIFY_TOKEN: {'configured' if token else 'MISSING'}")
    print(f"LLM analyzer: {'configured' if llm.enabled else 'deterministic fallback'}")
    print(f"discovery actor: https://apify.com/apify/instagram-reel-scraper")
    print(f"metrics actor: https://apify.com/patient_discovery/instagram-reel-analytics-by-url")
    if not token:
        print("action: set APIFY_TOKEN in the environment; never commit or paste it into source code")
        return 2
    return 0


def run_analyze(args: argparse.Namespace) -> int:
    thresholds = Thresholds(
        min_likes=args.min_likes,
        min_saves=args.min_saves,
        min_shares=args.min_shares,
        match=args.match,
        missing_metrics=args.missing_metrics,
    )
    if args.snapshot:
        profile = args.snapshot.stem.replace("_public_snapshot", "")
        all_reels = load_snapshot(args.snapshot)
    else:
        profile = args.profile
        client = ApifyClient(os.getenv("APIFY_TOKEN", ""))
        all_reels = discover_live(
            client,
            profile=profile,
            max_results=args.max_results,
            transcripts=not args.no_transcripts,
        )
        # Likes are cheap from discovery; enrich only plausible candidates.
        enrichment_candidates = [
            reel for reel in all_reels if reel.likes is None or reel.likes >= thresholds.min_likes
        ]
        enrich_live(client, enrichment_candidates)

    selected: list[Reel] = []
    for reel in all_reels:
        if qualify(reel, thresholds):
            selected.append(reel)
    selected.sort(key=lambda reel: (reel.likes or -1, reel.saves or -1, reel.shares or -1), reverse=True)

    analyses = analyze_reels(selected)
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_payload = {
        "profile": profile,
        "generated_at": generated_at,
        "thresholds": dataclasses.asdict(thresholds),
        "reels": [reel_to_public_dict(reel) for reel in all_reels],
    }
    (output_dir / "all_reels.json").write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    qualified_payload = [
        {**reel_to_public_dict(reel), "analysis": analyses[reel_key(reel)]}
        for reel in selected
    ]
    (output_dir / "qualified_reels.json").write_text(
        json.dumps(qualified_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(output_dir / "qualified_reels.csv", selected)
    markdown = report_markdown(profile, all_reels, selected, analyses, thresholds, generated_at)
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text(
        markdown_to_html(markdown, f"Instagram Reels Intelligence — @{profile}"), encoding="utf-8"
    )

    strict = sum(reel.qualification == "qualified" for reel in selected)
    unverified = sum(reel.qualification == "unverified-candidate" for reel in selected)
    print(f"scanned={len(all_reels)} selected={len(selected)} strict={strict} unverified={unverified}")
    print(f"report={output_dir / 'report.html'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.profile)
        if args.command == "analyze":
            return run_analyze(args)
        raise AgentError(f"Unknown command: {args.command}")
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
