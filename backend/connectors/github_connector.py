import requests

try:
    from backend.config import GH_TOKEN
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from config import GH_TOKEN


def _github_headers() -> dict:
    if GH_TOKEN:
        return {"Authorization": f"token {GH_TOKEN}"}
    return {}


def get_latest_release(repo: str) -> dict:
    """repo format: 'facebook/react'"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    response = requests.get(url, headers=_github_headers(), timeout=10)
    response.raise_for_status()
    data = response.json()
    return {
        "repo": repo,
        "latest_version": data.get("tag_name"),
        "published_at": data.get("published_at"),
        "release_name": data.get("name"),
    }
