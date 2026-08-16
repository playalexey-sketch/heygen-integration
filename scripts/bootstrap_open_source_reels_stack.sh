#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---base}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${REELS_VENV:-$ROOT/.venv-reels}"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip

# Versions are pinned to commits inspected while building the agent.
"$VENV/bin/pip" install \
  "git+https://github.com/instaloader/instaloader.git@5434692" \
  "git+https://github.com/parthmax2/parth-dl.git@5cc1525"

if [[ "$MODE" == "--transcription" ]]; then
  "$VENV/bin/pip" install \
    "git+https://github.com/Overusedhydra/reels-vault.git@959c120"
  if ! command -v ffmpeg >/dev/null; then
    echo "ffmpeg is required for local audio extraction" >&2
    exit 2
  fi
fi

cat <<EOF
Open-source Reels stack installed in: $VENV

Doctor:
  $VENV/bin/python $ROOT/open_source_reels_agent.py doctor

Public profile scrape:
  $VENV/bin/python $ROOT/open_source_reels_agent.py run \\
    --profile bartsevmatvei --max-results 1000 \\
    --output-dir $ROOT/deliverables/open_source_reels_live

With local Whisper transcription:
  $VENV/bin/python $ROOT/open_source_reels_agent.py run \\
    --profile bartsevmatvei --max-results 1000 --transcribe \\
    --cookies-from chrome --whisper-model small \\
    --output-dir $ROOT/deliverables/open_source_reels_live

Use an existing session file or browser cookies locally if Instagram serves a login wall.
Never commit session files or cookies.
EOF
