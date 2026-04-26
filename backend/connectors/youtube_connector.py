import yt_dlp  # pyright: ignore[reportMissingModuleSource]

try:
    from backend.connectors.url_utils import extract_video_id  # pyright: ignore[reportMissingImports]
    from backend.connectors.comments_connector import (  # pyright: ignore[reportMissingImports]
        get_channel_stats,
        get_video_statistics,
    )
    from backend.config import REQUEST_TIMEOUT_SECONDS  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from connectors.url_utils import extract_video_id
    from connectors.comments_connector import get_channel_stats, get_video_statistics
    from config import REQUEST_TIMEOUT_SECONDS


def get_video_metadata(url: str) -> dict:
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Invalid YouTube URL")

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    metadata = _fetch_via_ytdlp(canonical_url, video_id)

    api_data = get_video_statistics(video_id)
    if api_data:
        _enrich_from_api(metadata, api_data)

    return metadata


def _fetch_via_ytdlp(canonical_url: str, video_id: str) -> dict:
    ydl_opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": REQUEST_TIMEOUT_SECONDS,
        "retries": 1,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # pyright: ignore[reportArgumentType, reportUndefinedVariable]
        info = ydl.extract_info(canonical_url, download=False)
        return {
            "video_id": info.get("id", video_id),
            "title": info.get("title", ""),
            "description": info.get("description", ""),
            "upload_date": info.get("upload_date", ""),
            "channel": info.get("uploader", ""),
            "channel_id": info.get("channel_id", ""),
            "view_count": int(info.get("view_count") or 0),
            "like_count": int(info.get("like_count") or 0),
            "tags": info.get("tags", []),
            "comment_count": int(info.get("comment_count") or 0),
            "channel_follower_count": int(info.get("channel_follower_count") or 0),
            "duration_seconds": int(info.get("duration") or 0),
            "canonical_url": canonical_url,
        }


def _enrich_from_api(metadata: dict, api_data: dict) -> None:
    snippet = api_data.get("snippet", {})
    statistics = api_data.get("statistics", {})
    content_details = api_data.get("contentDetails", {})

    if snippet.get("title"):
        metadata["title"] = snippet["title"]
    if snippet.get("description"):
        metadata["description"] = snippet["description"]
    if snippet.get("channelTitle"):
        metadata["channel"] = snippet["channelTitle"]
    if snippet.get("channelId"):
        metadata["channel_id"] = snippet["channelId"]

    if statistics.get("viewCount"):
        metadata["view_count"] = int(statistics["viewCount"])
    if statistics.get("likeCount"):
        metadata["like_count"] = int(statistics["likeCount"])
    if statistics.get("commentCount"):
        metadata["comment_count"] = int(statistics["commentCount"])

    channel_id = metadata.get("channel_id", "")
    if channel_id:
        channel_data = get_channel_stats(channel_id)
        if channel_data:
            chan_stats = channel_data.get("statistics", {})
            if chan_stats.get("subscriberCount"):
                metadata["channel_follower_count"] = int(chan_stats["subscriberCount"])
            if chan_stats.get("videoCount"):
                metadata["channel_video_count"] = int(chan_stats["videoCount"])
            chan_snippet = channel_data.get("snippet", {})
            if chan_snippet.get("publishedAt"):
                metadata["channel_created_at"] = chan_snippet["publishedAt"]
