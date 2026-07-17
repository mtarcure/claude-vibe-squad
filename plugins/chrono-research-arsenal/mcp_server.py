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
from typing import Any

import arxiv
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chrono-research-arsenal")
logging.getLogger("arxiv").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _ok(payload: Any) -> dict[str, Any]:
    return {"ok": True, "result": payload}


def _err(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": reason, **extra}


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


if __name__ == "__main__":
    mcp.run()
