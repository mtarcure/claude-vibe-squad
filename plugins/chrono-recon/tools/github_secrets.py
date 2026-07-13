import httpx
import os
from typing import Optional

def github_leaked_secrets(query: str, org: Optional[str] = None) -> list[dict]:
    token = os.environ.get("GH_TOKEN")
    if not token:
        return [{"error": "GH_TOKEN not set"}]
    q = query
    if org:
        q += f" org:{org}"
    url = f"https://api.github.com/search/code?q={q}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = httpx.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        return [{"repo": item["repository"]["full_name"], "path": item["path"], "url": item["html_url"]} for item in data.get("items", [])[:20]]
    except Exception as e:
        return [{"error": str(e)}]
