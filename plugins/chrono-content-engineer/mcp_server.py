"""chrono-content-engineer FastMCP server.

Exposes image / video / audio generation tools backed by:
- OpenAI: DALL-E (gpt-image-2), Sora 2 / Sora 2 Pro
- Gemini: Imagen 4, Veo 3, Lyria 3, Nano Banana
- xAI: Grok Imagine

External MCPs visible alongside (NOT proxied through this server):
- Higgsfield (hosted MCP, OAuth) - cinematic image+video
- ElevenLabs (official MCP, uvx) - audio suite
- codex (codex mcp serve) - tool-bearing dispatch loop

Rule 17.1 - never str(httpx_exc); use status_code + reason_phrase.
Atomic writes for any vault sidecar - tmp + fsync + os.replace.
Severity vocabulary: critical/high/medium/low/info canonical only.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chrono-content-engineer")


def _openai_key_info() -> tuple[str | None, dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key is None:
        return None, {
            "present": False,
            "source": "missing",
            "redacted_prefix": "",
            "length": 0,
        }

    source = "manifest_passthrough_env"
    if api_key.startswith("${") and api_key.endswith("}"):
        source = "literal_manifest_placeholder"

    return api_key, {
        "present": bool(api_key),
        "source": source,
        "redacted_prefix": f"{api_key[:8]}..." if api_key else "",
        "length": len(api_key),
    }


def _redacted_excerpt(value: str, limit: int = 200) -> str:
    text = value or ""
    text = "\n".join(
        line for line in text.splitlines()
        if not line.lower().lstrip().startswith(("authorization:", "api-key:", "x-api-key:"))
    )
    text = text.replace(os.environ.get("OPENAI_API_KEY") or "\0", "[redacted]")
    return text.strip()[:limit]


def _openai_error_details(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"openai_raw_excerpt": _redacted_excerpt(response.text)}
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return {"openai_raw_excerpt": _redacted_excerpt(response.text)}
    return {
        "openai_error": {
            "type": str(error.get("type") or ""),
            "code": str(error.get("code") or ""),
            "param": str(error.get("param") or ""),
            "message_excerpt": _redacted_excerpt(str(error.get("message") or "")),
        }
    }


@mcp.tool()
def generate_image(
    prompt: str,
    provider: str = "openai",
    model: str = "gpt-image-2",
    size: str = "1024x1024",
) -> dict[str, Any]:
    """Generate an image from a text prompt.

    Provider routing:
      - openai -> POST /v1/images/generations (gpt-image-2 / dall-e-3)
      - gemini -> POST /v1/images:generate (imagen-4)
      - xai    -> POST /v1/images/generations (grok-imagine)

    Returns {ok, url, provider, model, error}. Network errors surface
    via Rule 17.1 - status_code + reason_phrase only, never str(exc).
    """
    if provider == "openai":
        api_key, _ = _openai_key_info()
        if not api_key:
            return {"ok": False, "error": "OPENAI_API_KEY missing"}
        try:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"prompt": prompt, "model": model, "size": size, "n": 1},
                )
            r.raise_for_status()
            data = r.json()
            url = data.get("data", [{}])[0].get("url", "")
            return {"ok": True, "url": url, "provider": provider, "model": model}
        except httpx.HTTPStatusError as e:
            return {
                "ok": False,
                "error": f"HTTP {e.response.status_code} {e.response.reason_phrase}",
                "provider": provider,
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}
    return {"ok": False, "error": f"provider not yet wired: {provider}"}


@mcp.tool()
def generate_video(
    prompt: str,
    provider: str = "openai",
    model: str = "sora-2",
    seconds: int = 8,
    size: str = "1280x720",
) -> dict[str, Any]:
    """Generate a video from a text prompt — async job-id pattern.

    OpenAI Sora 2 returns a job_id; caller polls GET /v1/videos/{job_id}
    until status=completed, then GET /v1/videos/{job_id}/content for MP4.

    Returns {ok, job_id, provider, model, status, error}.
    """
    if provider == "openai":
        api_key, _ = _openai_key_info()
        if not api_key:
            return {"ok": False, "error": "OPENAI_API_KEY missing"}
        try:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    "https://api.openai.com/v1/videos",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "prompt": prompt,
                        "size": size,
                        "seconds": str(seconds),
                    },
                )
            r.raise_for_status()
            data = r.json()
            return {
                "ok": True,
                "job_id": data.get("id", ""),
                "provider": provider,
                "model": model,
                "status": data.get("status", "queued"),
            }
        except httpx.HTTPStatusError as e:
            return {
                "ok": False,
                "error": f"HTTP {e.response.status_code} {e.response.reason_phrase}",
                "provider": provider,
                **_openai_error_details(e.response),
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}
    return {"ok": False, "error": f"provider not yet wired: {provider}"}


@mcp.tool()
def openai_auth_diagnostic() -> dict[str, Any]:
    """Probe OpenAI video auth without creating media or spending credits."""
    api_key, key_info = _openai_key_info()
    result: dict[str, Any] = {
        "ok": False,
        "provider": "openai",
        "key": key_info,
        "probe": "GET /v1/videos?limit=1",
    }
    if not api_key:
        result["error"] = "OPENAI_API_KEY missing"
        return result

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                "https://api.openai.com/v1/videos",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"limit": 1},
            )
        result["status_code"] = r.status_code
        result["reason"] = r.reason_phrase
        result["ok"] = 200 <= r.status_code < 300
        if not result["ok"]:
            result["error_type"] = r.json().get("error", {}).get("type", "")
        return result
    except httpx.HTTPStatusError as e:
        return {
            **result,
            "status_code": e.response.status_code,
            "reason": e.response.reason_phrase,
            "error_type": e.response.json().get("error", {}).get("type", ""),
        }
    except Exception as e:
        return {**result, "error": f"{type(e).__name__}"}


@mcp.tool()
def generate_audio(
    prompt: str,
    provider: str = "gemini",
    model: str = "lyria-3",
    duration_seconds: int = 30,
) -> dict[str, Any]:
    """Generate audio (music / sound) from a text prompt.

    Gemini lyria-3 is the primary path. For voice / TTS / SFX, use the
    ElevenLabs MCP (`mcp__elevenlabs__text_to_speech` etc.) declared in
    plugin.json — this tool covers music gen.

    Returns {ok, url, provider, model, error}.
    """
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {"ok": False, "error": "GEMINI_API_KEY missing"}
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/lyria-3:generateMusic",
                    headers={"x-goog-api-key": api_key},
                    json={
                        "prompt": prompt,
                        "duration_seconds": duration_seconds,
                    },
                )
            r.raise_for_status()
            data = r.json()
            return {
                "ok": True,
                "url": data.get("audio_uri", ""),
                "provider": provider,
                "model": model,
            }
        except httpx.HTTPStatusError as e:
            return {
                "ok": False,
                "error": f"HTTP {e.response.status_code} {e.response.reason_phrase}",
                "provider": provider,
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}
    return {"ok": False, "error": f"provider not yet wired: {provider}"}


if __name__ == "__main__":
    mcp.run()
