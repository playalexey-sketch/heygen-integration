"""
Photo → Video agent — Streamlit page (цифровой аватар на фото + озвучка).

Upload a photo and a voice, pick settings, get a ~15 second video.
"""

import requests
import streamlit as st


def render(api_base: str = "http://localhost:8000") -> None:
    """Render the photo-avatar video page."""
    st.title("📸 Фото → Видео (цифровой аватар)")
    st.markdown(
        "Загрузите **фото** человека и **озвучку** (или текст). "
        "Получите видео ~15 секунд, где человек на фото говорит вашим голосом."
    )

    # ── Voice mode ────────────────────────────────────────────
    voice_mode = st.radio(
        "Как задать озвучку?",
        ["🎤 Загрузить аудио (аватар повторит голос)",
         "📝 Текст + голос из библиотеки",
         "🎛️ Клонировать мой голос + текст"],
        horizontal=True,
    )

    col_photo, col_settings = st.columns([1, 1])

    with col_photo:
        st.subheader("1️⃣ Фото")
        photo = st.file_uploader(
            "Портрет человека (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            key="pv_photo",
        )
        if photo:
            st.image(photo, caption="Ваш цифровой аватар", use_container_width=True)

        st.subheader("2️⃣ Озвучка")
        audio = None
        script = ""
        voice_id = ""
        if "Аудио" in voice_mode:
            audio = st.file_uploader(
                "Аудио-дорожка (mp3/wav, ~15 сек)",
                type=["mp3", "wav", "m4a", "aac"],
                key="pv_audio",
            )
            if audio:
                st.audio(audio, format="audio/mp3")
        elif "Клонировать" in voice_mode:
            audio = st.file_uploader(
                "Образец вашего голоса (mp3/wav, 1–2 мин)",
                type=["mp3", "wav", "m4a", "aac"],
                key="pv_clone_audio",
            )
            script = st.text_area("Текст, который скажет аватар", key="pv_clone_script")
        else:  # текст + голос из библиотеки
            script = st.text_area(
                "Текст, который скажет аватар (уложите в ~15 сек)",
                key="pv_script",
            )
            voice_id = _pick_voice(api_base)

    # ── Settings ──────────────────────────────────────────────
    with col_settings:
        st.subheader("3️⃣ Настройки видео")
        duration = st.slider(
            "Целевая длительность (сек)", 5, 60, 15, 5,
            help="Для загруженного аудио длина видео = длина аудио. Текст подгоняется под длительность.",
        )
        aspect_ratio = st.selectbox(
            "Соотношение сторон",
            ["16:9", "9:16", "1:1", "auto"],
            help="16:9 — горизонтально, 9:16 — вертикально (Shorts/Reels), 1:1 — квадрат",
        )
        resolution = st.selectbox("Разрешение", ["1080p", "720p"])
        background = st.text_input(
            "Фон (цвет #RRGGBB или URL картинки)", value="", placeholder="#FFFFFF",
            help="Оставьте пустым для авто-фона",
        )
        motion_prompt = st.text_input(
            "Движение/жесты (для Avatar IV)", value="",
            placeholder="напр. 'speaking to camera, subtle nod'",
        )

    if st.button("🚀 Создать видео", type="primary", use_container_width=True):
        if photo is None:
            st.error("Загрузите фото.")
            return
        if audio is None and not script.strip():
            st.error("Загрузите аудио или введите текст.")
            return

        files = {"photo": (photo.name, photo.getvalue(), "image/" + photo.name.rsplit(".", 1)[-1])}
        if audio is not None:
            files["audio"] = (audio.name, audio.getvalue(), _audio_mime(audio.name))

        data = {
            "name": "My Photo Avatar",
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration_seconds": duration,
            "title": "Photo Avatar Video",
            "wait": "true",
        }
        if background.strip():
            data["background"] = background.strip()
        if motion_prompt.strip():
            data["motion_prompt"] = motion_prompt.strip()
        if "Текст" in voice_mode or "Клонировать" in voice_mode:
            data["script"] = script
            if voice_id:
                data["voice_id"] = voice_id
            if "Клонировать" in voice_mode:
                data["clone_voice"] = "true"
                data["voice_name"] = "My Voice"

        with st.spinner("Создаю видео… это может занять несколько минут."):
            try:
                resp = requests.post(
                    f"{api_base}/api/v1/photo/video",
                    files=files,
                    data=data,
                    timeout=600,
                )
                if resp.status_code != 200:
                    st.error(resp.text)
                    return
                result = resp.json()
            except Exception as e:  # noqa: BLE001
                st.error(f"Ошибка подключения к API: {e}")
                return

        if result.get("video_url"):
            st.success("✅ Видео готово!")
            st.video(result["video_url"])
            st.markdown(f"[⬇️ Скачать MP4]({result['video_url']})")
            st.caption(f"avatar_id: `{result.get('avatar_id')}`")
        else:
            st.info("Видео создаётся. Информация по запросу:")
            st.json(result)


def _pick_voice(api_base: str) -> str:
    """Return a voice_id chosen from the library, or '' if unavailable."""
    try:
        r = requests.get(f"{api_base}/api/v1/voices", timeout=30)
        r.raise_for_status()
        voices = r.json().get("voices", [])
        if not voices:
            st.info("Голоса из библиотеки недоступны — можно загрузить аудио.")
            return ""
        options = {f"{v['voice_name']} ({v['language']})": v["voice_id"] for v in voices}
        choice = st.selectbox("Голос", list(options.keys()))
        return options[choice]
    except Exception:  # noqa: BLE001
        st.info("Не удалось загрузить список голосов.")
        return ""


def _audio_mime(name: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
    }.get(name.rsplit(".", 1)[-1].lower(), "audio/mpeg")
