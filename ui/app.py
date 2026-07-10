"""
HeyGen Integration — Streamlit UI
Run: streamlit run ui/app.py
"""

import streamlit as st
import requests

# ── Page Config ───────────────────────────────────────────────

st.set_page_config(
    page_title="HeyGen Integration",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API Client ( talks to local FastAPI ) ─────────────────────

API_BASE = st.sidebar.text_input("API Base URL", value="http://localhost:8000")


def api_get(path: str, params: dict | None = None):
    r = requests.get(f"{API_BASE}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json_data: dict | None = None):
    r = requests.post(f"{API_BASE}{path}", json=json_data, timeout=60)
    r.raise_for_status()
    return r.json()


def api_delete(path: str):
    r = requests.delete(f"{API_BASE}{path}", timeout=60)
    r.raise_for_status()
    return r.json()


# ── Sidebar Navigation ────────────────────────────────────────

st.sidebar.title("🎬 HeyGen")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Dashboard",
        "🎥 Create Video",
        "🤖 Video Agent",
        "🌐 Translate Video",
        "🔊 Text to Speech",
        "📁 My Videos",
        "👤 Avatars",
        "🎙️ Voices",
        "⚙️ Settings",
    ],
)

# ── Dashboard ─────────────────────────────────────────────────

if page == "🏠 Dashboard":
    st.title("HeyGen Integration Dashboard")

    col1, col2, col3 = st.columns(3)

    try:
        health = api_get("/health")
        col1.metric("API Status", "🟢 Online" if health.get("status") == "ok" else "🔴 Error")
    except Exception as e:
        col1.metric("API Status", "🔴 Offline")
        st.error(f"Cannot connect to API: {e}")

    try:
        videos = api_get("/api/v1/videos", params={"limit": 100})
        video_list = videos.get("videos", [])
        total = len(video_list)
        completed = sum(1 for v in video_list if v.get("status") == "completed")
        failed = sum(1 for v in video_list if v.get("status") == "failed")

        col2.metric("Total Videos", total)
        col3.metric("Completed", completed)

        st.markdown("---")
        st.subheader("Recent Videos")
        for v in video_list[:5]:
            status_emoji = {"completed": "✅", "failed": "❌", "processing": "⏳"}.get(
                v.get("status"), "❓"
            )
            with st.container():
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"{status_emoji} `{v.get('video_id', 'N/A')[:20]}...`")
                c2.write(v.get("status", "unknown"))
                if v.get("video_url"):
                    c3.markdown(f"[Watch]({v['video_url']})")
                else:
                    c3.write("—")

        if failed > 0:
            st.warning(f"{failed} video(s) failed. Check the Videos page for details.")

    except Exception as e:
        st.error(f"Failed to load videos: {e}")

# ── Create Video ──────────────────────────────────────────────

elif page == "🎥 Create Video":
    st.title("Create Avatar Video")

    with st.form("video_form"):
        col1, col2 = st.columns(2)

        with col1:
            try:
                avatars = api_get("/api/v1/avatars")
                avatar_list = avatars.get("avatars", [])
                avatar_options = {f"{a['avatar_name']} ({a['avatar_id'][:8]}...)": a["avatar_id"] for a in avatar_list}
                avatar_choice = st.selectbox("Select Avatar", options=list(avatar_options.keys()))
                avatar_id = avatar_options.get(avatar_choice, "")
            except Exception as e:
                st.error(f"Cannot load avatars: {e}")
                avatar_id = st.text_input("Avatar ID (manual)", value="Dylan_expressive_202406")

        with col2:
            try:
                voices = api_get("/api/v1/voices")
                voice_list = voices.get("voices", [])
                voice_options = {f"{v['voice_name']} ({v['language']})": v["voice_id"] for v in voice_list}
                voice_choice = st.selectbox("Select Voice", options=list(voice_options.keys()))
                voice_id = voice_options.get(voice_choice, "")
            except Exception as e:
                st.error(f"Cannot load voices: {e}")
                voice_id = st.text_input("Voice ID (manual)", value="en-US-JennyNeural")

        script = st.text_area("Script (what the avatar will say)", height=150, placeholder="Hello! Welcome to our product demo...")

        col_w, col_h = st.columns(2)
        width = col_w.selectbox("Width", [1920, 1280, 1080], index=0)
        height = col_h.selectbox("Height", [1080, 720, 1920], index=0)

        background = st.text_input("Background (optional)", placeholder="#FFFFFF or image URL", value="")

        submitted = st.form_submit_button("🎬 Generate Video", use_container_width=True, type="primary")

    if submitted:
        if not script.strip():
            st.error("Please enter a script.")
        else:
            with st.spinner("Creating video... This may take a few minutes."):
                try:
                    result = api_post("/api/v1/videos/create", {
                        "avatar_id": avatar_id,
                        "voice_id": voice_id,
                        "script": script,
                        "background": background or None,
                        "dimension": {"width": width, "height": height},
                    })
                    st.success(f"Video submitted! ID: `{result.get('video_id')}`")
                    st.json(result)

                    # Auto-poll
                    if result.get("video_id"):
                        progress_bar = st.progress(0)
                        import time
                        for i in range(60):
                            time.sleep(5)
                            status = api_get(f"/api/v1/videos/{result['video_id']}/status")
                            progress_bar.progress(min((i + 1) / 60, 0.95))
                            if status.get("status") == "completed":
                                progress_bar.progress(1.0)
                                st.success("✅ Video ready!")
                                if status.get("video_url"):
                                    st.video(status["video_url"])
                                    st.markdown(f"[Download MP4]({status['video_url']})")
                                st.json(status)
                                break
                            elif status.get("status") == "failed":
                                st.error(f"❌ Video failed: {status.get('error', 'Unknown error')}")
                                st.json(status)
                                break
                        else:
                            st.info("⏳ Still processing. Check 'My Videos' page later.")

                except Exception as e:
                    st.error(f"Error: {e}")

# ── Video Agent ───────────────────────────────────────────────

elif page == "🤖 Video Agent":
    st.title("Video Agent (Prompt → Video)")
    st.markdown("Describe the video you want, and AI will create it autonomously.")

    prompt = st.text_area(
        "Prompt",
        height=150,
        placeholder="A 30-second product demo video featuring a professional presenter explaining our SaaS platform...",
    )

    if st.button("🚀 Generate with Agent", use_container_width=True, type="primary"):
        if not prompt.strip():
            st.error("Please enter a prompt.")
        else:
            with st.spinner("Video Agent is working... This may take 2-5 minutes."):
                try:
                    result = api_post("/api/v1/videos/agent/create", {"prompt": prompt})
                    st.success(f"Session started! ID: `{result.get('session_id')}`")
                    st.json(result)

                    if result.get("session_id"):
                        progress_bar = st.progress(0)
                        import time
                        for i in range(120):
                            time.sleep(5)
                            status = api_get(f"/api/v1/videos/agent/{result['session_id']}/status")
                            progress_bar.progress(min((i + 1) / 120, 0.95))
                            if status.get("status") == "completed":
                                progress_bar.progress(1.0)
                                st.success("✅ Video ready!")
                                if status.get("video_url"):
                                    st.video(status["video_url"])
                                    st.markdown(f"[Download MP4]({status['video_url']})")
                                st.json(status)
                                break
                            elif status.get("status") == "failed":
                                st.error(f"❌ Failed: {status.get('error', 'Unknown error')}")
                                st.json(status)
                                break
                        else:
                            st.info("⏳ Still processing. Check 'My Videos' page later.")

                except Exception as e:
                    st.error(f"Error: {e}")

# ── Translate Video ───────────────────────────────────────────

elif page == "🌐 Translate Video":
    st.title("Video Translation")
    st.markdown("Translate any video to another language with AI lip-sync.")

    with st.form("translate_form"):
        video_url = st.text_input("Source Video URL", placeholder="https://example.com/video.mp4")

        languages = {
            "Spanish": "es",
            "French": "fr",
            "German": "de",
            "Italian": "it",
            "Portuguese": "pt",
            "Russian": "ru",
            "Chinese (Simplified)": "zh",
            "Japanese": "ja",
            "Korean": "ko",
            "Arabic": "ar",
            "Hindi": "hi",
            "Dutch": "nl",
            "Turkish": "tr",
            "Polish": "pl",
        }
        target_language = st.selectbox("Target Language", options=list(languages.keys()))
        lang_code = languages[target_language]

        mode = st.radio("Mode", ["speed", "precision"], horizontal=True)

        submitted = st.form_submit_button("🌐 Translate", use_container_width=True, type="primary")

    if submitted:
        if not video_url.strip():
            st.error("Please enter a video URL.")
        else:
            with st.spinner("Translating video... This may take several minutes."):
                try:
                    result = api_post("/api/v1/translate", {
                        "video_url": video_url,
                        "target_language": lang_code,
                        "mode": mode,
                    })
                    st.success(f"Translation started! ID: `{result.get('translation_id')}`")
                    st.json(result)
                except Exception as e:
                    st.error(f"Error: {e}")

# ── Text to Speech ────────────────────────────────────────────

elif page == "🔊 Text to Speech":
    st.title("Text to Speech")

    try:
        voices = api_get("/api/v1/voices")
        voice_list = voices.get("voices", [])
        voice_options = {f"{v['voice_name']} ({v['language']})": v["voice_id"] for v in voice_list}
    except Exception:
        voice_options = {}

    with st.form("tts_form"):
        text = st.text_area("Text to convert", height=150, placeholder="Hello, this is a sample text...")
        voice_choice = st.selectbox("Voice", options=list(voice_options.keys()) if voice_options else ["Default"])
        voice_id = voice_options.get(voice_choice, "") if voice_options else st.text_input("Voice ID")
        speed = st.slider("Speed", min_value=0.5, max_value=2.0, value=1.0, step=0.1)

        submitted = st.form_submit_button("🔊 Generate Audio", use_container_width=True, type="primary")

    if submitted:
        if not text.strip():
            st.error("Please enter text.")
        else:
            with st.spinner("Generating audio..."):
                try:
                    result = api_post("/api/v1/tts/create", {
                        "text": text,
                        "voice_id": voice_id,
                        "speed": speed,
                    })
                    st.success(f"Audio created! ID: `{result.get('audio_id')}`")
                    if result.get("audio_url"):
                        st.audio(result["audio_url"])
                    st.json(result)
                except Exception as e:
                    st.error(f"Error: {e}")

# ── My Videos ─────────────────────────────────────────────────

elif page == "📁 My Videos":
    st.title("My Videos")

    try:
        videos = api_get("/api/v1/videos", params={"limit": 50})
        video_list = videos.get("videos", [])

        if not video_list:
            st.info("No videos yet. Create one from the 'Create Video' page.")
        else:
            for v in video_list:
                status_color = {
                    "completed": "🟢",
                    "failed": "🔴",
                    "processing": "🟡",
                    "pending": "⚪",
                }.get(v.get("status"), "⚪")

                with st.container():
                    cols = st.columns([2, 1, 1, 1])
                    cols[0].code(v.get("video_id", "N/A"))
                    cols[1].write(f"{status_color} {v.get('status', 'unknown')}")
                    cols[2].write(f"{v.get('duration', '—')}s" if v.get("duration") else "—")
                    if v.get("video_url"):
                        cols[3].markdown(f"[Watch]({v['video_url']})")
                    else:
                        cols[3].write("—")

                    if v.get("video_url") and v.get("status") == "completed":
                        st.video(v["video_url"], format="video/mp4")

                    st.divider()

    except Exception as e:
        st.error(f"Error loading videos: {e}")

# ── Avatars ───────────────────────────────────────────────────

elif page == "👤 Avatars":
    st.title("Available Avatars")

    try:
        avatars = api_get("/api/v1/avatars")
        avatar_list = avatars.get("avatars", [])

        if not avatar_list:
            st.info("No avatars found.")
        else:
            cols = st.columns(3)
            for i, a in enumerate(avatar_list):
                with cols[i % 3]:
                    with st.container(border=True):
                        if a.get("preview_image_url"):
                            st.image(a["preview_image_url"], use_container_width=True)
                        st.markdown(f"**{a.get('avatar_name', 'Unnamed')}**")
                        st.caption(f"ID: `{a['avatar_id']}`")
                        st.caption(f"Gender: {a.get('gender', '—')}")
                        if a.get("preview_video_url"):
                            st.markdown(f"[Preview]({a['preview_video_url']})")

    except Exception as e:
        st.error(f"Error loading avatars: {e}")

# ── Voices ────────────────────────────────────────────────────

elif page == "🎙️ Voices":
    st.title("Available Voices")

    try:
        voices = api_get("/api/v1/voices")
        voice_list = voices.get("voices", [])

        if not voice_list:
            st.info("No voices found.")
        else:
            search = st.text_input("Filter by language", placeholder="e.g. en, ru, es")
            filtered = [v for v in voice_list if not search or search.lower() in v.get("language", "").lower()]

            st.write(f"Showing {len(filtered)} voice(s)")
            for v in filtered:
                with st.container(border=True):
                    st.markdown(f"**{v.get('voice_name', 'Unnamed')}**")
                    st.caption(f"ID: `{v['voice_id']}` | Language: {v.get('language', '—')} | Gender: {v.get('gender', '—')}")
                    if v.get("preview_audio_url"):
                        st.audio(v["preview_audio_url"])

    except Exception as e:
        st.error(f"Error loading voices: {e}")

# ── Settings ──────────────────────────────────────────────────

elif page == "⚙️ Settings":
    st.title("Settings")

    st.subheader("API Configuration")
    st.info("API settings are managed via environment variables on the server.")

    st.markdown("**Required environment variables:**")
    st.code("""
HEYGEN_API_KEY=your_api_key_here
HEYGEN_BASE_URL=https://api.heygen.com
    """)

    st.markdown("**Optional:**")
    st.code("""
WEBHOOK_URL=https://your-domain.com/api/v1/webhooks/heygen
CALLBACK_URL=https://your-domain.com/api/v1/webhooks/heygen
DEBUG=false
PORT=8000
UI_PORT=8501
    """)

    st.subheader("Quick Start")
    st.code("""
# 1. Set your API key
export HEYGEN_API_KEY=your_key_here

# 2. Start the API server
python -m api.server

# 3. Start the UI (in another terminal)
streamlit run ui/app.py
    """)
