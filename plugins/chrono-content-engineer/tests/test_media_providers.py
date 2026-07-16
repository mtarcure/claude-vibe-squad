from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import httpx


MODULE_PATH = Path(__file__).parents[1] / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("chrono_content_engineer_mcp", MODULE_PATH)
assert SPEC and SPEC.loader
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


def response(status: int, payload: object | None = None, text: str | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://provider.invalid/test")
    if payload is not None:
        return httpx.Response(status, json=payload, request=request)
    return httpx.Response(status, text=text or "", request=request)


class ProviderRoutingTests(unittest.TestCase):
    def call_with_response(self, result: httpx.Response, function, **kwargs):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.post.return_value = result
        with patch.object(media.httpx, "Client", return_value=client):
            value = function(**kwargs)
        return value, client.post.call_args

    def test_gemini_image_routes_to_imagen_and_returns_data_url(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-secret"}):
            result, call = self.call_with_response(
                response(
                    200,
                    {
                        "predictions": [
                            {"safetyAttributes": {"contentType": "Positive Prompt"}},
                            {"bytesBase64Encoded": "aW1hZ2U=", "mimeType": "image/png"},
                        ]
                    },
                ),
                media.generate_image,
                prompt="a blue square",
                provider="GEMINI",
                model="imagen-4",
                size="1024x1024",
            )

        self.assertEqual(call.args[0], f"{media._GEMINI_BASE_URL}/models/imagen-4.0-generate-001:predict")
        self.assertEqual(call.kwargs["headers"], {"x-goog-api-key": "gemini-test-secret"})
        self.assertEqual(call.kwargs["json"]["instances"], [{"prompt": "a blue square"}])
        self.assertEqual(call.kwargs["json"]["parameters"]["aspectRatio"], "1:1")
        self.assertEqual(
            result,
            {
                "ok": True,
                "url": "data:image/png;base64,aW1hZ2U=",
                "provider": "gemini",
                "model": "imagen-4.0-generate-001",
            },
        )

    def test_gemini_image_all_safety_records_returns_clean_missing_data_error(self):
        secret = "gemini-safety-secret-that-must-not-escape"
        provider_body_marker = "provider-safety-body-must-not-escape"
        payload = {
            "predictions": [
                {"safetyAttributes": {"contentType": "Positive Prompt", "detail": secret}},
                {"raiFilteredReason": provider_body_marker},
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": secret}):
            result, _ = self.call_with_response(
                response(200, payload),
                media.generate_image,
                prompt="a filtered image",
                provider="gemini",
                model="imagen-4",
            )

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "invalid response: image data missing",
                "provider": "gemini",
                "model": "imagen-4.0-generate-001",
            },
        )
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(provider_body_marker, repr(result))

    def test_gemini_image_data_url_at_cap_passes(self):
        encoded_data = "aW1hZ2U="
        prefix = "data:image/png;base64,"
        exact_cap = len(prefix) + len(encoded_data)
        self.assertEqual(media._MAX_INLINE_MEDIA_DATA_URL_CHARS, 32 * 1024 * 1024)
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-secret"}),
            patch.object(media, "_MAX_INLINE_MEDIA_DATA_URL_CHARS", exact_cap),
        ):
            result, _ = self.call_with_response(
                response(
                    200,
                    {"predictions": [{"bytesBase64Encoded": encoded_data, "mimeType": "image/png"}]},
                ),
                media.generate_image,
                prompt="at-cap image",
                provider="gemini",
                model="imagen-4",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], f"{prefix}{encoded_data}")
        self.assertEqual(len(result["url"]), exact_cap)

    def test_gemini_image_data_url_over_cap_fails_closed_without_leak(self):
        secret = "gemini-cap-secret-that-must-not-escape"
        encoded_data = "b3ZlcnNpemVkLWltYWdlLXByb3ZpZGVyLWJvZHk="
        prefix = "data:image/png;base64,"
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": secret}),
            patch.object(
                media,
                "_MAX_INLINE_MEDIA_DATA_URL_CHARS",
                len(prefix) + len(encoded_data) - 1,
            ),
        ):
            result, _ = self.call_with_response(
                response(
                    200,
                    {"predictions": [{"bytesBase64Encoded": encoded_data, "mimeType": "image/png"}]},
                ),
                media.generate_image,
                prompt="over-cap image",
                provider="gemini",
                model="imagen-4",
            )

        self.assertEqual(result["error"], "media payload exceeds 32 MiB cap")
        self.assertFalse(result["ok"])
        self.assertNotIn("url", result)
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(encoded_data, repr(result))
        self.assertLess(len(result["error"]), 64)

    def test_xai_image_routes_to_current_grok_model(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "xai-test-secret"}):
            result, call = self.call_with_response(
                response(200, {"data": [{"url": "https://images.invalid/generated.jpg"}]}),
                media.generate_image,
                prompt="a green circle",
                provider="xai",
            )

        self.assertEqual(call.args[0], f"{media._XAI_BASE_URL}/images/generations")
        self.assertEqual(call.kwargs["json"]["model"], "grok-imagine-image-quality")
        self.assertEqual(call.kwargs["json"]["resolution"], "1k")
        self.assertEqual(result["url"], "https://images.invalid/generated.jpg")
        self.assertEqual(result["model"], "grok-imagine-image-quality")

    def test_gemini_video_returns_operation_name(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-secret"}):
            result, call = self.call_with_response(
                response(200, {"name": "operations/video-123"}),
                media.generate_video,
                prompt="a slowly turning cube",
                provider="gemini",
                seconds=8,
                size="1920x1080",
            )

        self.assertEqual(
            call.args[0],
            f"{media._GEMINI_BASE_URL}/models/veo-3.1-generate-preview:predictLongRunning",
        )
        self.assertEqual(call.kwargs["json"]["parameters"]["durationSeconds"], "8")
        self.assertEqual(call.kwargs["json"]["parameters"]["resolution"], "1080p")
        self.assertEqual(result["job_id"], "operations/video-123")
        self.assertEqual(result["status"], "queued")

    def test_xai_video_returns_request_id(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "xai-test-secret"}):
            result, call = self.call_with_response(
                response(200, {"request_id": "request-456"}),
                media.generate_video,
                prompt="a paper plane gliding",
                provider="xai",
                seconds=6,
                size="1920x1080",
            )

        self.assertEqual(call.args[0], f"{media._XAI_BASE_URL}/videos/generations")
        self.assertEqual(call.kwargs["json"]["model"], "grok-imagine-video")
        self.assertEqual(call.kwargs["json"]["duration"], 6)
        self.assertEqual(call.kwargs["json"]["resolution"], "720p")
        self.assertEqual(result["job_id"], "request-456")
        self.assertEqual(result["model"], "grok-imagine-video")

    def test_gemini_audio_routes_to_interactions_and_returns_data_url(self):
        payload = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "text", "text": "structure"},
                        {"type": "audio", "mime_type": "audio/mpeg", "data": "YXVkaW8="},
                    ],
                }
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-secret"}):
            result, call = self.call_with_response(
                response(200, payload),
                media.generate_audio,
                prompt="a quiet piano loop",
                provider="gemini",
                model="lyria-3",
            )

        self.assertEqual(call.args[0], f"{media._GEMINI_BASE_URL}/interactions")
        self.assertEqual(call.kwargs["json"]["model"], "lyria-3-clip-preview")
        self.assertEqual(result["url"], "data:audio/mpeg;base64,YXVkaW8=")
        self.assertEqual(result["model"], "lyria-3-clip-preview")

    def test_gemini_audio_data_url_at_cap_passes(self):
        encoded_data = "YXVkaW8="
        prefix = "data:audio/mpeg;base64,"
        exact_cap = len(prefix) + len(encoded_data)
        payload = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "audio", "mime_type": "audio/mpeg", "data": encoded_data}],
                }
            ]
        }
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-secret"}),
            patch.object(media, "_MAX_INLINE_MEDIA_DATA_URL_CHARS", exact_cap),
        ):
            result, _ = self.call_with_response(
                response(200, payload),
                media.generate_audio,
                prompt="at-cap audio",
                provider="gemini",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], f"{prefix}{encoded_data}")
        self.assertEqual(len(result["url"]), exact_cap)

    def test_gemini_audio_data_url_over_cap_fails_closed_without_leak(self):
        secret = "gemini-audio-cap-secret-that-must-not-escape"
        encoded_data = "b3ZlcnNpemVkLWF1ZGlvLXByb3ZpZGVyLWJvZHk="
        prefix = "data:audio/mpeg;base64,"
        payload = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "audio", "mime_type": "audio/mpeg", "data": encoded_data}],
                }
            ]
        }
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": secret}),
            patch.object(
                media,
                "_MAX_INLINE_MEDIA_DATA_URL_CHARS",
                len(prefix) + len(encoded_data) - 1,
            ),
        ):
            result, _ = self.call_with_response(
                response(200, payload),
                media.generate_audio,
                prompt="over-cap audio",
                provider="gemini",
            )

        self.assertEqual(result["error"], "media payload exceeds 32 MiB cap")
        self.assertFalse(result["ok"])
        self.assertNotIn("url", result)
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(encoded_data, repr(result))
        self.assertLess(len(result["error"]), 64)


class ProviderErrorTests(unittest.TestCase):
    def call_with_response(self, result: httpx.Response, function, **kwargs):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.post.return_value = result
        with patch.object(media.httpx, "Client", return_value=client):
            return function(**kwargs)

    def test_gemini_json_error_is_redacted(self):
        secret = "gemini-secret-that-must-not-escape"
        with patch.dict(os.environ, {"GEMINI_API_KEY": secret}):
            result = self.call_with_response(
                response(
                    403,
                    {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": f"bad key {secret}"}},
                ),
                media.generate_image,
                prompt="test",
                provider="gemini",
            )

        self.assertEqual(result["error"], "HTTP 403 Forbidden")
        self.assertEqual(result["gemini_error"]["type"], "PERMISSION_DENIED")
        self.assertNotIn(secret, repr(result))
        self.assertIn("[redacted]", result["gemini_error"]["message_excerpt"])

    def test_xai_non_json_error_removes_authorization_line_and_secret(self):
        secret = "xai-secret-that-must-not-escape"
        with patch.dict(os.environ, {"XAI_API_KEY": secret}):
            result = self.call_with_response(
                response(429, text=f"Authorization: Bearer {secret}\nretry later {secret}"),
                media.generate_image,
                prompt="test",
                provider="xai",
            )

        self.assertEqual(result["error"], "HTTP 429 Too Many Requests")
        self.assertNotIn(secret, repr(result))
        self.assertEqual(result["xai_raw_excerpt"], "retry later [redacted]")

    def test_missing_keys_do_not_attempt_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(media.httpx, "Client") as client:
            gemini = media.generate_image("test", provider="gemini")
            xai = media.generate_video("test", provider="xai")
        client.assert_not_called()
        self.assertEqual(gemini["error"], "GEMINI_API_KEY missing")
        self.assertEqual(xai["error"], "XAI_API_KEY missing")

    def test_unsupported_providers_are_not_advertised_as_pending(self):
        result = media.generate_audio("test", provider="elevenlabs")
        self.assertEqual(result, {"ok": False, "error": "unsupported provider: elevenlabs"})
        self.assertNotIn("not yet wired", result["error"])


if __name__ == "__main__":
    unittest.main()
