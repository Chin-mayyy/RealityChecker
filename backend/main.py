from datetime import datetime
import logging
from time import time

from fastapi import Body, FastAPI, HTTPException, Query  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import (  # pyright: ignore[reportMissingImports]
    CORSMiddleware,  # pyright: ignore[reportMissingImports]
)
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]
from yt_dlp.utils import DownloadError  # pyright: ignore[reportMissingModuleSource]

try:
    from backend.config import (
        CACHE_TTL_SECONDS,  # pyright: ignore[reportMissingImports]
    )
    from backend.connectors.comments_connector import (  # pyright: ignore[reportMissingImports]
        get_video_comments,
    )
    from backend.connectors.transcript_connector import (  # pyright: ignore[reportMissingImports]
        get_video_transcript,
    )
    from backend.connectors.url_utils import (  # pyright: ignore[reportMissingImports]
        is_valid_youtube_url,
    )
    from backend.connectors.youtube_connector import (  # pyright: ignore[reportMissingImports]
        get_video_metadata,
    )
    from backend.openmetadata.ingest import (  # pyright: ignore[reportMissingImports]
        check_connection,
        ensure_infrastructure,
        get_stats,
        ingest_analysis,
        ingest_freshness_rules,
        log_pipeline_run,
    )
    from backend.scoring.feature_snapshot import (  # pyright: ignore[reportMissingImports]
        build_feature_snapshot,
    )
    from backend.scoring.trust_score import (
        compute_trust_score,  # pyright: ignore[reportMissingImports]
    )
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import CACHE_TTL_SECONDS
    from connectors.comments_connector import get_video_comments
    from connectors.transcript_connector import get_video_transcript
    from connectors.url_utils import is_valid_youtube_url
    from connectors.youtube_connector import get_video_metadata
    from openmetadata.ingest import (
        check_connection,
        ensure_infrastructure,
        get_stats,
        ingest_analysis,
        ingest_freshness_rules,
        log_pipeline_run,
    )
    from scoring.feature_snapshot import build_feature_snapshot
    from scoring.trust_score import compute_trust_score

app = FastAPI(
    title="RealityChecker API",
    description="Trust scores for YouTube tutorials",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_CACHE: dict[str, tuple[float, dict]] = {}
logger = logging.getLogger("uvicorn.error")


class AnalyzeRequest(BaseModel):
    url: str | None = None
    videoUrl: str | None = None
    video_url: str | None = None


@app.get("/")
async def root():
    return {"status": "RealityChecker is running"}


@app.get("/health/openmetadata")
async def health_openmetadata():
    return check_connection()


@app.get("/openmetadata/stats")
async def openmetadata_stats():
    return get_stats()


@app.post("/openmetadata/init")
async def init_openmetadata():
    ensure_infrastructure()
    rules_result = ingest_freshness_rules()
    return {
        "freshness_rules": "created" if rules_result else "skipped_or_failed",
    }


@app.post("/analyze")
async def analyze(
    payload: AnalyzeRequest = Body(
        default_factory=AnalyzeRequest,
        examples=[
            {"url": "https://youtu.be/EerdGm-ehJQ?si=QBpVXYbezmBr5Eev"},
            {"video_url": "https://youtu.be/EerdGm-ehJQ?si=QBpVXYbezmBr5Eev"},
        ],
    ),
    url: str | None = Query(default=None),
):
    requested_url = _get_requested_url(payload, url)
    request_started = time()
    logger.info("Analyze request received: url=%s", requested_url)

    if not is_valid_youtube_url(requested_url):
        logger.warning("Analyze rejected invalid YouTube URL: %s", requested_url)
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cached_response = _get_cached_response(requested_url)
    if cached_response:
        logger.info(
            "Analyze cache hit: url=%s elapsed=%.2fs",
            requested_url,
            time() - request_started,
        )
        return cached_response

    start_ms = int(time() * 1000)
    success = False
    video_id = "unknown"

    try:
        # Step 1 — get video metadata
        step_started = time()
        logger.info("Analyze step start: metadata")
        video_data = get_video_metadata(requested_url)
        logger.info("Analyze step done: metadata elapsed=%.2fs", time() - step_started)
        video_id = video_data.get("video_id", "unknown")

        # Step 2 — get comments and transcript (with graceful fallbacks)
        step_started = time()
        logger.info("Analyze step start: comments")
        comments_data = get_video_comments(video_data.get("video_id", ""))
        logger.info("Analyze step done: comments elapsed=%.2fs", time() - step_started)

        step_started = time()
        logger.info("Analyze step start: transcript")
        try:
            transcript_data = get_video_transcript(
                video_data.get("canonical_url", requested_url)
            )
        except DownloadError:
            transcript_data = {
                "available": False,
                "source": None,
                "language": None,
                "text": "",
                "chunks": [],
            }
            logger.warning("Analyze transcript unavailable via yt-dlp")
        logger.info("Analyze step done: transcript elapsed=%.2fs", time() - step_started)

        # Step 3 — derive feature snapshot
        step_started = time()
        logger.info("Analyze step start: feature_snapshot")
        feature_snapshot = build_feature_snapshot(
            video_data, comments_data, transcript_data
        )
        logger.info(
            "Analyze step done: feature_snapshot elapsed=%.2fs",
            time() - step_started,
        )

        enriched_video_data = {
            **video_data,
            **feature_snapshot,
            "transcript_available": transcript_data.get("available", False),
            "comments_available": comments_data.get("available", False),
            "usable_comments": comments_data.get("usable_comments", []),
        }

        # Step 4 — compute trust scores (with LLM sentiment + explanations)
        step_started = time()
        logger.info("Analyze step start: scoring")
        trust_data = compute_trust_score(enriched_video_data, use_llm=True)
        logger.info("Analyze step done: scoring elapsed=%.2fs", time() - step_started)

        response_payload = {
            "url": requested_url,
            "video": {
                "video_id": enriched_video_data.get("video_id"),
                "title": enriched_video_data.get("title"),
                "channel": enriched_video_data.get("channel"),
                "upload_date": _format_upload_date(
                    enriched_video_data.get("upload_date")
                ),
            },
            "overall_score": trust_data.get("overall"),
            "confidence": trust_data.get("confidence"),
            "parameters": trust_data.get("parameters"),
            "risk_flags": trust_data.get("risk_flags"),
            "explanation": trust_data.get("explanation"),
            "weights": trust_data.get("weights"),
            "sentiment_detail": trust_data.get("sentiment_detail"),
            "llm_used": trust_data.get("llm_used", False),
            "feature_snapshot": feature_snapshot,
            "data_availability": {
                "comments": comments_data.get("available", False),
                "transcript": transcript_data.get("available", False),
            },
        }

        _set_cached_response(requested_url, response_payload)

        # Step 5 — ingest into OpenMetadata (non-blocking, graceful)
        om_result = None
        step_started = time()
        logger.info("Analyze step start: openmetadata_ingest")
        try:
            om_result = ingest_analysis(
                video_data=enriched_video_data,
                trust_data=trust_data,
                feature_snapshot=feature_snapshot,
            )
        except Exception:
            logger.exception("Analyze openmetadata ingest failed")
        logger.info(
            "Analyze step done: openmetadata_ingest elapsed=%.2fs",
            time() - step_started,
        )

        if om_result:
            response_payload["openmetadata"] = om_result

        success = True
        logger.info(
            "Analyze completed: video_id=%s elapsed=%.2fs",
            video_id,
            time() - request_started,
        )
        return response_payload
    except ValueError as e:
        logger.warning("Analyze failed with validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except DownloadError as e:
        logger.warning("Analyze failed with download error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Analyze failed unexpectedly")
        raise
    finally:
        end_ms = int(time() * 1000)
        try:
            log_pipeline_run(start_ms, end_ms, success, video_id)
        except Exception:
            logger.exception("Pipeline run logging failed")


def _get_requested_url(payload: AnalyzeRequest | None, query_url: str | None) -> str:
    if payload:
        for value in (payload.url, payload.videoUrl, payload.video_url):
            if isinstance(value, str):
                candidate = value.strip()
                if candidate:
                    return candidate

    if query_url and query_url.strip():
        return query_url.strip()

    raise HTTPException(
        status_code=422,
        detail="Provide a YouTube URL in JSON body {'url': '...'} or query parameter ?url=...",
    )


def _format_upload_date(raw_upload_date: str | None) -> str | None:
    if not raw_upload_date:
        return None
    try:
        parsed = datetime.strptime(raw_upload_date, "%Y%m%d")
    except ValueError:
        return raw_upload_date
    return parsed.strftime("%Y-%m-%d")


def _get_cached_response(url: str) -> dict | None:
    key = _cache_key(url)
    cached = _CACHE.get(key)
    if not cached:
        return None
    created_at, payload = cached
    if time() - created_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return payload


def _set_cached_response(url: str, payload: dict) -> None:
    key = _cache_key(url)
    _CACHE[key] = (time(), payload)


def _cache_key(url: str) -> str:
    return url.strip()
