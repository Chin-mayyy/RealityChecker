from datetime import datetime


def build_feature_snapshot(
    video_data: dict, comments_data: dict, transcript_data: dict
) -> dict:
    view_count = int(video_data.get("view_count") or 0)
    like_count = int(video_data.get("like_count") or 0)
    raw_comment_count = int(video_data.get("comment_count") or 0)

    usable_comments = comments_data.get("usable_comments") or []
    usable_comment_count = len(usable_comments)
    spam_like_count = int(comments_data.get("spam_like_count") or 0)
    total_fetched = int(comments_data.get("total_fetched") or 0)

    transcript_text = transcript_data.get("text") or ""
    transcript_chunks = transcript_data.get("chunks") or []

    recency_days = _compute_recency_days(video_data.get("upload_date"))
    like_view_ratio = (like_count / view_count) if view_count else 0.0
    comment_view_ratio = (raw_comment_count / view_count) if view_count else 0.0
    spam_ratio = (spam_like_count / total_fetched) if total_fetched else 0.0

    keyword_signals = _keyword_signals(
        title=video_data.get("title") or "",
        description=video_data.get("description") or "",
        transcript=transcript_text,
    )

    return {
        "recency_days": recency_days,
        "like_view_ratio": round(like_view_ratio, 5),
        "comment_view_ratio": round(comment_view_ratio, 5),
        "usable_comment_count": usable_comment_count,
        "spam_ratio": round(spam_ratio, 4),
        "transcript_length": len(transcript_text),
        "transcript_chunk_count": len(transcript_chunks),
        "keyword_signals": keyword_signals,
        "raw_comment_count": raw_comment_count,
        "total_fetched_comments": total_fetched,
    }


def _compute_recency_days(upload_date: str | None) -> int | None:
    if not upload_date:
        return None
    try:
        uploaded = datetime.strptime(upload_date, "%Y%m%d")
    except ValueError:
        return None
    return (datetime.now() - uploaded).days


def _keyword_signals(title: str, description: str, transcript: str) -> dict:
    corpus = " ".join((title, description, transcript)).lower()
    modern_terms = [
        "latest",
        "2025",
        "2026",
        "typescript",
        "docker",
        "kubernetes",
    ]
    outdated_terms = [
        "deprecated",
        "legacy",
        "old version",
        "python 2",
        "angularjs",
    ]

    modern_hits = sum(1 for term in modern_terms if term in corpus)
    outdated_hits = sum(1 for term in outdated_terms if term in corpus)

    return {
        "modern_hits": modern_hits,
        "outdated_hits": outdated_hits,
    }
