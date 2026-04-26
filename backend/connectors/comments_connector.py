import logging
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httplib2
from yt_dlp.utils import DownloadError  # pyright: ignore[reportMissingModuleSource]

try:
    from backend.config import (
        COMMENT_SAMPLE_SIZE,
        ENABLE_YTDLP_COMMENT_FALLBACK,
        REQUEST_TIMEOUT_SECONDS,
        YOUTUBE_API_KEY,
    )  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import (
        COMMENT_SAMPLE_SIZE,
        ENABLE_YTDLP_COMMENT_FALLBACK,
        REQUEST_TIMEOUT_SECONDS,
        YOUTUBE_API_KEY,
    )

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")
MULTISPACE_RE = re.compile(r"\s+")
SPAM_HINTS = (
    "whatsapp",
    "telegram",
    "subscribe",
    "giveaway",
    "dm me",
    "check my channel",
)

_youtube_client = None


def _get_youtube_client():
    global _youtube_client
    if not YOUTUBE_API_KEY:
        return None
    if _youtube_client is None:
        http = httplib2.Http(timeout=REQUEST_TIMEOUT_SECONDS)
        _youtube_client = build(
            "youtube",
            "v3",
            developerKey=YOUTUBE_API_KEY,
            http=http,
            cache_discovery=False,
        )
    return _youtube_client


def get_video_comments(video_id: str, max_results: int | None = None) -> dict:
    result = _get_comments_via_api(video_id, max_results)
    if result.get("available") or not YOUTUBE_API_KEY:
        return result

    if not ENABLE_YTDLP_COMMENT_FALLBACK:
        logger.info(
            "YouTube API comments failed; yt-dlp fallback disabled (error: %s)",
            result.get("error", "unknown"),
        )
        return result

    if not _should_use_ytdlp_fallback(result):
        logger.info(
            "Skipping yt-dlp comments fallback for non-recoverable API error: %s",
            result.get("error", "unknown"),
        )
        return result

    logger.info(
        "YouTube API comments failed (error: %s), falling back to yt-dlp",
        result.get("error", "unknown"),
    )
    ytdlp_result = _get_comments_via_ytdlp(video_id, max_results)
    if ytdlp_result.get("available"):
        ytdlp_result["source"] = "ytdlp"
        return ytdlp_result

    return result


def _get_comments_via_api(video_id: str, max_results: int | None = None) -> dict:
    if not YOUTUBE_API_KEY:
        return {
            "available": False,
            "total_fetched": 0,
            "usable_comments": [],
            "spam_like_count": 0,
            "error": "YOUTUBE_API_KEY is missing",
        }

    youtube = _get_youtube_client()
    if youtube is None:
        return {
            "available": False,
            "total_fetched": 0,
            "usable_comments": [],
            "spam_like_count": 0,
            "error": "YOUTUBE_API_KEY is missing",
        }

    target = min(max_results or COMMENT_SAMPLE_SIZE, 100)

    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=target,
            order="relevance",
            textFormat="plainText",
            fields="items(snippet/topLevelComment/snippet/textDisplay,snippet/topLevelComment/snippet/textOriginal)",
        )
        response = request.execute()
    except HttpError as err:
        error_detail = _parse_http_error(err)
        return {
            "available": False,
            "total_fetched": 0,
            "usable_comments": [],
            "spam_like_count": 0,
            "error": error_detail,
            "error_status": err.resp.status,
        }

    items = response.get("items", [])
    raw_comments = []
    for item in items:
        snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = snippet.get("textDisplay") or snippet.get("textOriginal") or ""
        if text:
            raw_comments.append(text)

    usable, spam_like_count = _preprocess_comments(raw_comments)

    return {
        "available": True,
        "total_fetched": len(raw_comments),
        "usable_comments": usable,
        "spam_like_count": spam_like_count,
        "error": None,
        "error_status": None,
    }


def get_video_statistics(video_id: str) -> dict | None:
    if not YOUTUBE_API_KEY:
        return None

    youtube = _get_youtube_client()
    if youtube is None:
        return None

    try:
        request = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id,
            fields="items(snippet(title,description,publishedAt,channelId,channelTitle,tags),statistics(viewCount,likeCount,commentCount),contentDetails/duration)",
        )
        response = request.execute()
    except HttpError:
        return None

    items = response.get("items", [])
    if not items:
        return None

    return items[0]


def get_channel_stats(channel_id: str) -> dict | None:
    if not YOUTUBE_API_KEY:
        return None

    youtube = _get_youtube_client()
    if youtube is None:
        return None

    try:
        request = youtube.channels().list(
            part="snippet,statistics",
            id=channel_id,
            fields="items(statistics(subscriberCount,videoCount),snippet/publishedAt)",
        )
        response = request.execute()
    except HttpError:
        return None

    items = response.get("items", [])
    if not items:
        return None

    return items[0]


def _parse_http_error(err: HttpError) -> str:
    status = err.resp.status
    if status == 403:
        return (
            "YouTube API key is blocked or has incorrect restrictions. "
            "Check: 1) YouTube Data API v3 is enabled, "
            "2) IP restrictions include your server IP, "
            "3) Key is not restricted to browser refs only."
        )
    if status == 400:
        return f"Bad request to YouTube API: {err}"
    return f"YouTube API error ({status}): {err}"


def _should_use_ytdlp_fallback(api_result: dict) -> bool:
    status = api_result.get("error_status")
    if isinstance(status, int):
        if status in (400, 401, 403, 404):
            return False
        if status in (429, 500, 502, 503, 504):
            return True
    return True


def _get_comments_via_ytdlp(video_id: str, max_results: int | None = None) -> dict:
    import yt_dlp  # pyright: ignore[reportMissingModuleSource]

    target = min(max_results or COMMENT_SAMPLE_SIZE, 100)
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_comments": True,
        "getcomments": True,
        "socket_timeout": REQUEST_TIMEOUT_SECONDS,
        "retries": 1,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            comments = info.get("comments") or []
    except (DownloadError, Exception) as exc:
        logger.warning("yt-dlp comment extraction failed for %s: %s", video_id, exc)
        return {
            "available": False,
            "total_fetched": 0,
            "usable_comments": [],
            "spam_like_count": 0,
            "error": f"yt-dlp fallback failed: {exc}",
        }

    raw_comments = []
    for comment in comments[:target]:
        text = comment.get("text", "") or comment.get("content", "") or ""
        if text:
            raw_comments.append(text)

    if not raw_comments:
        return {
            "available": False,
            "total_fetched": 0,
            "usable_comments": [],
            "spam_like_count": 0,
            "error": "yt-dlp returned no comments (video may have comments disabled)",
        }

    usable, spam_like_count = _preprocess_comments(raw_comments)

    return {
        "available": True,
        "total_fetched": len(raw_comments),
        "usable_comments": usable,
        "spam_like_count": spam_like_count,
        "error": None,
    }


def _preprocess_comments(comments: list[str]) -> tuple[list[str], int]:
    cleaned_unique = []
    seen = set()
    spam_like_count = 0

    for text in comments:
        cleaned = _clean_comment(text)
        if not cleaned:
            continue
        if cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())

        if _is_spam_like(cleaned):
            spam_like_count += 1
            continue

        cleaned_unique.append(cleaned)

    return cleaned_unique, spam_like_count


def _clean_comment(text: str) -> str:
    normalized = URL_RE.sub("", text)
    normalized = MULTISPACE_RE.sub(" ", normalized).strip()
    if len(normalized) < 8:
        return ""
    return normalized


def _is_spam_like(text: str) -> bool:
    lowered = text.lower()
    if any(hint in lowered for hint in SPAM_HINTS):
        return True
    if lowered.count("!") >= 5:
        return True
    return False
