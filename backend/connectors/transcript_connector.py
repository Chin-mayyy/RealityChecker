import yt_dlp  # pyright: ignore[reportMissingModuleSource]

try:
    from backend.config import REQUEST_TIMEOUT_SECONDS  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import REQUEST_TIMEOUT_SECONDS


def get_video_transcript(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "socket_timeout": REQUEST_TIMEOUT_SECONDS,
        "retries": 1,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # pyright: ignore[reportArgumentType, reportUndefinedVariable]
        info = ydl.extract_info(url, download=False)
        captions = info.get("subtitles") or {}
        auto_captions = info.get("automatic_captions") or {}

        language, source = _pick_caption_language(captions, auto_captions)
        transcript_text = _build_transcript_placeholder(info, language)

        return {
            "available": bool(language and transcript_text),
            "source": source,
            "language": language,
            "text": transcript_text,
            "chunks": _chunk_text(transcript_text),
        }


def _pick_caption_language(
    captions: dict, auto_captions: dict
) -> tuple[str | None, str | None]:
    preferred = ("en", "en-US", "en-GB")

    for key in preferred:
        if key in captions:
            return key, "manual"
    for key in preferred:
        if key in auto_captions:
            return key, "auto"

    if captions:
        first = next(iter(captions.keys()))
        return first, "manual"
    if auto_captions:
        first = next(iter(auto_captions.keys()))
        return first, "auto"

    return None, None


def _build_transcript_placeholder(info: dict, language: str | None) -> str:
    if not language:
        return ""
    description = (info.get("description") or "").strip()
    title = (info.get("title") or "").strip()
    tags = " ".join(info.get("tags") or [])

    merged = " ".join(part for part in (title, description, tags) if part)
    return merged.strip()


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    if not text:
        return []
    words = text.split()
    chunks = []
    current = []
    current_len = 0

    for word in words:
        current.append(word)
        current_len += len(word) + 1
        if current_len >= chunk_size:
            chunks.append(" ".join(current))
            current = []
            current_len = 0

    if current:
        chunks.append(" ".join(current))

    return chunks
