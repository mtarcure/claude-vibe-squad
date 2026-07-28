import httpx
import os
from typing import Optional


def _redacted_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: status={exc.response.status_code}"
    if isinstance(exc, httpx.RequestError) and exc.__cause__ is not None:
        return f"{type(exc).__name__}: reason={type(exc.__cause__).__name__}"
    return type(exc).__name__


def github_leaked_secrets(query: str, org: Optional[str] = None) -> list[dict]:
    token = os.environ.get("GH_TOKEN")
    if not token:
        return [{"error": "GH_TOKEN not set"}]
    q = query
    if org:
        q += f" org:{org}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    try:
        resp = httpx.get(
            "https://api.github.com/search/code",
            params={"q": q},
            headers=headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "repo": item["repository"]["full_name"],
                "path": item["path"],
                "url": item["html_url"],
            }
            for item in data.get("items", [])[:20]
        ]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return [{"error": _redacted_error(exc)}]
