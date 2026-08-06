# 🎬 HeyGen Integration

Full-featured Python integration for [HeyGen](https://www.heygen.com/) AI Video API.
Create avatar videos, translate videos, generate speech — all from code or a web UI.

> **You only need to add your HeyGen API key.** Everything else works out of the box.

---

## Features

| Feature | Description |
|---------|-------------|
| 🎥 **Avatar Video** | Create videos with specific avatar + voice + script |
| 📸 **Photo → Video** | Turn a photo + voice/script into a ~15s talking-avatar video |
| 🤖 **Video Agent** | Prompt-based autonomous video generation |
| 🌐 **Video Translation** | Translate videos to 40+ languages with lip-sync |
| 🔊 **Text-to-Speech** | Convert text to natural speech |
| 👤 **Avatars & Voices** | Browse and select from all available assets |
| 📡 **Webhooks** | Receive async completion callbacks |
| 🖥️ **Streamlit UI** | Full visual interface for non-coders |
| 🔌 **FastAPI** | REST API for integration into any stack |

---

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/playalexey-sketch/heygen-integration.git
cd heygen-integration

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Add Your API Key

```bash
cp .env.example .env
# Edit .env and set: HEYGEN_API_KEY=your_key_here
```

Get your API key at [app.heygen.com/settings/api](https://app.heygen.com/settings/api).

### 3. Start the API Server

```bash
python -m api.server
```

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 4. Start the UI (optional, another terminal)

```bash
streamlit run ui/app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Usage from Python

### Direct SDK

```python
from heygen_client import HeyGenClient

client = HeyGenClient()  # reads HEYGEN_API_KEY from env

# Create avatar video
video = client.create_avatar_video(
    avatar_id="Dylan_expressive_202406",
    voice_id="en-US-JennyNeural",
    script="Hello! Welcome to our product demo.",
)
print(f"Video ID: {video.video_id}")

# Wait for completion
result = client.poll_video(video.video_id)
print(f"Video URL: {result.video_url}")
```

### AI Agent Tools (import and call directly)

```python
from heygen_tools import (
    heygen_create_video,
    heygen_create_video_agent,
    heygen_list_avatars,
    heygen_list_voices,
    heygen_translate_video,
    heygen_text_to_speech,
)

# Create video with auto-selected avatar/voice
video = heygen_create_video(
    script="Hello world! This is my first AI video.",
    wait=True,  # blocks until ready
)
print(video["video_url"])

# Video Agent — describe what you want
video = heygen_create_video_agent(
    prompt="A 30-second product demo for a fitness app",
    wait=True,
)

# List resources
avatars = heygen_list_avatars()
voices = heygen_list_voices(language="en")

# Translate
result = heygen_translate_video(
    video_url="https://example.com/video.mp4",
    target_language="es",
)

# Text to speech
audio = heygen_text_to_speech("Hello, this is a test.")
```

### Photo → Video agent (фото + голос → видео)

Turn a **photo** of a person into a digital avatar and make it speak your
**voice** in a ~15 second video. Pass a photo and one of: an audio file
(avatar lip-syncs it), a script + `voice_id`, or `clone_voice_from` (your voice
is cloned and reads the script).

```python
from photo_video_agent import build_video_from_photo

result = build_video_from_photo(
    photo_path="me.jpg",       # portrait photo (PNG/JPG)
    audio_path="voice.mp3",    # voiceover, ~15s   (OR)
    # script="Hi! This is me.", voice_id="en-US-JennyNeural",  # text mode
    # clone_voice_from="voice.mp3", script="Hi! This is me.",   # clone mode
    duration_seconds=15,
    resolution="1080p",        # or "720p"
    aspect_ratio="16:9",       # "16:9" / "9:16" / "1:1" / "auto"
    wait=True,
)
print(result["video_url"])
```

Or from the command line:

```bash
python photo_video_agent.py --photo me.jpg --audio voice.mp3 --duration 15 --out video.mp4
python photo_video_agent.py --photo me.jpg --script "Hi! This is me." --voice-id en-US-JennyNeural
```

> Note: for audio-driven videos the output length equals the audio length, so
> trim the audio to ~15s beforehand. For text mode the agent pads the script to
> roughly match the requested duration.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/avatars` | List avatars |
| GET | `/api/v1/avatars/{id}` | Avatar details |
| GET | `/api/v1/voices` | List voices |
| POST | `/api/v1/videos/create` | Create avatar video |
| GET | `/api/v1/videos/{id}/status` | Video status |
| GET | `/api/v1/videos/{id}/poll` | Poll until ready |
| DELETE | `/api/v1/videos/{id}` | Delete video |
| GET | `/api/v1/videos` | List videos |
| POST | `/api/v1/videos/agent/create` | Video Agent |
| GET | `/api/v1/videos/agent/{id}/status` | Agent status |
| POST | `/api/v1/translate` | Translate video |
| POST | `/api/v1/tts/create` | Text-to-speech |
| POST | `/api/v1/photo/video` | Photo + voice → talking avatar video (multipart) |
| POST | `/api/v1/photo/asset` | Upload an asset (image/audio) → asset_id |
| POST | `/api/v1/photo/avatar` | Create a photo avatar |
| POST | `/api/v1/photo/voice/clone` | Clone a voice from audio |
| POST | `/api/v1/webhooks/heygen` | Webhook receiver |
| GET | `/api/v1/webhooks/events` | Recent webhook events |

Full OpenAPI docs at `/docs` when server is running.

---

## Project Structure

```
heygen-integration/
├── config.py              # Environment configuration
├── heygen_client.py       # Python SDK for HeyGen API
├── heygen_tools.py        # AI-agent ready functions
├── requirements.txt       # Dependencies
├── .env.example           # Environment template
├── api/
│   ├── server.py          # FastAPI application
│   ├── webhooks.py        # Webhook receiver
│   └── routes/
│       ├── avatars.py     # Avatar endpoints
│       ├── voices.py      # Voice endpoints
│       ├── videos.py      # Video CRUD + Agent
│       ├── translate.py   # Translation endpoints
│       ├── tts.py         # TTS endpoints
│       └── photo.py       # Photo → Video agent endpoints
├── models/
│   └── schemas.py         # Pydantic data models
├── ui/
│   ├── app.py             # Streamlit interface
│   └── photo_avatar.py    # Photo → Video agent page
├── photo_video_agent.py   # Standalone photo→video agent (CLI + function)
└── utils/
    └── helpers.py         # Utilities
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HEYGEN_API_KEY` | ✅ | Your HeyGen API key |
| `HEYGEN_BASE_URL` | ❌ | API base (default: `https://api.heygen.com`) |
| `WEBHOOK_URL` | ❌ | Public URL for receiving webhooks |
| `HOST` | ❌ | Server host (default: `0.0.0.0`) |
| `PORT` | ❌ | Server port (default: `8000`) |

---

## HeyGen Pricing Reference

| Model | Starting Price | Use Case |
|-------|---------------|----------|
| Video Agent | $0.0333/sec | Prompt → polished video |
| Avatar Video | $0.05-0.0667/sec | Avatar + script video |
| Video Translation | $0.0333-0.0667/sec | Lip-sync translation |
| Text-to-Speech | $0.000667/sec | Voice generation |

Top up at [app.heygen.com/settings/api](https://app.heygen.com/settings/api).

---

## License

MIT
