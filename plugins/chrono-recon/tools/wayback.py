import httpx
from typing import Optional


def _redacted_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: status={exc.response.status_code}"
    if isinstance(exc, httpx.RequestError) and exc.__cause__ is not None:
        return f"{type(exc).__name__}: reason={type(exc.__cause__).__name__}"
    return type(exc).__name__


def wayback_snapshots(
    url: str, from_date: Optional[str] = None, to_date: Optional[str] = None
) -> list[dict]:
    params = {"url": url, "output": "json", "limit": 50}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    try:
        resp = httpx.get(
            "https://web.archive.org/cdx/search/cdx",
            params=params,
            timeout=15.0,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return []
        headers = rows[0]
        return [dict(zip(headers, row)) for row in rows[1:]]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        return [{"error": _redacted_error(exc)}]
