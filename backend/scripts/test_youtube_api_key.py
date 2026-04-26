import json
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from backend.config import YOUTUBE_API_KEY  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import YOUTUBE_API_KEY


def diagnose_key(video_id: str = "dQw4w9WgXcQ") -> int:
    if not YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY is missing in environment.")
        return 1

    print(f"Key found: {YOUTUBE_API_KEY[:8]}...{YOUTUBE_API_KEY[-4:]}")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    tests_passed = 0
    tests_failed = 0

    try:
        video_resp = (
            youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        )
        items = video_resp.get("items", [])
        if not items:
            print("[FAIL] videos.list: no items returned")
            tests_failed += 1
        else:
            snippet = items[0].get("snippet", {})
            stats = items[0].get("statistics", {})
            print(
                "[PASS] videos.list: "
                f"title={snippet.get('title')}, "
                f"views={stats.get('viewCount')}, "
                f"likes={stats.get('likeCount')}"
            )
            tests_passed += 1
    except HttpError as err:
        print(f"[FAIL] videos.list: HTTP {err.resp.status}")
        _print_error_detail(err)
        tests_failed += 1

    try:
        comment_resp = (
            youtube.commentThreads()
            .list(part="snippet", videoId=video_id, maxResults=1, order="relevance")
            .execute()
        )
        count = len(comment_resp.get("items", []))
        print(f"[PASS] commentThreads.list: {count} comment(s) returned")
        tests_passed += 1
    except HttpError as err:
        print(f"[FAIL] commentThreads.list: HTTP {err.resp.status}")
        _print_error_detail(err)
        tests_failed += 1

    print(f"\nResults: {tests_passed} passed, {tests_failed} failed")
    if tests_failed > 0:
        print("\nCommon fixes:")
        print("  1. Enable YouTube Data API v3 in GCP Console")
        print("  2. Add your IPv4 AND IPv6 to IP restrictions")
        print("  3. Do NOT use 'HTTP referrer' restriction for backend calls")
        print("  4. Wait 2-5 minutes after saving key changes")
    return 1 if tests_failed > 0 else 0


def _print_error_detail(err: HttpError) -> None:
    try:
        body = json.loads(err.content.decode("utf-8"))
        error = body.get("error", {})
        message = error.get("message", "")
        reasons = [e.get("reason", "") for e in error.get("errors", [])]
        print(f"       message: {message}")
        print(f"       reasons: {', '.join(reasons)}")
    except Exception:
        print(f"       raw: {err}")


if __name__ == "__main__":
    raise SystemExit(diagnose_key())
