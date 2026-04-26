from urllib.parse import parse_qs, urlparse


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.netloc not in YOUTUBE_HOSTS:
        return None

    if "youtu.be" in parsed.netloc:
        candidate = parsed.path.strip("/")
        return candidate or None

    query_params = parse_qs(parsed.query)
    if "v" in query_params and query_params["v"]:
        return query_params["v"][0]

    if parsed.path.startswith("/shorts/"):
        candidate = parsed.path.replace("/shorts/", "").strip("/")
        return candidate or None

    if parsed.path.startswith("/embed/"):
        candidate = parsed.path.replace("/embed/", "").strip("/")
        return candidate or None

    return None


def is_valid_youtube_url(url: str) -> bool:
    return extract_video_id(url) is not None
