"""chrono-research-arsenal — shared external research arsenal MCP.

Phase 2 ships: arxiv_search (proof-of-shape).
Phase 3 adds: brave_search, serper_search, perplexity_query, hn_search, youtube_transcript,
              github_query, reddit_top, grok_x_search, apify_twitter, rt_markitdown_convert.

Used by all chrono roles needing external data (research, scout, scraping, etc).
Rebuilt from a predecessor project's research tools using FastMCP for consistency.
Sync `def` for blocking ops (FastMCP runs them in a background thread).
Per Rule 17.1 (TOOLS.md): never str(httpx_exc) — only status_code + reason_phrase.
"""
from __future__ import annotations

import os
import logging
import json
import base64
import binascii
import mimetypes
from typing import Any

import arxiv
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chrono-research-arsenal")
logging.getLogger("arxiv").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

FIRECRAWL_API_BASE = "https://api.firecrawl.dev/v2"
FIRECRAWL_PARSE_MAX_BYTES = 10 * 1024 * 1024
FIRECRAWL_PARSE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".odt",
    ".pdf",
    ".rtf",
    ".xls",
    ".xlsx",
}


def _ok(payload: Any) -> dict[str, Any]:
    return {"ok": True, "result": payload}


def _err(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": reason, **extra}


def _firecrawl_key() -> str | None:
    """Read the Firecrawl credential at call time without logging or returning it."""
    return os.environ.get("FIRECRAWL_API_KEY") or None


def _firecrawl_json_request(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    api_key = _firecrawl_key()
    if not api_key:
        return _err("FIRECRAWL_API_KEY missing")
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{FIRECRAWL_API_BASE}/{path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        return _ok(response.json())
    except httpx.HTTPStatusError as exc:
        return _err(
            "firecrawl_http_error",
            status_code=exc.response.status_code,
            reason_phrase=exc.response.reason_phrase,
        )
    except Exception as exc:
        return _err(f"firecrawl_error: {type(exc).__name__}")


def _firecrawl_formats(formats: list[str] | None) -> list[str]:
    allowed = {"markdown", "html", "rawHtml", "links", "images", "summary"}
    requested = formats or ["markdown"]
    normalized = [str(value) for value in requested if str(value) in allowed]
    return normalized or ["markdown"]


def _coerce_result(item: Any, source_hint: str) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or item.get("url") or "").strip()
    url = str(item.get("url") or "").strip()
    snippet = str(item.get("snippet") or item.get("summary") or "").strip()
    source = str(item.get("source") or source_hint).strip() or source_hint
    if not url:
        return None
    return {"title": title or url, "url": url, "snippet": snippet, "source": source}


def _message_text_and_citations(response_data: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    texts: list[str] = []
    citations: list[dict[str, Any]] = []
    for output in response_data.get("output", []):
        if output.get("type") != "message":
            continue
        for content in output.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
            for annotation in content.get("annotations", []):
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    citations.append(annotation)
    return "\n".join(texts).strip(), citations


def _tool_source_urls(response_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for output in response_data.get("output", []):
        if output.get("type") not in {"web_search_call", "x_search_call"}:
            continue
        action = output.get("action") or {}
        for source in action.get("sources", []):
            url = source.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _openalex_fallback(query: str, max_results: int) -> dict[str, Any]:
    """Fallback academic search when export.arxiv.org keyword search is throttled."""
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(
                "https://api.openalex.org/works",
                params={
                    "search": query,
                    "per-page": max_results,
                    "select": "id,title,doi,publication_year,primary_location,authorships,abstract_inverted_index",
                },
                headers={"User-Agent": "claude-vibe-squad/1.0"},
            )
        response.raise_for_status()
        data = response.json()
        papers = []
        for item in data.get("results", []):
            authors = []
            for authorship in item.get("authorships", [])[:8]:
                author = authorship.get("author") or {}
                name = author.get("display_name")
                if name:
                    authors.append(name)
            location = item.get("primary_location") or {}
            papers.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "summary": None,
                    "authors": authors,
                    "published": item.get("publication_year"),
                    "pdf_url": location.get("pdf_url"),
                    "url": location.get("landing_page_url") or item.get("doi") or item.get("id"),
                    "source": "openalex_fallback",
                }
            )
        return _ok({"papers": papers, "source": "openalex_fallback"})
    except httpx.HTTPStatusError as exc:
        return _err("openalex_http_error", status_code=exc.response.status_code)
    except Exception as exc:
        return _err(f"openalex_error: {type(exc).__name__}")


@mcp.tool()
def arxiv_search(
    query: str,
    max_results: int = 10,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Search arXiv. Returns paper metadata: id, title, summary, authors, published, pdf_url.

    `categories` filters by arXiv category (e.g. ["cs.AI", "cs.CL", "cs.LG"]).
    When supplied, query is wrapped as ``(cat:cs.AI OR cat:cs.CL OR ...) AND (<query>)``.
    """
    try:
        full_query = query
        if categories:
            cat_clause = " OR ".join(f"cat:{c}" for c in categories)
            full_query = f"({cat_clause}) AND ({query})"
        max_results = max(1, min(int(max_results), 10))
        # The arXiv API returns 429 under load; the arxiv package default retry
        # path can exceed model-lane tool timeouts. Fail fast and let the lane
        # use its approved fallback instead of blocking the whole task.
        client = arxiv.Client(page_size=max_results, delay_seconds=0.0, num_retries=0)
        search = arxiv.Search(
            query=full_query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        papers = []
        for r in client.results(search):
            papers.append({
                "id": r.entry_id,
                "title": r.title,
                "summary": r.summary,
                "authors": [a.name for a in r.authors],
                "published": r.published.isoformat() if r.published else None,
                "pdf_url": r.pdf_url,
            })
        return _ok({"papers": papers})
    except arxiv.HTTPError:
        return _openalex_fallback(query, max_results)
    except Exception as exc:
        # arxiv lib raises various exception types; we only want class name in the error,
        # never the message (could contain query/network details we don't want to leak).
        return _err(f"arxiv_error: {type(exc).__name__}")


@mcp.tool()
def xai_search(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search web / X / news via xAI Responses API search tools.

    Replaces deprecated xAI Live Search. Replaces broken Twitter API path
    (operator's TWITTER_BEARER + access-token-secret are auth-failed; xAI's
    native X integration is the chosen alternative — see
    docs/migrations/twitter-broken-credentials.md path A).

    Args:
      query: Free-text search query
      sources: Optional list of source kinds. Default: ["web", "x", "news"]
      max_results: Max items per source (default 10)

    Returns {ok, results: [{title, url, snippet, source}], error}. Errors
    surface via Rule 17.1 — status_code + reason_phrase, never str(exc).
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "XAI_API_KEY missing"}
    requested_sources = [str(s).lower() for s in (sources or ["web", "x", "news"])]
    allowed_sources = {"web", "x", "news"}
    unknown_sources = sorted(set(requested_sources) - allowed_sources)
    if unknown_sources:
        return {"ok": False, "error": f"unsupported sources: {', '.join(unknown_sources)}", "query": query}

    max_results = max(1, min(int(max_results), 10))
    tools: list[dict[str, Any]] = []
    if "web" in requested_sources or "news" in requested_sources:
        tools.append({"type": "web_search"})
    if "x" in requested_sources or "news" in requested_sources:
        tools.append({"type": "x_search"})
    if not tools:
        return {"ok": False, "error": "no search sources requested", "query": query}

    source_hint = "news" if requested_sources == ["news"] else requested_sources[0]
    prompt = (
        "Use the enabled xAI search tools to search for the user's query. "
        f"Return ONLY valid JSON with this exact shape: "
        f'{{"results":[{{"title":"...","url":"https://...","snippet":"one sentence","source":"web|x|news"}}]}}. '
        f"Return at most {max_results} results. Every result must include a real URL "
        f"found through the search tool or citation. Prefer source labels from this requested set: "
        f"{requested_sources}.\n\nQuery: {query}"
    )
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-4.5",
                    "input": [{"role": "user", "content": prompt}],
                    "tools": tools,
                    "store": False,
                    "text": {"format": {"type": "json_object"}},
                },
            )
        r.raise_for_status()
        data = r.json()
        text, citations = _message_text_and_citations(data)
        results: list[dict[str, str]] = []
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError:
            parsed = {}
        for item in parsed.get("results", []):
            result = _coerce_result(item, source_hint)
            if result:
                results.append(result)

        seen = {item["url"] for item in results}
        for citation in citations:
            url = citation.get("url")
            if url and url not in seen:
                title = str(citation.get("title") or url)
                results.append({"title": title, "url": url, "snippet": "", "source": source_hint})
                seen.add(url)
            if len(results) >= max_results:
                break

        for url in _tool_source_urls(data):
            if url not in seen:
                results.append({"title": url, "url": url, "snippet": "", "source": source_hint})
                seen.add(url)
            if len(results) >= max_results:
                break

        if not results:
            return {"ok": False, "error": "no_results", "query": query}

        return {
            "ok": True,
            "results": results[:max_results],
            "query": query,
            "endpoint": "https://api.x.ai/v1/responses",
        }
    except httpx.HTTPStatusError as e:
        return {
            "ok": False,
            "error": f"HTTP {e.response.status_code} {e.response.reason_phrase}",
            "query": query,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}", "query": query}


@mcp.tool()
def firecrawl_scrape(
    url: str,
    formats: list[str] | None = None,
    only_main_content: bool = True,
    wait_for_ms: int = 0,
    timeout_ms: int = 60_000,
) -> dict[str, Any]:
    """Scrape one public URL through Firecrawl API v2.

    The API key is read only from ``FIRECRAWL_API_KEY``. Custom request headers
    are intentionally not accepted so callers cannot forward ambient secrets.
    """
    timeout_ms = max(1_000, min(int(timeout_ms), 120_000))
    payload = {
        "url": url,
        "formats": _firecrawl_formats(formats),
        "onlyMainContent": bool(only_main_content),
        "waitFor": max(0, min(int(wait_for_ms), 30_000)),
        "timeout": timeout_ms,
        "storeInCache": False,
        "zeroDataRetention": True,
    }
    return _firecrawl_json_request("scrape", payload, timeout=(timeout_ms / 1000) + 10)


@mcp.tool()
def firecrawl_crawl(
    url: str,
    max_pages: int = 10,
    max_discovery_depth: int = 2,
    formats: list[str] | None = None,
    only_main_content: bool = True,
) -> dict[str, Any]:
    """Start a bounded Firecrawl API v2 crawl and return its asynchronous job ID."""
    payload = {
        "url": url,
        "limit": max(1, min(int(max_pages), 100)),
        "maxDiscoveryDepth": max(0, min(int(max_discovery_depth), 10)),
        "allowExternalLinks": False,
        "zeroDataRetention": True,
        "scrapeOptions": {
            "formats": _firecrawl_formats(formats),
            "onlyMainContent": bool(only_main_content),
            "storeInCache": False,
        },
    }
    return _firecrawl_json_request("crawl", payload, timeout=70.0)


@mcp.tool()
def firecrawl_parse(
    filename: str,
    content_base64: str,
    formats: list[str] | None = None,
    only_main_content: bool = True,
) -> dict[str, Any]:
    """Parse caller-supplied document bytes through Firecrawl API v2.

    This operation accepts explicit base64 content instead of a filesystem path,
    preventing the MCP from becoming an arbitrary local-file exfiltration primitive.
    Files are limited to 10 MiB and to Firecrawl's documented document formats.
    """
    api_key = _firecrawl_key()
    if not api_key:
        return _err("FIRECRAWL_API_KEY missing")
    safe_name = os.path.basename(filename)
    extension = os.path.splitext(safe_name)[1].lower()
    if not safe_name or safe_name != filename or extension not in FIRECRAWL_PARSE_EXTENSIONS:
        return _err("unsupported_or_unsafe_filename")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        return _err("invalid_base64")
    if not content or len(content) > FIRECRAWL_PARSE_MAX_BYTES:
        return _err("document_size_out_of_bounds", max_bytes=FIRECRAWL_PARSE_MAX_BYTES)

    options = {
        "formats": _firecrawl_formats(formats),
        "onlyMainContent": bool(only_main_content),
        "zeroDataRetention": True,
    }
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    try:
        with httpx.Client(timeout=130.0) as client:
            response = client.post(
                f"{FIRECRAWL_API_BASE}/parse",
                headers={"Authorization": f"Bearer {api_key}"},
                files={
                    "file": (safe_name, content, content_type),
                    "options": (None, json.dumps(options), "application/json"),
                },
            )
        response.raise_for_status()
        return _ok(response.json())
    except httpx.HTTPStatusError as exc:
        return _err(
            "firecrawl_http_error",
            status_code=exc.response.status_code,
            reason_phrase=exc.response.reason_phrase,
        )
    except Exception as exc:
        return _err(f"firecrawl_error: {type(exc).__name__}")


if __name__ == "__main__":
    mcp.run()
