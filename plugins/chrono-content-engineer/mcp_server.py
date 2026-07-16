"""chrono-content-engineer FastMCP server.

Exposes image / video / audio generation tools backed by:
- OpenAI: gpt-image-2, Sora 2 / Sora 2 Pro
- Gemini: Imagen 4, Veo 3.1, Lyria 3
- xAI: Grok Imagine image and video

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

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_XAI_BASE_URL = "https://api.x.ai/v1"
# Bound the actual inline string returned to MCP callers. For base64 media this
# allows roughly 24 MiB of decoded image/audio data while keeping one data URL
# below 32 MiB; check before concatenation to avoid a second oversized string.
_MAX_INLINE_MEDIA_DATA_URL_CHARS = 32 * 1024 * 1024
_INLINE_MEDIA_CAP_ERROR = "media payload exceeds 32 MiB cap"

_IMAGE_MODEL_ALIASES = {
    "gemini": {
        "gpt-image-2": "imagen-4.0-generate-001",
        "imagen-4": "imagen-4.0-generate-001",
    },
    "xai": {
        "gpt-image-2": "grok-imagine-image-quality",
        "grok-imagine": "grok-imagine-image-quality",
    },
}
_VIDEO_MODEL_ALIASES = {
    "gemini": {
        "sora-2": "veo-3.1-generate-preview",
        "veo-3": "veo-3.1-generate-preview",
    },
    "xai": {
        "sora-2": "grok-imagine-video",
        "grok-imagine": "grok-imagine-video",
    },
}
_AUDIO_MODEL_ALIASES = {
    "lyria-3": "lyria-3-clip-preview",
}


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


def _api_key(provider: str) -> str | None:
    return os.environ.get(f"{provider.upper()}_API_KEY")


def _resolved_model(provider: str, model: str, aliases: dict[str, dict[str, str]]) -> str:
    return aliases.get(provider, {}).get(model, model)


def _dimensions(size: str) -> tuple[str, str]:
    """Translate the existing WIDTHxHEIGHT argument to provider media controls."""
    try:
        width_text, height_text = size.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (AttributeError, TypeError, ValueError):
        return "1:1", "1k"

    if width == height:
        ratio = "1:1"
    elif width * 9 == height * 16:
        ratio = "16:9"
    elif width * 16 == height * 9:
        ratio = "9:16"
    elif width * 3 == height * 4:
        ratio = "4:3"
    elif width * 4 == height * 3:
        ratio = "3:4"
    elif width * 2 == height * 3:
        ratio = "3:2"
    elif width * 3 == height * 2:
        ratio = "2:3"
    else:
        ratio = "1:1"
    resolution = "2k" if max(width, height) > 1536 else "1k"
    return ratio, resolution


def _video_dimensions(size: str) -> tuple[str, str]:
    ratio, _ = _dimensions(size)
    if ratio not in {"16:9", "9:16"}:
        ratio = "16:9"
    try:
        _, height_text = size.lower().split("x", 1)
        height = int(height_text)
    except (AttributeError, TypeError, ValueError):
        height = 720
    resolution = "1080p" if height >= 1080 else "720p"
    return ratio, resolution


def _redacted_excerpt(value: str, limit: int = 200) -> str:
    text = value or ""
    text = "\n".join(
        line for line in text.splitlines()
        if not line.lower().lstrip().startswith(("authorization:", "api-key:", "x-api-key:"))
    )
    for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
        secret = os.environ.get(env_name)
        if secret:
            text = text.replace(secret, "[redacted]")
    return text.strip()[:limit]


def _provider_error_details(response: httpx.Response, provider: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {f"{provider}_raw_excerpt": _redacted_excerpt(response.text)}
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return {f"{provider}_raw_excerpt": _redacted_excerpt(response.text)}
    return {
        f"{provider}_error": {
            "type": str(error.get("type") or error.get("status") or ""),
            "code": str(error.get("code") or ""),
            "param": str(error.get("param") or ""),
            "message_excerpt": _redacted_excerpt(str(error.get("message") or "")),
        }
    }


def _openai_error_details(response: httpx.Response) -> dict[str, Any]:
    return _provider_error_details(response, "openai")


def _http_error(provider: str, response: httpx.Response) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"HTTP {response.status_code} {response.reason_phrase}",
        "provider": provider,
        **_provider_error_details(response, provider),
    }


def _inline_media_result(
    mime_type: str,
    encoded_data: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    prefix = f"data:{mime_type};base64,"
    if len(prefix) + len(encoded_data) > _MAX_INLINE_MEDIA_DATA_URL_CHARS:
        return {
            "ok": False,
            "error": _INLINE_MEDIA_CAP_ERROR,
            "provider": provider,
            "model": model,
        }
    return {
        "ok": True,
        "url": f"{prefix}{encoded_data}",
        "provider": provider,
        "model": model,
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
      - gemini -> POST /v1beta/models/{imagen-model}:predict
        (Imagen 4 is deprecated and scheduled to shut down 2026-08-17.)
      - xai    -> POST /v1/images/generations (grok-imagine-image-quality)

    Returns {ok, url, provider, model, error}. Network errors surface
    via Rule 17.1 - status_code + reason_phrase only, never str(exc).
    """
    provider = provider.strip().lower()
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

    if provider == "gemini":
        api_key = _api_key(provider)
        if not api_key:
            return {"ok": False, "error": "GEMINI_API_KEY missing"}
        resolved_model = _resolved_model(provider, model, _IMAGE_MODEL_ALIASES)
        aspect_ratio, resolution = _dimensions(size)
        parameters: dict[str, Any] = {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio if aspect_ratio in {"1:1", "3:4", "4:3", "9:16", "16:9"} else "1:1",
            "imageSize": resolution.upper(),
        }
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    f"{_GEMINI_BASE_URL}/models/{resolved_model}:predict",
                    headers={"x-goog-api-key": api_key},
                    json={"instances": [{"prompt": prompt}], "parameters": parameters},
                )
            r.raise_for_status()
            data = r.json()
            predictions = data.get("predictions", []) if isinstance(data, dict) else []
            image = next(
                (
                    prediction
                    for prediction in predictions
                    if isinstance(prediction, dict) and prediction.get("bytesBase64Encoded")
                ),
                {},
            )
            encoded_data = str(image.get("bytesBase64Encoded") or "")
            if not encoded_data:
                return {
                    "ok": False,
                    "error": "invalid response: image data missing",
                    "provider": provider,
                    "model": resolved_model,
                }
            mime_type = str(image.get("mimeType") or "image/png")
            return _inline_media_result(mime_type, encoded_data, provider, resolved_model)
        except httpx.HTTPStatusError as e:
            return _http_error(provider, e.response)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}

    if provider == "xai":
        api_key = _api_key(provider)
        if not api_key:
            return {"ok": False, "error": "XAI_API_KEY missing"}
        resolved_model = _resolved_model(provider, model, _IMAGE_MODEL_ALIASES)
        aspect_ratio, resolution = _dimensions(size)
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    f"{_XAI_BASE_URL}/images/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "prompt": prompt,
                        "model": resolved_model,
                        "n": 1,
                        "aspect_ratio": aspect_ratio,
                        "resolution": resolution,
                    },
                )
            r.raise_for_status()
            data = r.json()
            images = data.get("data", []) if isinstance(data, dict) else []
            url = str(images[0].get("url") or "") if images and isinstance(images[0], dict) else ""
            if not url:
                return {
                    "ok": False,
                    "error": "invalid response: image URL missing",
                    "provider": provider,
                    "model": resolved_model,
                }
            return {"ok": True, "url": url, "provider": provider, "model": resolved_model}
        except httpx.HTTPStatusError as e:
            return _http_error(provider, e.response)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}

    return {"ok": False, "error": f"unsupported provider: {provider}"}


@mcp.tool()
def generate_video(
    prompt: str,
    provider: str = "openai",
    model: str = "sora-2",
    seconds: int = 8,
    size: str = "1280x720",
) -> dict[str, Any]:
    """Generate a video from a text prompt — async job-id pattern.

    OpenAI Sora, Gemini Veo 3.1, and xAI Grok Imagine all return a job ID.
    Poll the provider's status endpoint until generation completes.

    Returns {ok, job_id, provider, model, status, error}.
    """
    provider = provider.strip().lower()
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

    if provider == "gemini":
        api_key = _api_key(provider)
        if not api_key:
            return {"ok": False, "error": "GEMINI_API_KEY missing"}
        resolved_model = _resolved_model(provider, model, _VIDEO_MODEL_ALIASES)
        aspect_ratio, resolution = _video_dimensions(size)
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    f"{_GEMINI_BASE_URL}/models/{resolved_model}:predictLongRunning",
                    headers={"x-goog-api-key": api_key},
                    json={
                        "instances": [{"prompt": prompt}],
                        "parameters": {
                            "aspectRatio": aspect_ratio,
                            "durationSeconds": str(seconds),
                            "resolution": resolution,
                        },
                    },
                )
            r.raise_for_status()
            data = r.json()
            job_id = str(data.get("name") or "") if isinstance(data, dict) else ""
            if not job_id:
                return {
                    "ok": False,
                    "error": "invalid response: operation name missing",
                    "provider": provider,
                    "model": resolved_model,
                }
            return {
                "ok": True,
                "job_id": job_id,
                "provider": provider,
                "model": resolved_model,
                "status": "queued",
            }
        except httpx.HTTPStatusError as e:
            return _http_error(provider, e.response)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}

    if provider == "xai":
        api_key = _api_key(provider)
        if not api_key:
            return {"ok": False, "error": "XAI_API_KEY missing"}
        resolved_model = _resolved_model(provider, model, _VIDEO_MODEL_ALIASES)
        aspect_ratio, _ = _video_dimensions(size)
        # The wired text-to-video model supports 480p/720p, not 1080p.
        resolution = "720p"
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    f"{_XAI_BASE_URL}/videos/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "prompt": prompt,
                        "model": resolved_model,
                        "duration": seconds,
                        "aspect_ratio": aspect_ratio,
                        "resolution": resolution,
                    },
                )
            r.raise_for_status()
            data = r.json()
            job_id = str(data.get("request_id") or "") if isinstance(data, dict) else ""
            if not job_id:
                return {
                    "ok": False,
                    "error": "invalid response: request ID missing",
                    "provider": provider,
                    "model": resolved_model,
                }
            return {
                "ok": True,
                "job_id": job_id,
                "provider": provider,
                "model": resolved_model,
                "status": "queued",
            }
        except httpx.HTTPStatusError as e:
            return _http_error(provider, e.response)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}

    return {"ok": False, "error": f"unsupported provider: {provider}"}


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
    model: str = "lyria-3-clip-preview",
    duration_seconds: int = 30,
) -> dict[str, Any]:
    """Generate audio (music / sound) from a text prompt.

    Gemini Lyria 3 is the music-generation path. For voice / TTS / SFX, use the
    ElevenLabs MCP (`mcp__elevenlabs__text_to_speech` etc.) declared in
    plugin.json — this tool covers music gen.

    Returns {ok, url, provider, model, error}.
    """
    provider = provider.strip().lower()
    if provider == "gemini":
        api_key = _api_key(provider)
        if not api_key:
            return {"ok": False, "error": "GEMINI_API_KEY missing"}
        resolved_model = _AUDIO_MODEL_ALIASES.get(model, model)
        audio_prompt = prompt
        if resolved_model == "lyria-3-pro-preview":
            audio_prompt = f"Create an approximately {duration_seconds}-second track. {prompt}"
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(
                    f"{_GEMINI_BASE_URL}/interactions",
                    headers={"x-goog-api-key": api_key},
                    json={"model": resolved_model, "input": audio_prompt},
                )
            r.raise_for_status()
            data = r.json()
            audio: dict[str, Any] = {}
            for step in data.get("steps", []) if isinstance(data, dict) else []:
                if not isinstance(step, dict) or step.get("type") != "model_output":
                    continue
                for content in step.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "audio":
                        audio = content
            encoded_data = str(audio.get("data") or "")
            if not encoded_data:
                return {
                    "ok": False,
                    "error": "invalid response: audio data missing",
                    "provider": provider,
                    "model": resolved_model,
                }
            mime_type = str(audio.get("mime_type") or "audio/mpeg")
            return _inline_media_result(mime_type, encoded_data, provider, resolved_model)
        except httpx.HTTPStatusError as e:
            return _http_error(provider, e.response)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "provider": provider}
    return {"ok": False, "error": f"unsupported provider: {provider}"}


if __name__ == "__main__":
    mcp.run()
