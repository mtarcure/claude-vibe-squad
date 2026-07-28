import httpx


def _redacted_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: status={exc.response.status_code}"
    if isinstance(exc, httpx.RequestError) and exc.__cause__ is not None:
        return f"{type(exc).__name__}: reason={type(exc.__cause__).__name__}"
    return type(exc).__name__


def crt_sh_certificates(domain: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://crt.sh/",
            params={"q": domain, "output": "json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "issuer": r.get("issuer_name"),
                "name": r.get("name_value"),
                "not_before": r.get("not_before"),
            }
            for r in raw[:100]
        ]
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        return [{"error": _redacted_error(exc)}]
