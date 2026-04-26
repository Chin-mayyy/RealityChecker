import re

try:
    from backend.scoring.rules.tech_freshness import (  # pyright: ignore[reportMissingImports]
        EVERGREEN_TOPICS,
        OUTDATED_COMMENT_SIGNALS,
        SCORING_WEIGHTS,
        TECH_FRESHNESS_PACKS,
    )
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from scoring.rules.tech_freshness import (
        EVERGREEN_TOPICS,
        OUTDATED_COMMENT_SIGNALS,
        SCORING_WEIGHTS,
        TECH_FRESHNESS_PACKS,
    )

_DOMAIN_PRIORITY = [
    "react",
    "node",
    "python",
    "java",
    "devops",
    "javascript_typescript",
]


def detect_domain(
    title: str, description: str, tags: list[str], transcript: str = ""
) -> str | None:
    corpus = " ".join(
        part for part in (title, description, " ".join(tags), transcript) if part
    ).lower()

    scores: dict[str, float] = {}
    for domain, pack in TECH_FRESHNESS_PACKS.items():
        score = 0.0
        for kw in pack["keywords"]:
            if kw in corpus:
                if kw in title.lower():
                    score += 3.0
                elif kw in description.lower():
                    score += 2.0
                else:
                    score += 1.0
        scores[domain] = score

    for domain in _DOMAIN_PRIORITY:
        if scores.get(domain, 0) > 0:
            if domain == "javascript_typescript":
                react_score = scores.get("react", 0)
                if react_score >= scores.get("javascript_typescript", 0):
                    continue
            return domain

    return None


def score_tech_freshness(video_data: dict) -> tuple[float, dict]:
    title = video_data.get("title") or ""
    description = video_data.get("description") or ""
    tags = video_data.get("tags") or []
    transcript = video_data.get("transcript_text") or ""
    comments = video_data.get("usable_comments") or []

    corpus = " ".join(
        part for part in (title, description, " ".join(tags), transcript) if part
    ).lower()

    domain = detect_domain(title, description, tags, transcript)

    is_evergreen = _check_evergreen(title, description)
    evergreen_bonus = SCORING_WEIGHTS["evergreen_bonus"] if is_evergreen else 0.0

    if domain and domain in TECH_FRESHNESS_PACKS:
        score, detail = _score_domain_freshness(domain, corpus, comments)
    else:
        score, detail = _score_generic_freshness(corpus, comments)

    if is_evergreen:
        detail["evergreen"] = True
        detail["evergreen_reason"] = "Topic is foundational/evergreen"

    score += evergreen_bonus
    score = max(
        SCORING_WEIGHTS["minimum_score"],
        min(SCORING_WEIGHTS["maximum_score"], round(score, 1)),
    )

    return score, detail


def _score_domain_freshness(
    domain: str, corpus: str, comments: list[str]
) -> tuple[float, dict]:
    pack = TECH_FRESHNESS_PACKS[domain]
    modern_hits = 0
    modern_found = []
    outdated_hits = 0
    outdated_found = []

    for category, patterns in pack["modern_patterns"].items():
        for pattern in patterns:
            if pattern in corpus:
                modern_hits += 1
                modern_found.append(pattern)

    for category, patterns in pack["outdated_patterns"].items():
        for pattern in patterns:
            if pattern in corpus:
                outdated_hits += 1
                outdated_found.append(pattern)

    comment_signal = _analyze_comments_for_freshness(comments)

    score = SCORING_WEIGHTS["base_score"]
    score += modern_hits * SCORING_WEIGHTS["modern_pattern_hit"]
    score += outdated_hits * SCORING_WEIGHTS["outdated_pattern_hit"]
    score += comment_signal["net_comment_impact"]

    detail = {
        "domain": domain,
        "domain_name": pack["name"],
        "modern_hits": modern_hits,
        "modern_found": modern_found[:5],
        "outdated_hits": outdated_hits,
        "outdated_found": outdated_found[:5],
        "comment_signals": comment_signal,
    }

    return score, detail


def _score_generic_freshness(corpus: str, comments: list[str]) -> tuple[float, dict]:
    modern_hint_count = sum(
        1 for kw in ("latest", "2025", "2026", "modern", "current") if kw in corpus
    )
    outdated_hint_count = sum(
        1 for kw in ("deprecated", "legacy", "old version", "outdated") if kw in corpus
    )

    comment_signal = _analyze_comments_for_freshness(comments)

    score = SCORING_WEIGHTS["base_score"]
    score += modern_hint_count * 0.4
    score += outdated_hint_count * -0.8
    score += comment_signal["net_comment_impact"]

    detail = {
        "domain": None,
        "modern_hits": modern_hint_count,
        "outdated_hits": outdated_hint_count,
        "comment_signals": comment_signal,
    }

    return score, detail


def _analyze_comments_for_freshness(comments: list[str]) -> dict:
    if not comments:
        return {
            "outdated_comment_count": 0,
            "correction_comment_count": 0,
            "still_relevant_count": 0,
            "net_comment_impact": 0.0,
        }

    sample = comments[:50]
    text = " ".join(sample).lower()

    outdated_count = sum(
        1 for signal in OUTDATED_COMMENT_SIGNALS["explicit_outdated"] if signal in text
    )
    correction_count = sum(
        1 for signal in OUTDATED_COMMENT_SIGNALS["helpful_correction"] if signal in text
    )
    still_relevant_count = sum(
        1 for signal in OUTDATED_COMMENT_SIGNALS["still_relevant"] if signal in text
    )

    net_impact = 0.0
    net_impact += outdated_count * SCORING_WEIGHTS["explicit_outdated_comment"]
    net_impact += correction_count * SCORING_WEIGHTS["helpful_correction_comment"]
    net_impact += still_relevant_count * SCORING_WEIGHTS["still_relevant_comment"]

    return {
        "outdated_comment_count": outdated_count,
        "correction_comment_count": correction_count,
        "still_relevant_count": still_relevant_count,
        "net_comment_impact": round(net_impact, 2),
    }


def _check_evergreen(title: str, description: str) -> bool:
    combined = f"{title} {description}".lower()
    for keyword in EVERGREEN_TOPICS["keywords"]:
        if keyword in combined:
            return True
    for pattern in EVERGREEN_TOPICS["title_patterns"]:
        if pattern in combined:
            return True
    return False
