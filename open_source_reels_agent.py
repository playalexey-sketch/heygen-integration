#!/usr/bin/env python3
"""Open-source Instagram Reels scraping + transcription agent.

Open-source stack:
- Instaloader (MIT): enumerate every Reel exposed by a public profile.
- Reels Vault (MIT): yt-dlp/Playwright download and local Whisper transcript.
- parth-dl (MIT): zero-dependency single-Reel metadata fallback.

The agent never asks for or stores an Instagram password. An optional existing
Instaloader session file / browser cookie source can be supplied locally.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

import instagram_reels_agent as core

STACK = {
    "instaloader": {
        "repo": "https://github.com/instaloader/instaloader",
        "commit": "5434692",
        "license": "MIT",
        "role": "profile Reel enumeration and public metadata",
    },
    "reels-vault": {
        "repo": "https://github.com/Overusedhydra/reels-vault",
        "commit": "959c120",
        "license": "MIT",
        "role": "video download, FFmpeg audio extraction and local Whisper transcript",
    },
    "parth-dl": {
        "repo": "https://github.com/parthmax2/parth-dl",
        "commit": "5cc1525",
        "license": "MIT",
        "role": "zero-dependency metadata/download fallback for individual public Reel URLs",
    },
}


class OpenSourceStackError(core.AgentError):
    pass


def optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def post_node_value(post: Any, *keys: str) -> Any:
    node = getattr(post, "_node", {}) or {}
    for key in keys:
        if isinstance(node, dict) and node.get(key) is not None:
            return node[key]
    return None


def safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
        return value() if callable(value) and name.startswith("get_") else value
    except Exception:
        return default


def post_to_reel(post: Any, username: str) -> core.Reel:
    shortcode = str(safe_attr(post, "shortcode", "") or "")
    date_value = safe_attr(post, "date_utc", None) or safe_attr(post, "date", None)
    if hasattr(date_value, "isoformat"):
        published_at = date_value.isoformat()
    else:
        published_at = str(date_value or "")
    plays = core.to_int(
        safe_attr(post, "video_play_count", None)
        or post_node_value(post, "video_play_count", "play_count", "ig_play_count")
        or safe_attr(post, "video_view_count", None)
    )
    duration = core.to_float(
        safe_attr(post, "video_duration", None)
        or post_node_value(post, "video_duration", "duration")
    )
    return core.Reel(
        shortcode=shortcode,
        url=f"https://www.instagram.com/reel/{shortcode}/" if shortcode else "",
        owner_username=username,
        caption=str(safe_attr(post, "caption", "") or ""),
        published_at=published_at,
        duration_seconds=duration,
        likes=core.to_int(safe_attr(post, "likes", None)),
        comments=core.to_int(safe_attr(post, "comments", None)),
        plays=plays,
        saves=None,
        shares=None,
        is_pinned=post_node_value(post, "is_pinned"),
        video_url=str(safe_attr(post, "video_url", "") or ""),
        thumbnail_url=str(safe_attr(post, "url", "") or ""),
        source="instaloader:open-source",
        raw={"node": getattr(post, "_node", {}) or {}},
    )


class InstaloaderEnumerator:
    def __init__(self, session_file: Path | None = None, session_user: str | None = None) -> None:
        module = optional_import("instaloader")
        if module is None:
            raise OpenSourceStackError(
                "Instaloader is not installed. Run scripts/bootstrap_open_source_reels_stack.sh --base"
            )
        self.module = module
        self.loader = module.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
            max_connection_attempts=3,
            request_timeout=60,
        )
        if session_file:
            if not session_user:
                raise OpenSourceStackError("--session-user is required with --session-file")
            self.loader.load_session_from_file(session_user, filename=str(session_file))

    def enumerate(self, username: str, max_results: int) -> list[core.Reel]:
        profile = self.module.Profile.from_username(self.loader.context, username)
        reels: list[core.Reel] = []
        for post in profile.get_reels():
            reels.append(post_to_reel(post, username))
            if len(reels) >= max_results:
                break
        return core.deduplicate(reels)


class SingleReelFallback:
    def __init__(self) -> None:
        self.parth = optional_import("parth_dl")

    @property
    def available(self) -> bool:
        return self.parth is not None

    def enrich(self, reel: core.Reel) -> core.Reel:
        if not self.parth:
            return reel
        try:
            info = self.parth.get_info(reel.url)
        except Exception as exc:
            print(f"warning: parth-dl failed for {reel.shortcode}: {exc}", file=sys.stderr)
            return reel
        if not isinstance(info, dict):
            return reel
        enriched = core.normalize_reel(info, "parth-dl:open-source")
        return core.merge_reels(reel, enriched)


class LocalTranscriber:
    def __init__(self, whisper_model: str, cookies_from: str | None, session_file: Path | None) -> None:
        self.whisper_model = whisper_model
        self.cookies_from = cookies_from
        self.session_file = str(session_file) if session_file else None
        try:
            self.extract = importlib.import_module("reels_vault.extract")
        except Exception:
            self.extract = None

    @property
    def available(self) -> bool:
        return self.extract is not None and shutil.which("ffmpeg") is not None

    def transcribe(self, reel: core.Reel, work_root: Path) -> core.Reel:
        if not self.available:
            raise OpenSourceStackError(
                "Reels Vault/Whisper/FFmpeg stack is unavailable. Run bootstrap with --transcription."
            )
        output_dir = work_root / reel.shortcode
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path, metadata = self.extract.extract_metadata(
            reel.url,
            str(output_dir),
            cookies_from=self.cookies_from,
            session_file=self.session_file,
        )
        audio_path = self.extract.extract_audio(video_path, str(output_dir))
        transcript = self.extract.transcribe(audio_path, self.whisper_model)
        reel.transcript = str(transcript.get("text", ""))
        reel.raw = {
            **reel.raw,
            "local_transcript": transcript,
            "reels_vault_metadata": metadata,
        }
        if metadata:
            core.merge_reels(reel, core.normalize_reel(metadata, "reels-vault:open-source"))
        reel.source = ",".join(part for part in [reel.source, "reels-vault:open-source"] if part)
        return reel


def snapshot_reels(path: Path) -> list[core.Reel]:
    return core.load_snapshot(path)


def report_all_reels(
    profile: str,
    reels: list[core.Reel],
    output_dir: Path,
    stack_status: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    reels.sort(key=lambda r: (r.likes or -1), reverse=True)
    analyses = core.analyze_reels(reels)
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    for reel in reels:
        reel.qualification = "scraped" if reel.transcript else "metadata-only"
        reel.qualification_reason = (
            "open-source local transcript available"
            if reel.transcript
            else "caption/metadata only; exact transcript unavailable"
        )

    payload = {
        "profile": profile,
        "generated_at": generated_at,
        "open_source_stack": STACK,
        "stack_status": stack_status,
        "limitations": {
            "saves": "not exposed by public open-source profile scraping",
            "shares": "not exposed reliably by public open-source profile scraping",
            "transcript": "exact only when video download and local Whisper succeeded",
        },
        "reels": [
            {**core.reel_to_public_dict(reel), "analysis": analyses[core.reel_key(reel)]}
            for reel in reels
        ],
    }
    (output_dir / "open_source_reels.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fields = [
        "shortcode", "url", "published_at", "duration_seconds", "likes", "comments",
        "plays", "saves", "shares", "transcript_status", "source",
    ]
    with (output_dir / "open_source_reels.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for reel in reels:
            public = core.reel_to_public_dict(reel)
            writer.writerow(
                {
                    **{key: public.get(key) for key in fields if key != "transcript_status"},
                    "transcript_status": "exact-local" if reel.transcript else "unavailable",
                }
            )

    # Reuse the detailed report renderer. Private metrics remain n/a rather than zero.
    thresholds = core.Thresholds(
        min_likes=0,
        min_saves=0,
        min_shares=0,
        match="any",
        missing_metrics="include-unverified",
    )
    for reel in reels:
        reel.qualification = "open-source-exact" if reel.transcript else "open-source-metadata"
    markdown = core.report_markdown(profile, reels, reels, analyses, thresholds, generated_at)
    preface = (
        f"# Open-source scrape status\n\n"
        f"- Instaloader: {'available' if stack_status['instaloader'] else 'missing'}\n"
        f"- Reels Vault: {'available' if stack_status['reels_vault'] else 'missing'}\n"
        f"- parth-dl: {'available' if stack_status['parth_dl'] else 'missing'}\n"
        f"- Exact local transcripts: {sum(bool(r.transcript) for r in reels)} / {len(reels)}\n\n"
        "> Missing saves/shares are not zero. They remain n/a.\n\n---\n\n"
    )
    markdown = preface + markdown
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text(
        core.markdown_to_html(markdown, f"Open-source Reels report — @{profile}"),
        encoding="utf-8",
    )


def doctor() -> int:
    checks = {
        "instaloader": optional_import("instaloader") is not None,
        "reels_vault": optional_import("reels_vault.extract") is not None,
        "parth_dl": optional_import("parth_dl") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "yt-dlp": shutil.which("yt-dlp") is not None,
    }
    print(json.dumps({"stack": STACK, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if checks["instaloader"] else 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open-source Instagram Reels scraper/transcriber")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    run = sub.add_parser("run")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile")
    source.add_argument("--snapshot", type=Path)
    run.add_argument("--max-results", type=int, default=1000)
    run.add_argument("--session-file", type=Path)
    run.add_argument("--session-user")
    run.add_argument("--cookies-from", help="Browser name for Reels Vault/yt-dlp, e.g. chrome")
    run.add_argument("--transcribe", action="store_true")
    run.add_argument("--whisper-model", default="base")
    run.add_argument("--work-dir", type=Path, default=Path(".reels-work"))
    run.add_argument("--output-dir", type=Path, default=Path("deliverables/open_source_reels_result"))
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    checks = {
        "instaloader": optional_import("instaloader") is not None,
        "reels_vault": optional_import("reels_vault.extract") is not None,
        "parth_dl": optional_import("parth_dl") is not None,
    }
    if args.snapshot:
        profile = args.snapshot.stem.replace("_public_snapshot", "")
        reels = snapshot_reels(args.snapshot)
    else:
        profile = args.profile.strip("/").split("/")[-1].split("?")[0]
        enumerator = InstaloaderEnumerator(args.session_file, args.session_user)
        reels = enumerator.enumerate(profile, args.max_results)
        fallback = SingleReelFallback()
        if fallback.available:
            reels = [fallback.enrich(reel) for reel in reels]

    if args.transcribe:
        transcriber = LocalTranscriber(args.whisper_model, args.cookies_from, args.session_file)
        for index, reel in enumerate(reels, 1):
            print(f"transcribe {index}/{len(reels)} {reel.shortcode}")
            try:
                transcriber.transcribe(reel, args.work_dir)
            except Exception as exc:
                print(f"warning: transcript failed for {reel.shortcode}: {exc}", file=sys.stderr)

    report_all_reels(profile, reels, args.output_dir, checks)
    print(f"reels={len(reels)} exact_transcripts={sum(bool(r.transcript) for r in reels)}")
    print(f"report={args.output_dir / 'report.html'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        return run(args)
    except core.AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
