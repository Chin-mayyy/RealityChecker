import os
from pathlib import Path

from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

_BACKEND_DIR = Path(__file__).resolve().parent
_ENV_PATH = _BACKEND_DIR / ".env"
load_dotenv(_ENV_PATH, override=True)
load_dotenv(override=True)

GH_TOKEN = os.getenv("GH_TOKEN")
OPENMETADATA_HOST = os.getenv("OPENMETADATA_HOST")
OPENMETADATA_TOKEN = os.getenv("OPENMETADATA_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "43200"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
COMMENT_SAMPLE_SIZE = int(os.getenv("COMMENT_SAMPLE_SIZE", "100"))
ENABLE_YTDLP_COMMENT_FALLBACK = (
    os.getenv("ENABLE_YTDLP_COMMENT_FALLBACK", "false").strip().lower() == "true"
)
