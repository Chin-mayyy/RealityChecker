# RealityChecker

Realitychecker is a browser-extension-driven scoring system that rates YouTube learning videos on six parameters and produces a confidence-aware score out of 10, with full OpenMetadata governance integration.

## Architecture

```
YouTube URL
    │
    ▼
┌──────────────────────────────────────────────────┐
│  Chrome Extension (popup.html + content.js)      │
│  - URL input or auto-detect current tab          │
│  - Displays score circle, 6 params, risk flags   │
│  - Injects score badge on YouTube watch pages     │
└──────────────────┬───────────────────────────────┘
                   │ POST /analyze
                   ▼
┌──────────────────────────────────────────────────┐
│  FastAPI Backend (Python)                        │
│                                                  │
│  Connectors          Scoring Engine              │
│  ┌─────────────┐    ┌──────────────────┐        │
│  │ yt-dlp      │───▶│ recency          │ 0.15   │
│  │ YouTube API │───▶│ tech_freshness   │ 0.25   │
│  │ Groq (LLM)  │───▶│ sentiment_quality│ 0.15   │
│  │ GitHub/NPM  │    │ creator_cred.    │ 0.20   │
│  └─────────────┘    │ engagement_quality│ 0.10   │
│                     │ topic_match      │ 0.15   │
│                     └──────┬───────────┘        │
│                            │                     │
│  ┌─────────────────────────▼──────────────────┐  │
│  │         OpenMetadata Ingestion              │  │
│  │  youtube_video_raw → feature_snapshot       │  │
│  │       → video_scorecard  (lineage tracked)  │  │
│  │  tech_freshness_rules → feature_snapshot    │  │
│  │  + governance tags per scorecard            │  │
│  └─────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your keys
```

Required variables:

| Variable | Description | Required |
|---|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key | No (yt-dlp fallback) |
| `GROQ_API_KEY` | Groq API key for LLM sentiment/explanations | No (heuristic fallback) |
| `OPENMETADATA_HOST` | OpenMetadata host URL, e.g. `http://localhost:8585/api` | No (skips OM ingestion) |
| `OPENMETADATA_TOKEN` | OpenMetadata JWT token | No (skips OM ingestion) |
| `GH_TOKEN` | GitHub personal access token | No |
| `CACHE_TTL_SECONDS` | Cache TTL in seconds (default: 43200) | No |
| `REQUEST_TIMEOUT_SECONDS` | Request timeout in seconds (default: 15) | No |
| `COMMENT_SAMPLE_SIZE` | Max comments to sample (default: 100) | No |

### 3. Start the backend

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# or: python3 -m uvicorn backend.main:app --reload
```

### 4. Start the extension frontend (Vite)

In a new terminal:

```bash
cd extension
bun install
bun dev
```

Keep this terminal running during development.

### 5. Load extension in Chrome

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select the `extension/dist` folder
4. Pin the RealityChecker extension

### 6. OpenMetadata setup 

Make sure OpenMetadata is running, then:

```bash
# Check connection
curl http://localhost:8585/health/openmetadata

# Initialize schema, classification, tags, and freshness rules
curl -X POST http://localhost:8585/openmetadata/init
```

Every `/analyze` call auto-ingests into OpenMetadata with lineage and governance tags.

## API Reference

### `POST /analyze`

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

Also accepted:

```bash
# URL as query parameter
curl -X POST "http://localhost:8000/analyze?url=https://youtu.be/EerdGm-ehJQ?si=QBpVXYbezmBr5Eev"

# Alternate JSON keys
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"video_url": "https://youtu.be/EerdGm-ehJQ?si=QBpVXYbezmBr5Eev"}'
```

Response:

```json
{
  "url": "https://youtube.com/watch?v=...",
  "video": { "video_id": "...", "title": "...", "channel": "...", "upload_date": "YYYY-MM-DD" },
  "overall_score": 7.4,
  "confidence": { "level": "high", "value": 0.81, "reasons": ["Transcript available", "91 comments analyzed", "Channel statistics available"] },
  "parameters": {
    "sentiment_quality": { "score": 7.8, "why": "Positive viewer feedback with strong engagement" },
    "recency": { "score": 9.0, "why": "Video was uploaded 34 days ago" },
    "tech_freshness": { "score": 5.5, "why": "Domain: React. 3 modern signal(s)" },
    "creator_credibility": { "score": 8.2, "why": "Based on large following, strong engagement, prolific creator" },
    "engagement_quality": { "score": 7.1, "why": "86 usable comments; comment rate 5.0/1k views; strong like ratio (4.8%)" },
    "topic_match": { "score": 8.0, "why": "has title. has description. 4 tag(s). substantial transcript" }
  },
  "risk_flags": ["no-major-risk-detected"],
  "explanation": "Reasonably useful tutorial with high confidence.",
  "sentiment_detail": { "score": 8.5, "label": "positive", "summary": "...", "llm_used": true },
  "feature_snapshot": { ... },
  "data_availability": { "comments": true, "transcript": true },
  "weights": { "sentiment_quality": 0.15, "recency": 0.15, "tech_freshness": 0.25, "creator_credibility": 0.20, "engagement_quality": 0.10, "topic_match": 0.15 }
}
```

### `GET /`

Health check — returns `{"status": "RealityChecker is running"}`

### `GET /health/openmetadata`

Returns OpenMetadata connection status and version.

### `POST /openmetadata/init`

Initializes OpenMetadata infrastructure: service, database, schema, governance classification with 7 tags, and 6 domain freshness rule tables.

## Scoring Engine

### Parameters and Weights

| Parameter | Weight | Description |
|---|---|---|
| tech_freshness | 0.25 | Modern vs outdated pattern detection across 6 domains (React, Node, Python, Java, JS/TS, DevOps) |
| creator_credibility | 0.20 | Channel followers, like-view ratio, video count, entertainment channel detection |
| recency | 0.15 | Smooth decay curve with evergreen topic exemption |
| sentiment_quality | 0.15 | LLM-based or heuristic per-comment sentiment classification |
| topic_match | 0.15 | Tech keyword density, educational channel bonus, vague content penalty |
| engagement_quality | 0.10 | Comment rate per 1k views, comments per minute, like-view ratio, spam ratio |

### Recency Scoring

Uses a smooth interpolation curve instead of step functions. Evergreen topics (algorithms, data structures, git basics, etc.) receive a minimum score of 7.5 regardless of age.

| Age | Normal Score | Evergreen Score |
|---|---|---|
| Today | 10.0 | 10.0 |
| 4 months | 8.3 | 9.5 |
| 9 months | 6.8 | 8.8 |
| 2 years | 4.0 | 8.0 |
| 3+ years | 1.0-2.0 | 7.5+ |

### Sentiment Analysis

Two paths:

1. **LLM (Groq llama-3.1-8b)**: Analyzes up to 50 comments, returns structured sentiment score + label + summary
2. **Heuristic fallback**: Per-comment classification using strong/mild positive/negative keyword lists, weighted scoring with coverage bonus

### Risk Flags

| Flag | Trigger |
|---|---|
| `outdated-risk-high` | tech_freshness ≤ 3.0 |
| `outdated-risk-medium` | tech_freshness ≤ 6.0 |
| `low-confidence` | confidence level = "low" |
| `low-engagement` | engagement_quality ≤ 3.0 |
| `low-credibility` | creator_credibility ≤ 3.0 |

### Confidence Policy

Starts at 1.00, applies penalties:

- No transcript: -0.25
- < 30 comments: -0.20
- Missing channel stats: -0.15
- LLM fallback used: -0.10

Levels: high (≥0.75), medium (0.45-0.74), low (<0.45)

## OpenMetadata Integration

Every `/analyze` call creates three lineage-tracked entities with governance tags:

```
youtube_video_raw_{id} ──→ feature_snapshot_{id}_{ts} ──→ video_scorecard_{id}_{ts}
                                    ▲
tech_freshness_rules_{domain} ───────┘
```

### How RealityChecker Uses OpenMetadata

OpenMetadata is used as the governance and observability layer around the scoring pipeline.

- **Infrastructure bootstrap (`POST /openmetadata/init`)**
  - Calls `ensure_infrastructure()` to create/ensure:
    - database service `realitychecker`
    - database `youtube_analytics`
    - schema `default`
    - pipeline service `realitychecker_pipeline_service`
    - pipeline `realitychecker_scoring`
    - governance classification + tags
  - Calls `ingest_freshness_rules()` to register `tech_freshness_rules_{domain}` tables for each rule pack (React, Node, Python, Java, JS/TS, DevOps).

- **Per-analysis metadata ingestion (`POST /analyze`)**
  - On each successful analysis, `ingest_analysis(...)` creates three table entities:
    - `youtube_video_raw_{video_id}`
    - `feature_snapshot_{video_id}_{timestamp}`
    - `video_scorecard_{video_id}_{timestamp}`
  - Adds lineage edges:
    - `youtube_video_raw_* -> feature_snapshot_*`
    - `feature_snapshot_* -> video_scorecard_*`
    - `tech_freshness_rules_{domain} -> feature_snapshot_*`
  - Returns ingestion status in API response as `openmetadata` when ingestion succeeds.

- **Governance tagging in practice**
  - `video_scorecard_*` gets tags derived from score outcomes and flags (quality tier, outdated risk, low confidence, low engagement, low credibility, beginner-friendly).
  - Additional conditional tags are applied for `evergreen`, `recentContent`, `highEngagement`, and `spamHeavy`.

- **Data quality and run observability**
  - Creates scorecard-linked data quality test cases via `/dataQuality/testCases` for key thresholds:
    - overall score
    - confidence
    - tech freshness
    - recency
    - creator credibility
    - engagement quality
    - sentiment quality
  - Logs pipeline runs via `/pipelineStatus` with start/end timestamps and success/failure state (`log_pipeline_run(...)`).

- **Health and stats endpoints**
  - `GET /health/openmetadata` validates connectivity/version (`/system/version`).
  - `GET /openmetadata/stats` returns connectivity plus table/database summary.

- **What is and is not persisted**
  - The integration persists metadata entities, lineage, tags, and data quality test definitions.
  - It does not currently write full row-level analysis records into OpenMetadata tables; analysis values are represented in table/column metadata and descriptions.

- **Graceful behavior**
  - If `OPENMETADATA_HOST` or `OPENMETADATA_TOKEN` is missing, backend scoring still works and OpenMetadata operations are skipped.
  - Ingestion failures are non-blocking for `/analyze` responses.

In short, OpenMetadata is used for lineage, governance classification, data quality checks, and pipeline run visibility around every scoring decision.

### Entity Schema

**youtube_video_raw**: Video ID, title, channel, upload date, view/like/comment counts, channel followers

**feature_snapshot**: Recency days, like-view ratio, spam ratio, usable comments, transcript length, keyword signals

**video_scorecard**: Overall score, per-parameter scores with explanations, confidence level/value/reasons, tagged with governance classification

**tech_freshness_rules**: Per-domain rule packs (React, Node, Python, Java, JS/TS, DevOps) with modern/outdated pattern counts

### Governance Tags

| Tag | Applied When |
|---|---|
| `governance.highQuality` | Overall score ≥ 8.0 |
| `governance.moderateQuality` | Score 6.0-7.9 |
| `governance.lowQuality` | Score < 4.0 |
| `governance.outdatedRisk` | Any outdated flag |
| `governance.lowConfidence` | Confidence level = "low" |
| `governance.beginnerFriendly` | High confidence + overall ≥ 7.0 |

## Graceful Degradation

| Data Source | Available | Unavailable |
|---|---|---|
| Video metadata | Full (YouTube API+yt-dlp) | yt-dlp only |
| Comments | YouTube API → yt-dlp fallback | No comments, confidence drops |
| Transcript | Full text | Confidence -0.25 |
| Channel stats | Subscriber/video counts | Missing, confidence -0.15 |
| LLM sentiment | Groq API | Heuristic keyword analysis |

## Project Structure

```
├── backend/
│   ├── main.py                    # FastAPI app, /analyze endpoint
│   ├── config.py                  # Environment config
│   ├── connectors/
│   │   ├── youtube_connector.py   # yt-dlp + YouTube Data API
│   │   ├── comments_connector.py  # YouTube API + yt-dlp fallback
│   │   ├── transcript_connector.py# yt-dlp transcript extraction
│   │   ├── url_utils.py           # YouTube URL parsing
│   │   ├── github_connector.py    # GitHub release API
│   │   └── npm_connector.py       # npm/PyPI registry API
│   ├── scoring/
│   │   ├── trust_score.py         # Main scoring engine (6 params + confidence + risks)
│   │   ├── feature_snapshot.py    # Derived feature computation
│   │   └── rules/
│   │       ├── scoring_rules.py   # Domain detection + freshness scoring logic
│   │       └── tech_freshness.py  # 6 domain pattern packs + scoring weights
│   ├── llm/
│   │   └── provider.py            # Groq (llama-3.1-8b + llama-3.3-70b) with caching
│   ├── openmetadata/
│   │   └── ingest.py               # Entity creation, lineage, governance tags
│   └── scripts/
│       └── test_youtube_api_key.py # Diagnostic for YouTube API key
├── extension/
│   ├── manifest.json              # Chrome MV3 manifest
│   ├── popup.html                  # Dark-themed analysis UI
│   ├── popup.js                    # Popup logic + API calls
│   ├── content.js                  # YouTube page score badge injection
│   ├── content.css                 # Badge styles
│   └── icons/                      # 16/48/128px icons
├── data/
│   └── benchmark_template.csv     # 16 real YouTube URLs across 6 domains
└── docs/
    └── openmetadata_contract.md   # Entity/lineage/tag contract
```

## YouTube API Key Setup

The backend uses YouTube Data API v3 for comments, stats, and channel data, with yt-dlp fallback.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project → **APIs & Services > Library** → enable **YouTube Data API v3**
3. **APIs & Services > Credentials** → create **API key**
4. Restrict to **YouTube Data API v3 only** → set application restriction to **IP addresses** or **None** for dev

```bash
# Test your key
python3 backend/scripts/test_youtube_api_key.py
```

Quota: ~3 units per `/analyze` call, 10,000 units/day = ~3,300 videos/day.

## Benchmarking

```bash
# Run all 16 benchmark URLs
while IFS=, read -r url domain label reason; do
  [[ "$url" == "video_url" ]] && continue
  curl -s -X POST http://localhost:8000/analyze \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"$url\"}" | python3 -m json.tool
done < data/benchmark_template.csv
```

## AI Assistance Declaration

This project was developed using OpenCode with GLM 5.1 and GPT-5.3 Codex for coding support, with limited assistance for ideation and planning.
All architecture, implementation decisions, and final validation were reviewed and finalized by the project author.
