import httpx

def crt_sh_certificates(domain: str) -> list[dict]:
    url = f"https://crt.sh/?q={domain}&output=json"
    try:
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        raw = resp.json()
        return [{"issuer": r.get("issuer_name"), "name": r.get("name_value"), "not_before": r.get("not_before")} for r in raw[:100]]
    except Exception as e:
        return [{"error": str(e)}]
