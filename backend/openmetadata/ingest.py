import logging
from datetime import datetime, timezone

import requests

try:
    from backend.config import (
        OPENMETADATA_HOST,
        OPENMETADATA_TOKEN,
    )
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import OPENMETADATA_HOST, OPENMETADATA_TOKEN

logger = logging.getLogger(__name__)

_SERVICE_NAME = "realitychecker"
_SCHEMA_FQN = "realitychecker.youtube_analytics.default"

_SETUP_DONE = False


def _get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if OPENMETADATA_TOKEN:
        headers["Authorization"] = f"Bearer {OPENMETADATA_TOKEN}"
    return headers


def _api_url(path: str) -> str:
    base = (OPENMETADATA_HOST or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/api"):
        return f"{base}/v1{path}"
    return f"{base}/api/v1{path}"


def _is_configured() -> bool:
    return bool(OPENMETADATA_HOST) and bool(OPENMETADATA_TOKEN)


def _post(path: str, payload: dict) -> dict | None:
    url = _api_url(path)
    if not url:
        return None
    try:
        resp = requests.post(url, json=payload, headers=_get_headers(), timeout=15)
        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        if resp.status_code == 409:
            return {}
        logger.warning(
            "OM POST %s returned %s: %s", path, resp.status_code, resp.text[:200]
        )
        return None
    except Exception as exc:
        logger.warning("OM POST failed for %s: %s", path, exc)
        return None


def _put(path: str, payload: dict) -> dict | None:
    url = _api_url(path)
    if not url:
        return None
    try:
        resp = requests.put(url, json=payload, headers=_get_headers(), timeout=15)
        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        if resp.status_code == 409:
            return {}
        logger.warning(
            "OM PUT %s returned %s: %s", path, resp.status_code, resp.text[:200]
        )
        return None
    except Exception as exc:
        logger.warning("OM PUT failed for %s: %s", path, exc)
        return None


def ensure_infrastructure() -> None:
    global _SETUP_DONE
    if _SETUP_DONE or not _is_configured():
        return

    _post(
        "/services/databaseServices",
        {
            "name": "realitychecker",
            "serviceType": "Mysql",
            "connection": {
                "config": {
                    "type": "Mysql",
                    "hostPort": "youtube.com",
                    "username": "realitychecker",
                    "authType": {"password": "realitychecker_dummy"},
                }
            },
        },
    )

    _post(
        "/databases",
        {
            "name": "youtube_analytics",
            "service": "realitychecker",
        },
    )

    _post(
        "/databaseSchemas",
        {
            "name": "default",
            "database": "realitychecker.youtube_analytics",
        },
    )

    _post(
        "/services/pipelineServices",
        {
            "name": "realitychecker_pipeline_service",
            "serviceType": "Airflow",
            "connection": {
                "config": {
                    "type": "Airflow",
                    "hostPort": "http://localhost:8000",
                }
            },
            "description": "RealityChecker scoring pipeline service for YouTube video quality analysis",
        },
    )

    _post(
        "/pipelines",
        {
            "name": "realitychecker_scoring",
            "service": "realitychecker_pipeline_service",
            "sourceUrl": "https://github.com/anomalyco/realitychecker",
            "description": "Scoring pipeline: fetch metadata -> extract features -> compute trust scores -> generate scorecard",
        },
    )

    _post(
        "/classifications",
        {
            "name": "governance",
            "description": "Governance tags for RealityChecker video quality classification",
            "provider": "user",
            "mutuallyExclusive": False,
        },
    )

    tags = [
        ("highQuality", "Score >= 8/10: high quality learning resource"),
        ("moderateQuality", "Score 6-7.9/10: reasonably useful tutorial"),
        ("lowQuality", "Score < 4/10: high risk of outdated or low-quality content"),
        ("outdatedRisk", "Video contains outdated patterns or deprecated APIs"),
        ("lowConfidence", "Insufficient data for reliable scoring"),
        ("beginnerFriendly", "Suitable for beginners based on content and engagement"),
        ("techFreshnessRules", "Curated rule pack for tech freshness detection"),
        ("highEngagement", "Engagement quality score >= 7.0"),
        ("recentContent", "Recency score >= 7.0: uploaded recently"),
        ("spamHeavy", "Comment spam ratio >= 30%"),
        ("lowEngagement", "Engagement quality score <= 3.0"),
        ("lowCredibility", "Creator credibility score <= 3.0"),
        ("evergreen", "Evergreen topic: content remains relevant regardless of age"),
    ]
    for tag_name, desc in tags:
        _post(
            "/tags",
            {
                "name": tag_name,
                "description": desc,
                "classification": "governance",
            },
        )

    _SETUP_DONE = True
    logger.info("OM infrastructure ensured")


def ingest_analysis(
    video_data: dict, trust_data: dict, feature_snapshot: dict
) -> dict | None:
    if not _is_configured():
        logger.info("OpenMetadata not configured, skipping ingestion")
        return None

    ensure_infrastructure()

    video_id = video_data.get("video_id", "unknown")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    raw_table = _ingest_raw_table(video_id, video_data)
    feature_table = _ingest_feature_table(video_id, timestamp, feature_snapshot)
    scorecard_table = _ingest_scorecard_table(
        video_id, timestamp, video_data, trust_data, feature_snapshot
    )

    raw_fqn = f"realitychecker.youtube_analytics.default.youtube_video_raw_{video_id}"
    feature_fqn = f"realitychecker.youtube_analytics.default.feature_snapshot_{video_id}_{timestamp}"
    scorecard_fqn = f"realitychecker.youtube_analytics.default.video_scorecard_{video_id}_{timestamp}"

    _add_lineage(from_fqn=raw_fqn, to_fqn=feature_fqn)
    _add_lineage(from_fqn=feature_fqn, to_fqn=scorecard_fqn)

    domain = (video_data.get("_tech_freshness_detail") or {}).get("domain") or "general"
    rules_fqn = (
        f"realitychecker.youtube_analytics.default.tech_freshness_rules_{domain}"
    )
    _add_lineage(from_fqn=rules_fqn, to_fqn=feature_fqn)

    _ingest_sample_data(video_id, timestamp, video_data, trust_data, feature_snapshot)

    _ingest_data_quality_tests(scorecard_fqn, trust_data)

    logger.info("OM ingestion complete for video %s", video_id)
    return {
        "raw": raw_table is not None,
        "feature": feature_table is not None,
        "scorecard": scorecard_table is not None,
        "lineage_edges": 3,
    }


def _ingest_raw_table(video_id: str, video_data: dict) -> dict | None:
    payload = {
        "name": f"youtube_video_raw_{video_id}",
        "databaseSchema": _SCHEMA_FQN,
        "columns": [
            {
                "name": "video_id",
                "dataType": "VARCHAR",
                "dataLength": 20,
                "description": "YouTube video ID",
            },
            {
                "name": "title",
                "dataType": "VARCHAR",
                "dataLength": 500,
                "description": "Video title",
            },
            {
                "name": "channel",
                "dataType": "VARCHAR",
                "dataLength": 200,
                "description": "Channel name",
            },
            {"name": "upload_date", "dataType": "DATE", "description": "Upload date"},
            {"name": "view_count", "dataType": "BIGINT", "description": "Total views"},
            {"name": "like_count", "dataType": "BIGINT", "description": "Total likes"},
            {
                "name": "comment_count",
                "dataType": "INT",
                "description": "Total comments",
            },
            {
                "name": "channel_follower_count",
                "dataType": "BIGINT",
                "description": "Channel subscriber count",
            },
        ],
        "description": f"Raw YouTube metadata for: {video_data.get('title', video_id)}",
    }
    return _post("/tables", payload)


def _ingest_feature_table(
    video_id: str, timestamp: str, feature_snapshot: dict
) -> dict | None:
    columns = [
        {
            "name": "recency_days",
            "dataType": "INT",
            "description": f"Days since upload: {feature_snapshot.get('recency_days', 'N/A')}",
        },
        {
            "name": "like_view_ratio",
            "dataType": "DOUBLE",
            "description": f"Like/view ratio: {feature_snapshot.get('like_view_ratio', 'N/A')}",
        },
        {
            "name": "spam_ratio",
            "dataType": "DOUBLE",
            "description": f"Spam comment ratio: {feature_snapshot.get('spam_ratio', 'N/A')}",
        },
        {
            "name": "usable_comment_count",
            "dataType": "INT",
            "description": f"Non-spam comments: {feature_snapshot.get('usable_comment_count', 'N/A')}",
        },
        {
            "name": "transcript_length",
            "dataType": "INT",
            "description": f"Transcript length: {feature_snapshot.get('transcript_length', 'N/A')}",
        },
    ]
    keyword_signals = feature_snapshot.get("keyword_signals") or {}
    if keyword_signals:
        columns.append(
            {
                "name": "keyword_signals_json",
                "dataType": "VARCHAR",
                "dataLength": "2000",
                "description": f"Freshness signals: modern={keyword_signals.get('modern_hits', 0)}, outdated={keyword_signals.get('outdated_hits', 0)}",
            }
        )

    payload = {
        "name": f"feature_snapshot_{video_id}_{timestamp}",
        "databaseSchema": _SCHEMA_FQN,
        "columns": columns,
        "description": f"Derived features for video {video_id} at {timestamp}",
    }
    return _post("/tables", payload)


def _ingest_scorecard_table(
    video_id: str,
    timestamp: str,
    video_data: dict,
    trust_data: dict,
    feature_snapshot: dict | None = None,
) -> dict | None:
    overall = trust_data.get("overall", 0)
    confidence = trust_data.get("confidence", {})
    parameters = trust_data.get("parameters", {})

    columns = [
        {
            "name": "overall_score",
            "dataType": "DOUBLE",
            "description": f"Overall score: {overall}/10",
        },
        {
            "name": "confidence_level",
            "dataType": "VARCHAR",
            "dataLength": 20,
            "description": f"Confidence: {confidence.get('level', 'N/A')}",
        },
        {
            "name": "confidence_value",
            "dataType": "DOUBLE",
            "description": f"Confidence value: {confidence.get('value', 'N/A')}",
        },
    ]
    for param_name, param_data in parameters.items():
        columns.append(
            {
                "name": f"score_{param_name}",
                "dataType": "DOUBLE",
                "description": f"{param_name}: {param_data.get('score', 'N/A')} — {(param_data.get('why', '') or '')[:80]}",
            }
        )

    tags = _build_tags(overall, trust_data, feature_snapshot)

    tech_detail = video_data.get("_tech_freshness_detail") or {}
    if tech_detail.get("evergreen"):
        tags.append({"tagFQN": "governance.evergreen"})

    description = (
        f"RealityChecker scorecard for '{video_data.get('title', video_id)}'. "
        f"Overall: {overall}/10, Confidence: {confidence.get('level', 'N/A')}. "
        f"Flags: {', '.join(trust_data.get('risk_flags', ['none']))}."
    )

    payload = {
        "name": f"video_scorecard_{video_id}_{timestamp}",
        "databaseSchema": _SCHEMA_FQN,
        "columns": columns,
        "tags": tags,
        "description": description,
    }
    return _post("/tables", payload)


def _build_tags(
    overall: float, trust_data: dict, feature_snapshot: dict | None = None
) -> list[dict]:
    tags = []
    if overall >= 8.0:
        tags.append({"tagFQN": "governance.highQuality"})
    elif overall >= 6.0:
        tags.append({"tagFQN": "governance.moderateQuality"})
    elif overall < 4.0:
        tags.append({"tagFQN": "governance.lowQuality"})

    for flag in trust_data.get("risk_flags", []):
        if "outdated" in flag:
            tags.append({"tagFQN": "governance.outdatedRisk"})
        if "low-confidence" in flag:
            tags.append({"tagFQN": "governance.lowConfidence"})
        if "low-engagement" in flag:
            tags.append({"tagFQN": "governance.lowEngagement"})
        if "low-credibility" in flag:
            tags.append({"tagFQN": "governance.lowCredibility"})

    if trust_data.get("confidence", {}).get("level") == "high" and overall >= 7.0:
        tags.append({"tagFQN": "governance.beginnerFriendly"})

    parameters = trust_data.get("parameters", {})
    engagement = parameters.get("engagement_quality", {}).get("score", 5.0)
    if engagement >= 7.0:
        tags.append({"tagFQN": "governance.highEngagement"})

    recency = parameters.get("recency", {}).get("score", 5.0)
    if recency >= 7.0:
        tags.append({"tagFQN": "governance.recentContent"})

    feature_snapshot = trust_data.get("_feature_snapshot") or {}
    spam_ratio = feature_snapshot.get("spam_ratio", 0)
    if isinstance(spam_ratio, (int, float)) and spam_ratio >= 0.3:
        tags.append({"tagFQN": "governance.spamHeavy"})

    return tags


def _get_entity_id(fqn: str, entity_type: str) -> str | None:
    url = _api_url(f"/{entity_type}s/name/{fqn}")
    if not url:
        return None
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            entity_id = data.get("id")
            if entity_id:
                logger.info("OM resolved entity %s -> %s", fqn, entity_id)
                return entity_id
            logger.warning("OM entity %s has no id field in response", fqn)
            return None
        logger.warning(
            "OM entity lookup for %s returned %s: %s",
            fqn,
            resp.status_code,
            resp.text[:200],
        )
        return None
    except Exception as exc:
        logger.warning("OM entity lookup failed for %s: %s", fqn, exc)
        return None


def _add_lineage(from_fqn: str, to_fqn: str) -> dict | None:
    if not _is_configured():
        return None

    url = _api_url("/lineage")
    if not url:
        return None

    from_id = _get_entity_id(from_fqn, "table")
    to_id = _get_entity_id(to_fqn, "table")

    if not from_id or not to_id:
        logger.warning(
            "OM lineage: could not resolve entity IDs for %s -> %s (from=%s, to=%s)",
            from_fqn,
            to_fqn,
            from_id,
            to_id,
        )
        return None

    payload = {
        "edge": {
            "fromEntity": {"id": from_id, "type": "table"},
            "toEntity": {"id": to_id, "type": "table"},
            "lineageDetails": {
                "pipeline": {"id": from_id, "type": "table"},
                "sql": f"SELECT * FROM {from_fqn.split('.')[-1]}",
                "description": f"RealityChecker scoring pipeline: {from_fqn.split('.')[-1]} \u2192 {to_fqn.split('.')[-1]}",
            },
        }
    }

    try:
        resp = requests.put(url, json=payload, headers=_get_headers(), timeout=15)
        if resp.status_code in (200, 201, 409):
            logger.info(
                "OM lineage: %s -> %s", from_fqn.split(".")[-1], to_fqn.split(".")[-1]
            )
            return resp.json() if resp.content else {}
        logger.warning("OM lineage returned %s: %s", resp.status_code, resp.text[:300])
        return None
    except Exception as exc:
        logger.warning("OM lineage failed: %s", exc)
        return None


def ingest_freshness_rules() -> dict | None:
    if not _is_configured():
        return None
    ensure_infrastructure()

    try:
        from backend.scoring.rules.tech_freshness import (
            SCORING_WEIGHTS,
            TECH_FRESHNESS_PACKS,
        )  # pyright: ignore[reportMissingImports]
    except ModuleNotFoundError:
        from scoring.rules.tech_freshness import SCORING_WEIGHTS, TECH_FRESHNESS_PACKS

    for domain, pack in TECH_FRESHNESS_PACKS.items():
        modern_count = sum(
            len(patterns) for patterns in pack["modern_patterns"].values()
        )
        outdated_count = sum(
            len(patterns) for patterns in pack["outdated_patterns"].values()
        )

        modern_categories = list(pack["modern_patterns"].keys())
        outdated_categories = list(pack["outdated_patterns"].keys())

        payload = {
            "name": f"tech_freshness_rules_{domain}",
            "databaseSchema": _SCHEMA_FQN,
            "columns": [
                {
                    "name": "domain",
                    "dataType": "VARCHAR",
                    "dataLength": 50,
                    "description": f"Tech domain: {pack['name']}",
                },
                {
                    "name": "rule_version",
                    "dataType": "VARCHAR",
                    "dataLength": 20,
                    "description": "Rule pack version (v1)",
                },
                {
                    "name": "modern_patterns_count",
                    "dataType": "INT",
                    "description": f"Modern patterns: {modern_count} across {', '.join(modern_categories)}",
                },
                {
                    "name": "outdated_patterns_count",
                    "dataType": "INT",
                    "description": f"Outdated patterns: {outdated_count} across {', '.join(outdated_categories)}",
                },
                {
                    "name": "keywords",
                    "dataType": "VARCHAR",
                    "dataLength": 500,
                    "description": f"Detection keywords: {', '.join(pack['keywords'][:5])}",
                },
                {
                    "name": "evergreen_bonus",
                    "dataType": "DOUBLE",
                    "description": f"Evergreen topic bonus: {SCORING_WEIGHTS.get('evergreen_bonus', 1.5)}",
                },
                {
                    "name": "base_score",
                    "dataType": "DOUBLE",
                    "description": f"Base score for domain freshness: {SCORING_WEIGHTS.get('base_score', 5.0)}",
                },
            ],
            "tags": [{"tagFQN": "governance.techFreshnessRules"}],
            "description": f"Tech freshness rule pack for {pack['name']}. {modern_count} modern + {outdated_count} outdated detection patterns. Domain priority: {domain}.",
        }
        result = _post("/tables", payload)
        if result:
            logger.info("OM freshness rules ensured for domain: %s", domain)

    return {"status": "ok"}


def _ingest_sample_data(
    video_id: str,
    timestamp: str,
    video_data: dict,
    trust_data: dict,
    feature_snapshot: dict,
) -> None:
    if not _is_configured():
        return

    scorecard_fqn = f"realitychecker.youtube_analytics.default.video_scorecard_{video_id}_{timestamp}"

    sample_data = {
        "overall_score": str(trust_data.get("overall", 0)),
        "confidence_level": trust_data.get("confidence", {}).get("level", "unknown"),
        "confidence_value": str(trust_data.get("confidence", {}).get("value", 0)),
    }
    for param_name, param_data in trust_data.get("parameters", {}).items():
        sample_data[f"score_{param_name}"] = str(param_data.get("score", 0))

    logger.info(
        "OM sample data prepared for scorecard %s (data ingestion via column descriptions)",
        scorecard_fqn,
    )


_QUALITY_TESTS = [
    {
        "name": "tech_freshness_pass",
        "column": "score_tech_freshness",
        "displayName": "Tech Freshness >= 5.0",
        "description": "Checks if the tech freshness score meets the minimum threshold for a quality learning resource",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "5.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 5.0,
    },
    {
        "name": "recency_pass",
        "column": "score_recency",
        "displayName": "Recency >= 5.0",
        "description": "Checks if the recency score indicates content is not severely outdated",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "5.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 5.0,
    },
    {
        "name": "creator_credibility_pass",
        "column": "score_creator_credibility",
        "displayName": "Creator Credibility >= 5.0",
        "description": "Checks if the creator credibility score indicates a trustworthy source",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "5.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 5.0,
    },
    {
        "name": "engagement_quality_pass",
        "column": "score_engagement_quality",
        "displayName": "Engagement Quality >= 5.0",
        "description": "Checks if engagement metrics indicate active community interaction",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "5.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 5.0,
    },
    {
        "name": "sentiment_quality_pass",
        "column": "score_sentiment_quality",
        "displayName": "Sentiment Quality >= 5.0",
        "description": "Checks if viewer sentiment is neutral or positive",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "5.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 5.0,
    },
    {
        "name": "overall_score_pass",
        "column": "overall_score",
        "displayName": "Overall Score >= 6.0",
        "description": "Checks if the overall trust score meets the quality threshold",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "6.0"},
            {"name": "maxValueForMaxInCol", "value": "10.0"},
        ],
        "threshold": 6.0,
    },
    {
        "name": "confidence_pass",
        "column": "confidence_value",
        "displayName": "Confidence >= 0.45",
        "description": "Checks if confidence level meets minimum threshold (medium or above)",
        "definition": "columnValueMaxToBeBetween",
        "params": [
            {"name": "minValueForMaxInCol", "value": "0.45"},
            {"name": "maxValueForMaxInCol", "value": "1.0"},
        ],
        "threshold": 0.45,
    },
]


def _ingest_data_quality_tests(scorecard_fqn: str, trust_data: dict) -> None:
    if not _is_configured():
        return

    overall = trust_data.get("overall", 0)
    parameters = trust_data.get("parameters", {})

    for test_def in _QUALITY_TESTS:
        column_name = test_def["column"]
        threshold = test_def["threshold"]

        if column_name == "overall_score":
            value = overall
        elif column_name == "confidence_value":
            value = trust_data.get("confidence", {}).get("value", 0)
        elif column_name.startswith("score_"):
            param_key = column_name.replace("score_", "")
            value = parameters.get(param_key, {}).get("score", 0)
        else:
            continue

        passed = value >= threshold  # noqa: F841

        payload = {
            "name": test_def["name"],
            "displayName": test_def["displayName"],
            "description": test_def["description"],
            "testDefinition": test_def["definition"],
            "entityLink": f"<#E::table::{scorecard_fqn}::columns::{column_name}>",
            "parameterValues": test_def["params"],
        }

        result = _post("/dataQuality/testCases", payload)
        if not result:
            continue

    logger.info("OM data quality tests ingested for %s", scorecard_fqn)


def get_stats() -> dict:
    if not _is_configured():
        return {"connected": False, "tables": 0, "lineage_edges": 0}

    try:
        resp = requests.get(
            _api_url("/tables"),
            headers=_get_headers(),
            params={"limit": 0},
            timeout=10,
        )
        total_tables = 0
        if resp.status_code == 200:
            data = resp.json()
            total_tables = data.get("paging", {}).get(
                "total", len(data.get("data", []))
            )

        database_resp = requests.get(
            _api_url("/databases/name/realitychecker.youtube_analytics"),
            headers=_get_headers(),
            timeout=10,
        )
        db_info = {}
        if database_resp.status_code == 200:
            db_info = database_resp.json()

        return {
            "connected": True,
            "tables": total_tables,
            "database": db_info.get("name", "youtube_analytics"),
            "service": db_info.get("service", {}),
            "version": check_connection().get("version", "unknown"),
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def check_connection() -> dict:
    if not _is_configured():
        return {
            "connected": False,
            "error": "OPENMETADATA_HOST or OPENMETADATA_TOKEN not configured",
        }

    url = _api_url("/system/version")
    if not url:
        return {"connected": False, "error": "Invalid OPENMETADATA_HOST"}

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {"connected": True, "version": data.get("version", "unknown")}
        return {
            "connected": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def log_pipeline_run(
    start_ms: int, end_ms: int, success: bool, video_id: str
) -> dict | None:
    """Log a pipeline run to OpenMetadata for audit and monitoring."""
    if not _is_configured():
        return None

    try:
        pipeline_fqn = "realitychecker_pipeline_service.realitychecker_scoring"
        start_ts = start_ms // 1000
        end_ts = end_ms // 1000
        duration_ms = end_ms - start_ms

        payload = {
            "pipelineRunId": f"{video_id}_{start_ms}",
            "pipelineName": pipeline_fqn,
            "startDate": start_ts,
            "endDate": end_ts,
            "status": "Successful" if success else "Failed",
            "executedAt": datetime.now(timezone.utc).isoformat(),
        }

        result = _post("/pipelineStatus", payload)
        if result:
            logger.info(
                "Pipeline run logged for video %s (duration: %dms, status: %s)",
                video_id,
                duration_ms,
                "success" if success else "failed",
            )
        return result
    except Exception as exc:
        logger.debug("Failed to log pipeline run: %s", str(exc))
        return None
