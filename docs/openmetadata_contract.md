# OpenMetadata Contract (Day 1)

## Objective

Define the minimum OpenMetadata integration needed for strong hackathon evaluation under "Best Use of OpenMetadata".

## Core Entities

1. `youtube_video_raw`
   - Source metadata from YouTube ingestion.
   - Key fields: video_id, title, channel, upload_date, view_count, like_count, comment_count.

2. `feature_snapshots`
   - Derived features used by the scoring engine.
   - Key fields: recency_days, sentiment_summary, freshness_signals, credibility_signals, engagement_signals, topic_signals.

3. `video_scorecards`
   - Final scoring output returned to clients.
   - Key fields: overall_score, per-parameter scores, confidence level/value/reasons, risk_flags, explanation.

4. `tech_freshness_rules`
   - Curated rules for detecting outdated or modern patterns.
   - Key fields: domain, rule_version, deprecated_patterns, modern_patterns.

## Lineage

`youtube_video_raw -> feature_snapshots -> video_scorecards`

`tech_freshness_rules -> feature_snapshots`

## Governance Tags (MVP)

- `outdated-risk-high`
- `outdated-risk-medium`
- `low-confidence`
- `beginner-friendly-candidate`

## Day 1 API/Schema Lock

The backend API contract in `README.md` is the source of truth for scorecard payload fields.

## Day 2+ Implementation Notes

- Implement ingestion in `backend/openmetadata/ingest.py`.
- Start with create-or-update operations and idempotent upserts keyed by `video_id` + `analysis_timestamp`.
- Add lineage edges in the same transaction scope when possible.
