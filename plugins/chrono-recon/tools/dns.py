import dns.resolver
from typing import Optional

def dns_enumerate(domain: str, record_types: Optional[list[str]] = None) -> dict:
    types = record_types or ["A", "MX", "NS", "TXT", "CNAME"]
    results = {}
    for rtype in types:
        try:
            answers = dns.resolver.resolve(domain, rtype)
            results[rtype] = [str(a) for a in answers]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException) as e:
            results[rtype] = {"error": type(e).__name__}
    return {"domain": domain, "records": results}
