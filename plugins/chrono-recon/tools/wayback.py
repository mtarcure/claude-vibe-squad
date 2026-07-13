import httpx
from typing import Optional

def wayback_snapshots(url: str, from_date: Optional[str] = None, to_date: Optional[str] = None) -> list[dict]:
    api = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&limit=50"
    if from_date:
        api += f"&from={from_date}"
    if to_date:
        api += f"&to={to_date}"
    try:
        resp = httpx.get(api, timeout=15.0)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return []
        headers = rows[0]
        return [dict(zip(headers, row)) for row in rows[1:]]
    except Exception as e:
        return [{"error": str(e)}]
