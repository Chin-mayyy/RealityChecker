import hashlib
import json
from time import time

try:
    from backend.config import CACHE_TTL_SECONDS, GROQ_API_KEY  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import CACHE_TTL_SECONDS, GROQ_API_KEY

from groq import Groq  # pyright: ignore[reportMissingImports]

_MODEL_SENTIMENT = "llama-3.1-8b-instant"
_MODEL_EXPLANATION = "llama-3.3-70b-versatile"
_MAX_RETRIES = 1
_TIMEOUT_SECONDS = 15

_cache: dict[str, tuple[float, dict]] = {}


def _groq_client() -> Groq | None:
    if not GROQ_API_KEY:
        return None
    return Groq(api_key=GROQ_API_KEY, timeout=_TIMEOUT_SECONDS)


def _cache_key(prompt: str, model: str) -> str:
    raw = f"{model}:{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(prompt: str, model: str) -> dict | None:
    key = _cache_key(prompt, model)
    entry = _cache.get(key)
    if not entry:
        return None
    created_at, payload = entry
    if time() - created_at > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return payload


def _set_cached(prompt: str, model: str, payload: dict) -> None:
    key = _cache_key(prompt, model)
    _cache[key] = (time(), payload)


def call_groq(
    prompt: str,
    model: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 300,
    temperature: float = 0.3,
) -> dict:
    model = model or _MODEL_SENTIMENT
    cached = _get_cached(prompt, model)
    if cached:
        cached["from_cache"] = True
        return cached

    client = _groq_client()
    if client is None:
        return {
            "success": False,
            "error": "GROQ_API_KEY not configured",
            "from_cache": False,
        }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    retries = 0
    last_error = None
    while retries <= _MAX_RETRIES:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content
            text = (content or "").strip()
            result = {
                "success": True,
                "text": text,
                "model": model,
                "from_cache": False,
            }
            _set_cached(prompt, model, result)
            return result
        except Exception as exc:
            last_error = str(exc)
            retries += 1

    return {"success": False, "error": last_error, "from_cache": False}


def analyze_sentiment(comments: list[str], video_title: str = "") -> dict:
    if not comments:
        return {
            "score": 5.0,
            "label": "neutral",
            "summary": "No comments available for sentiment analysis.",
            "llm_used": False,
        }

    sampled = comments[:50]
    comments_text = "\n".join(f"- {c}" for c in sampled)

    system_prompt = (
        "You are a comment sentiment classifier for YouTube tutorial videos. "
        "Respond ONLY with valid JSON. Do not include any text outside the JSON object."
    )

    user_prompt = (
        f'Video title: "{video_title}"\n\n'
        f"Comments from viewers:\n{comments_text}\n\n"
        "Analyze the sentiment of these YouTube comments for a tutorial video. "
        "Respond with ONLY a JSON object with these fields:\n"
        '- "sentiment_score": a number from 1 to 10 where 10=very positive, 1=very negative\n'
        '- "sentiment_label": one of "positive", "negative", "mixed", "neutral"\n'
        '- "summary": a single sentence summarizing the overall sentiment'
    )

    result = call_groq(
        prompt=user_prompt,
        model=_MODEL_SENTIMENT,
        system_prompt=system_prompt,
        max_tokens=200,
        temperature=0.2,
    )

    if not result.get("success"):
        return _heuristic_sentiment(comments, result.get("error"))

    try:
        text = result["text"]
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        score = float(parsed.get("sentiment_score", 5.0))
        score = max(1.0, min(10.0, score))
        return {
            "score": round(score, 1),
            "label": parsed.get("sentiment_label", "mixed"),
            "summary": parsed.get("summary", "Sentiment analysis completed."),
            "llm_used": True,
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return _heuristic_sentiment(comments, "LLM response parse error")


def generate_explanations(
    video_data: dict, parameter_scores: dict, overall: float, risk_flags: list[str]
) -> dict:
    title = video_data.get("title", "Unknown video")
    channel = video_data.get("channel", "Unknown channel")

    params_text = "\n".join(
        f"- {name}: {data['score']}/10" for name, data in parameter_scores.items()
    )
    flags_text = ", ".join(risk_flags) if risk_flags else "none"

    system_prompt = (
        "You are an educational content quality analyst. "
        "Respond ONLY with valid JSON. Do not include any text outside the JSON object."
    )

    user_prompt = (
        f'Video: "{title}" by {channel}\n'
        f"Overall relevance score: {overall}/10\n"
        f"Parameter scores:\n{params_text}\n"
        f"Risk flags: {flags_text}\n\n"
        "For each parameter, write a brief explanation (under 20 words) of why it received that score. "
        "Also write an overall explanation (under 30 words) summarizing the video's learning quality.\n\n"
        "Respond with ONLY a JSON object:\n"
        "{\n"
        '  "sentiment_quality": "brief explanation",\n'
        '  "recency": "brief explanation",\n'
        '  "tech_freshness": "brief explanation",\n'
        '  "creator_credibility": "brief explanation",\n'
        '  "engagement_quality": "brief explanation",\n'
        '  "topic_match": "brief explanation",\n'
        '  "overall_explanation": "overall summary"\n'
        "}"
    )

    result = call_groq(
        prompt=user_prompt,
        model=_MODEL_EXPLANATION,
        system_prompt=system_prompt,
        max_tokens=300,
        temperature=0.3,
    )

    if not result.get("success"):
        return _fallback_explanations(video_data, parameter_scores)

    try:
        text = result["text"]
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        parsed["llm_used"] = True
        return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        return _fallback_explanations(video_data, parameter_scores)


def _heuristic_sentiment(comments: list[str], error: str | None = None) -> dict:
    positive_words = (
        "great",
        "helpful",
        "awesome",
        "thanks",
        "love",
        "excellent",
        "clear",
        "best",
    )
    negative_words = (
        "bad",
        "wrong",
        "outdated",
        "confusing",
        "hate",
        "terrible",
        "waste",
        "boring",
    )

    text = " ".join(comments).lower()
    pos = sum(1 for w in positive_words if w in text)
    neg = sum(1 for w in negative_words if w in text)

    if pos > neg * 2:
        score, label = 7.5, "positive"
    elif neg > pos * 2:
        score, label = 3.0, "negative"
    elif pos > neg:
        score, label = 6.0, "mixed-positive"
    elif neg > pos:
        score, label = 4.0, "mixed-negative"
    else:
        score, label = 5.0, "neutral"

    summary = "Estimated from keyword heuristics"
    if error:
        summary += f" (LLM unavailable: {error})"

    return {
        "score": score,
        "label": label,
        "summary": summary,
        "llm_used": False,
    }


def _fallback_explanations(video_data: dict, parameter_scores: dict) -> dict:
    title = video_data.get("title", "")
    upload_date = video_data.get("upload_date", "")
    days_old = None
    if upload_date:
        try:
            from datetime import datetime

            uploaded = datetime.strptime(upload_date, "%Y%m%d")
            days_old = (datetime.now() - uploaded).days
        except ValueError:
            pass

    explanations = {
        "sentiment_quality": "Estimated from keyword heuristics (LLM unavailable).",
        "recency": f"Video uploaded {days_old} days ago."
        if days_old
        else "Recency estimated from metadata.",
        "tech_freshness": "Estimated from modern/outdated keyword signals.",
        "creator_credibility": "Based on channel reach and engagement health.",
        "engagement_quality": "Derived from comments, like-view ratio, and spam ratio.",
        "topic_match": "Estimated from title/description and transcript coverage.",
        "overall_explanation": "Heuristic-based scoring (LLM explanations unavailable).",
        "llm_used": False,
    }
    return explanations
