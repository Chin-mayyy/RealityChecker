from datetime import datetime

try:
    from backend.llm.provider import (  # pyright: ignore[reportMissingImports]
        analyze_sentiment,
        generate_explanations,
    )
    from backend.scoring.rules.scoring_rules import (  # pyright: ignore[reportMissingImports]
        score_tech_freshness as _rule_based_tech_freshness,
    )
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from llm.provider import analyze_sentiment, generate_explanations
    from scoring.rules.scoring_rules import (
        score_tech_freshness as _rule_based_tech_freshness,
    )

WEIGHTS = {
    "sentiment_quality": 0.15,
    "recency": 0.15,
    "tech_freshness": 0.25,
    "creator_credibility": 0.20,
    "engagement_quality": 0.10,
    "topic_match": 0.15,
}


def compute_trust_score(video_data: dict, use_llm: bool = True) -> dict:
    parameter_scores = {
        "sentiment_quality": _score_sentiment_quality(video_data),
        "recency": _score_recency(video_data),
        "tech_freshness": _score_tech_freshness(video_data),
        "creator_credibility": _score_creator_credibility(video_data),
        "engagement_quality": _score_engagement_quality(video_data),
        "topic_match": _score_topic_match(video_data),
    }

    overall = round(
        sum(parameter_scores[name] * WEIGHTS[name] for name in parameter_scores),
        1,
    )

    confidence = _compute_confidence(video_data)
    risk_flags = _derive_risk_flags(parameter_scores, confidence)

    sentiment_result = _get_sentiment(video_data, use_llm)
    if sentiment_result.get("llm_used"):
        parameter_scores["sentiment_quality"] = sentiment_result["score"]

    overall = round(
        sum(parameter_scores[name] * WEIGHTS[name] for name in parameter_scores),
        1,
    )

    default_parameters = {
        "sentiment_quality": {
            "score": parameter_scores["sentiment_quality"],
            "why": sentiment_result.get("summary", "Sentiment analysis pending."),
        },
        "recency": {
            "score": parameter_scores["recency"],
            "why": _recency_reason(video_data),
        },
        "tech_freshness": {
            "score": parameter_scores["tech_freshness"],
            "why": _tech_freshness_why(video_data),
        },
        "creator_credibility": {
            "score": parameter_scores["creator_credibility"],
            "why": _creator_credibility_why(video_data),
        },
        "engagement_quality": {
            "score": parameter_scores["engagement_quality"],
            "why": _engagement_quality_why(video_data),
        },
        "topic_match": {
            "score": parameter_scores["topic_match"],
            "why": _topic_match_why(video_data),
        },
    }

    llm_explanations = _get_explanations(
        video_data, default_parameters, overall, risk_flags, use_llm
    )

    parameters = default_parameters.copy()
    llm_used_for_explanations = False
    if llm_explanations.get("llm_used"):
        llm_used_for_explanations = True
        for key in parameters:
            if key in llm_explanations and isinstance(llm_explanations[key], str):
                parameters[key]["why"] = llm_explanations[key]
        overall_explanation = llm_explanations.get("overall_explanation")
        if overall_explanation:
            risk_flags = risk_flags
    else:
        overall_explanation = _compose_explanation(overall, confidence, risk_flags)

    final_overall = overall
    if overall_explanation and llm_used_for_explanations:
        final_explanation = overall_explanation
    else:
        final_explanation = _compose_explanation(overall, confidence, risk_flags)

    return {
        "overall": final_overall,
        "weights": WEIGHTS,
        "parameters": parameters,
        "confidence": confidence,
        "risk_flags": risk_flags,
        "explanation": final_explanation,
        "sentiment_detail": sentiment_result,
        "llm_used": sentiment_result.get("llm_used", False)
        or llm_used_for_explanations,
    }


def _get_sentiment(video_data: dict, use_llm: bool) -> dict:
    comments = video_data.get("usable_comments") or []
    title = video_data.get("title") or ""
    if use_llm and comments:
        return analyze_sentiment(comments, video_title=title)
    return {
        "score": _score_sentiment_quality(video_data),
        "label": "neutral",
        "summary": "Heuristic sentiment (no LLM or no comments).",
        "llm_used": False,
    }


def _get_explanations(
    video_data: dict,
    parameter_scores: dict,
    overall: float,
    risk_flags: list[str],
    use_llm: bool,
) -> dict:
    if not use_llm:
        return {"llm_used": False}
    return generate_explanations(video_data, parameter_scores, overall, risk_flags)


def _score_sentiment_quality(video_data: dict) -> float:
    comments = video_data.get("usable_comments") or []
    if not comments:
        return 5.0

    strong_positive_words = (
        "excellent",
        "amazing",
        "best",
        "wonderful",
        "fantastic",
        "brilliant",
        "superb",
        "solved",
        "finally",
        "works perfectly",
        "life saver",
        "game changer",
    )
    mild_positive_words = (
        "great",
        "helpful",
        "awesome",
        "thanks",
        "thank you",
        "love",
        "clear",
        "informative",
        "useful",
        "learned",
        "working",
        "works",
        "good",
    )
    strong_negative_words = (
        "doesn't work",
        "not working",
        "broken",
        "useless",
        "worst",
        "frustrating",
        "misleading",
        "waste of time",
        "outdated",
        "deprecated",
        "obsolete",
    )
    mild_negative_words = (
        "bad",
        "wrong",
        "confusing",
        "hate",
        "terrible",
        "waste",
        "boring",
        "disappointed",
        "inaccurate",
        "incorrect",
    )

    sample = comments[:80]
    pos_hits = 0
    neg_hits = 0
    for comment in sample:
        lower = comment.lower()
        has_strong_pos = any(w in lower for w in strong_positive_words)
        has_mild_pos = any(w in lower for w in mild_positive_words)
        has_strong_neg = any(w in lower for w in strong_negative_words)
        has_mild_neg = any(w in lower for w in mild_negative_words)

        if has_strong_neg or has_mild_neg:
            neg_hits += 1
        elif has_strong_pos:
            pos_hits += 2
        elif has_mild_pos:
            pos_hits += 1

    total_signal = pos_hits + neg_hits
    if total_signal == 0:
        return 5.0

    pos_ratio = pos_hits / total_signal
    coverage_bonus = min(len(sample) / 50, 1.0) * 0.3

    raw_score = 3.0 + pos_ratio * 6.0 + coverage_bonus
    return round(max(1.0, min(10.0, raw_score)), 1)


def _score_recency(video_data: dict) -> float:
    upload_date = video_data.get("upload_date", "")
    if not upload_date:
        return 5.0
    try:
        uploaded = datetime.strptime(upload_date, "%Y%m%d")
    except ValueError:
        return 5.0
    days_old = (datetime.now() - uploaded).days

    if _is_evergreen_recency_exempt(video_data):
        return round(max(7.5, 10.0 - (days_old / 365) * 0.5), 1)

    if days_old <= 0:
        return 10.0
    if days_old <= 30:
        return round(9.5 - (days_old / 30) * 0.5, 1)
    if days_old <= 180:
        return round(9.0 - ((days_old - 30) / 150) * 1.0, 1)
    if days_old <= 365:
        return round(8.0 - ((days_old - 180) / 185) * 2.0, 1)
    if days_old <= 730:
        return round(6.0 - ((days_old - 365) / 365) * 2.0, 1)
    if days_old <= 1095:
        return round(4.0 - ((days_old - 730) / 365) * 2.0, 1)
    return round(max(1.0, 2.0 - ((days_old - 1095) / 365) * 0.5), 1)


def _is_evergreen_recency_exempt(video_data: dict) -> bool:
    evergreen_keywords = [
        "algorithm",
        "data structure",
        "sorting",
        "big o",
        "recursion",
        "computer science",
        "discrete math",
        "networking fundamentals",
        "git basics",
        "git fundamentals",
        "version control",
        "solid principles",
        "design pattern",
        "clean code",
        "binary search",
        "linked list",
        "hash table",
        "complexity analysis",
        "finite state machine",
        "operating system",
        "os basics",
        "how the internet works",
        "how dns works",
        "tcp",
        "udp",
        "http fundamentals",
    ]
    title = (video_data.get("title") or "").lower()
    description = (video_data.get("description") or "").lower()
    tags = " ".join(t.lower() for t in (video_data.get("tags") or []))
    corpus = f"{title} {description} {tags}"
    return any(kw in corpus for kw in evergreen_keywords)


def _score_tech_freshness(video_data: dict) -> float:
    score, detail = _rule_based_tech_freshness(video_data)
    video_data["_tech_freshness_detail"] = detail
    return score


def _tech_freshness_why(video_data: dict) -> str:
    detail = video_data.get("_tech_freshness_detail") or {}
    domain = detail.get("domain_name") or detail.get("domain") or "general"
    modern = detail.get("modern_hits", 0)
    outdated = detail.get("outdated_hits", 0)
    cs = detail.get("comment_signals") or {}
    outdated_comments = cs.get("outdated_comment_count", 0)

    parts = [f"Domain: {domain}"]
    if modern:
        parts.append(f"{modern} modern signal(s)")
    if outdated:
        parts.append(f"{outdated} outdated signal(s)")
    if outdated_comments:
        parts.append(f"{outdated_comments} outdated comment(s)")
    if detail.get("evergreen"):
        parts.append("evergreen topic bonus applied")

    return ". ".join(parts) if len(parts) > 1 else parts[0]


def _creator_credibility_why(video_data: dict) -> str:
    if video_data.get("_creator_unrelated"):
        return "Channel appears unrelated to this topic. Penalty applied."
    followers = video_data.get("channel_follower_count") or 0
    views = video_data.get("view_count") or 0
    likes = video_data.get("like_count") or 0
    parts = []
    if followers >= 10000:
        parts.append("large following")
    elif followers >= 1000:
        parts.append("moderate following")
    if views > 0:
        ratio = likes / views
        if ratio >= 0.04:
            parts.append("strong engagement")
        elif ratio >= 0.02:
            parts.append("decent engagement")
    if (
        video_data.get("channel_video_count")
        and video_data["channel_video_count"] >= 50
    ):
        parts.append("prolific creator")
    return "Based on " + (", ".join(parts) if parts else "limited signals") + "."


def _engagement_quality_why(video_data: dict) -> str:
    comments_available = bool(video_data.get("comments_available"))
    comments = video_data.get("usable_comment_count") or 0
    views = video_data.get("view_count") or 0
    likes = video_data.get("like_count") or 0
    spam_ratio = float(video_data.get("spam_ratio") or 0)
    duration = video_data.get("duration_seconds") or 0

    parts = []
    if comments_available and comments > 0:
        parts.append(f"{comments} usable comments")
        if views > 0:
            rate = (comments / views) * 1000
            parts.append(f"comment rate {rate:.1f}/1k views")
        if duration > 0:
            cpm = comments / (duration / 60)
            parts.append(f"{cpm:.1f} comments/min")
    elif not comments_available:
        parts.append("no comments available")

    if views > 0:
        lvr = likes / views
        if lvr >= 0.04:
            parts.append(f"strong like ratio ({lvr:.1%})")
        elif lvr < 0.01:
            parts.append(f"low like ratio ({lvr:.1%})")

    if spam_ratio >= 0.3:
        parts.append(f"high spam ({spam_ratio:.0%})")
    elif spam_ratio > 0:
        parts.append(f"low spam ({spam_ratio:.0%})")

    return "; ".join(parts) if parts else "Limited engagement data."


def _topic_match_why(video_data: dict) -> str:
    title = (video_data.get("title") or "").strip()
    description = (video_data.get("description") or "").strip()
    transcript_length = int(video_data.get("transcript_length") or 0)
    tags = video_data.get("tags") or []

    parts = []
    if title:
        parts.append("has title")
    if description:
        parts.append("has description")
    if tags:
        parts.append(f"{len(tags)} tag(s)")
    if transcript_length >= 2000:
        parts.append("substantial transcript")
    elif transcript_length >= 500:
        parts.append("moderate transcript")
    elif transcript_length > 0:
        parts.append("short transcript")
    else:
        parts.append("no transcript")

    return ". ".join(parts) if parts else "Insufficient content signals."


def _score_creator_credibility(video_data: dict) -> float:
    followers = video_data.get("channel_follower_count") or 0
    views = video_data.get("view_count") or 0
    likes = video_data.get("like_count") or 0

    score = 4.0
    if followers >= 10000:
        score += 2.0
    elif followers >= 1000:
        score += 1.0

    if views > 0:
        ratio = likes / views
        if ratio >= 0.04:
            score += 2.0
        elif ratio >= 0.02:
            score += 1.0

    if _is_unrelated_channel(video_data):
        score -= 2.0
        video_data["_creator_unrelated"] = True
    else:
        video_data["_creator_unrelated"] = False

    if (
        video_data.get("channel_video_count")
        and video_data["channel_video_count"] >= 50
    ):
        score += 0.5

    return round(min(score, 10.0), 1)


def _is_unrelated_channel(video_data: dict) -> bool:
    title = (video_data.get("title") or "").lower()
    description = (video_data.get("description") or "").lower()
    channel = (video_data.get("channel") or "").lower()
    tags = " ".join(t.lower() for t in (video_data.get("tags") or []))

    tech_indicators = [
        "tutorial",
        "course",
        "learn",
        "guide",
        "programming",
        "coding",
        "developer",
        "engineering",
        "software",
        "web dev",
        "data science",
        "machine learning",
        "ai",
        "react",
        "python",
        "javascript",
        "node",
        "docker",
        "kubernetes",
        "aws",
        "cloud",
    ]
    entertainment_channel_indicators = [
        "music",
        "gaming",
        "vlog",
        "funny",
        "prank",
        "reaction",
        "stream",
        "podcast",
        "entertainment",
        "comedy",
    ]

    is_tech_content = any(ind in title or ind in description for ind in tech_indicators)
    is_entertainment_channel = any(
        ind in channel for ind in entertainment_channel_indicators
    )

    if is_entertainment_channel and not is_tech_content:
        return True

    music_channel_keywords = [
        "records",
        "music",
        "vevo",
        "official",
        "entertainment",
        "- topic",
    ]
    if any(kw in channel for kw in music_channel_keywords):
        tech_in_tags = any(ind in tags for ind in tech_indicators)
        if not tech_in_tags:
            return True

    return False


def _score_engagement_quality(video_data: dict) -> float:
    comments_available = bool(video_data.get("comments_available"))
    comments = video_data.get("usable_comment_count") or 0
    views = video_data.get("view_count") or 0
    likes = video_data.get("like_count") or 0
    spam_ratio = float(video_data.get("spam_ratio") or 0)
    duration = video_data.get("duration_seconds") or 0
    raw_comment_count = video_data.get("raw_comment_count") or 0

    score = 5.0

    if comments_available and comments > 0:
        if views > 0:
            comment_rate = (comments / views) * 1000
            if comment_rate >= 15:
                score += 2.0
            elif comment_rate >= 5:
                score += 1.0
            elif comment_rate >= 2:
                score += 0.5
            else:
                score -= 0.5

        if duration > 0:
            comments_per_minute = comments / (duration / 60)
            if comments_per_minute >= 3:
                score += 1.5
            elif comments_per_minute >= 1:
                score += 0.5
        else:
            if comments >= 100:
                score += 1.5
            elif comments >= 30:
                score += 1.0
            elif comments >= 10:
                score += 0.5
    elif comments_available and comments == 0 and raw_comment_count > 0:
        score -= 0.5
    else:
        score -= 1.5

    if views > 0:
        like_view_ratio = likes / views
        if like_view_ratio >= 0.06:
            score += 1.5
        elif like_view_ratio >= 0.04:
            score += 1.0
        elif like_view_ratio >= 0.02:
            score += 0.5
        elif like_view_ratio < 0.005:
            score -= 1.5
        elif like_view_ratio < 0.01:
            score -= 0.5

    if spam_ratio >= 0.5:
        score -= 2.5
    elif spam_ratio >= 0.3:
        score -= 1.5
    elif spam_ratio >= 0.15:
        score -= 0.5

    return round(max(1.0, min(10.0, score)), 1)


def _score_topic_match(video_data: dict) -> float:
    title = (video_data.get("title") or "").strip()
    description = (video_data.get("description") or "").strip()
    transcript = video_data.get("transcript_text") or ""
    transcript_length = int(video_data.get("transcript_length") or 0)
    tags = video_data.get("tags") or []
    channel = (video_data.get("channel") or "").lower()

    score = 3.0

    tech_keywords = [
        "tutorial",
        "course",
        "learn",
        "guide",
        "how to",
        "introduction",
        "beginner",
        "advanced",
        "deep dive",
        "crash course",
        "explained",
        "fundamentals",
        "masterclass",
        "walkthrough",
        "hands-on",
        "project",
        "programming",
        "coding",
        "developer",
        "software",
        "engineering",
        "web dev",
        "data science",
        "machine learning",
        "artificial intelligence",
        "cloud",
        "devops",
        "framework",
        "api",
        "database",
        "algorithm",
        "deployment",
        "testing",
        "debugging",
        "refactoring",
        "architecture",
    ]

    title_lower = title.lower()
    desc_lower = description.lower()
    tags_text = " ".join(t.lower() for t in tags)

    tech_signal_count = sum(1 for kw in tech_keywords if kw in title_lower)
    if tech_signal_count >= 2:
        score += 2.0
    elif tech_signal_count == 1:
        score += 1.5

    desc_tech_signal_count = sum(1 for kw in tech_keywords if kw in desc_lower)
    if desc_tech_signal_count >= 3:
        score += 1.0
    elif desc_tech_signal_count >= 1:
        score += 0.5

    if tags:
        tech_tag_ratio = sum(
            1
            for t in tags
            if t.lower() in tech_keywords
            or any(
                kw in t.lower()
                for kw in ["react", "python", "node", "java", "docker", "kubernetes"]
            )
        ) / len(tags)
        score += tech_tag_ratio * 1.5

    vague_patterns = [
        "funny",
        "prank",
        "challenge",
        "reaction",
        "vlog",
        "day in my life",
        "haul",
        "unboxing",
        "mukbang",
        "asmr",
    ]
    if any(p in title_lower for p in vague_patterns) and tech_signal_count == 0:
        score -= 1.5

    if transcript_length >= 2000:
        score += 1.5
    elif transcript_length >= 500:
        score += 1.0
    elif transcript_length >= 100:
        score += 0.5

    educational_channels = [
        "freecodecamp",
        "traversy media",
        "fireship",
        "the net ninja",
        "programming with mosh",
        "tech with tim",
        "sentdex",
        "corey schafer",
        "cs50",
        "mit opencourseware",
        "3blue1brown",
        "coding train",
        "computerphile",
        "two minute papers",
        "statquest",
    ]
    if any(ech in channel for ech in educational_channels):
        score += 0.5

    return round(min(10.0, max(1.0, score)), 1)


def _compute_confidence(video_data: dict) -> dict:
    confidence_value = 1.0
    reasons = []

    transcript_available = bool(video_data.get("transcript_available"))
    comments_available = bool(video_data.get("comments_available"))
    comment_count = video_data.get("usable_comment_count") or 0
    channel_follower_count = video_data.get("channel_follower_count") or 0
    llm_fallback_used = bool(video_data.get("llm_fallback_used"))
    sentiment_llm_used = video_data.get("sentiment_llm_used", True)

    if transcript_available:
        reasons.append("Transcript available")
    else:
        confidence_value -= 0.25
        reasons.append("Transcript unavailable")

    if comments_available and comment_count >= 30:
        reasons.append(f"{comment_count} comments analyzed")
    else:
        confidence_value -= 0.20
        reasons.append("Comments unavailable or low sample size")

    if channel_follower_count > 0:
        reasons.append("Channel statistics available")
    else:
        confidence_value -= 0.15
        reasons.append("Missing channel statistics")

    if llm_fallback_used or not sentiment_llm_used:
        confidence_value -= 0.10
        reasons.append("LLM fallback path used")

    confidence_value = max(0.0, min(1.0, round(confidence_value, 2)))

    if confidence_value >= 0.75:
        level = "high"
    elif confidence_value >= 0.45:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "value": confidence_value,
        "reasons": reasons,
    }


def _derive_risk_flags(parameter_scores: dict, confidence: dict) -> list[str]:
    risk_flags = []

    freshness_score = parameter_scores.get("tech_freshness", 5.0)
    if freshness_score <= 3.0:
        risk_flags.append("outdated-risk-high")
    elif freshness_score <= 6.0:
        risk_flags.append("outdated-risk-medium")

    if confidence.get("level") == "low":
        risk_flags.append("low-confidence")

    engagement_score = parameter_scores.get("engagement_quality", 5.0)
    if engagement_score <= 3.0:
        risk_flags.append("low-engagement")

    credibility_score = parameter_scores.get("creator_credibility", 5.0)
    if credibility_score <= 3.0:
        risk_flags.append("low-credibility")

    if not risk_flags:
        risk_flags.append("no-major-risk-detected")

    return risk_flags


def _compose_explanation(
    overall: float, confidence: dict, risk_flags: list[str]
) -> str:
    if overall >= 8.0:
        quality = "Strong learning resource"
    elif overall >= 6.0:
        quality = "Reasonably useful tutorial"
    elif overall >= 4.0:
        quality = "Mixed quality tutorial"
    else:
        quality = "High risk of outdated or low-quality content"

    return (
        f"{quality} with {confidence['level']} confidence. "
        f"Flags: {', '.join(risk_flags)}."
    )


def _recency_reason(video_data: dict) -> str:
    upload_date = video_data.get("upload_date", "")
    if not upload_date:
        return "Upload date unavailable, applied neutral recency score."
    try:
        uploaded = datetime.strptime(upload_date, "%Y%m%d")
    except ValueError:
        return "Upload date format invalid, applied neutral recency score."
    days_old = (datetime.now() - uploaded).days
    if _is_evergreen_recency_exempt(video_data):
        return f"Evergreen topic uploaded {days_old} days ago (age penalty reduced)."
    return f"Video was uploaded {days_old} days ago."
