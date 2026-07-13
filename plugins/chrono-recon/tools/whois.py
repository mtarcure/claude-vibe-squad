import whois

def whois_lookup(domain_or_ip: str) -> dict:
    try:
        w = whois.whois(domain_or_ip)
        return {
            "registrar": w.registrar,
            "creation_date": str(w.creation_date),
            "expiration_date": str(w.expiration_date),
            "name_servers": w.name_servers,
            "status": w.status,
            "raw": str(w.text)[:2000] if w.text else None,
        }
    except Exception as e:
        return {"error": str(e)}
