# chrono-recon MCP

OSINT recon tools for Vibe Squad specialists (v1 keyless tools).

## Tools

### dns_enumerate
Enumerate DNS records for a domain.
- Parameters: `domain` (str), `record_types` (list, optional, default: ["A", "MX", "NS", "TXT", "CNAME"])
- Returns: dict with domain and records keyed by type

### whois_lookup
Look up WHOIS registration info for a domain or IP.
- Parameters: `domain_or_ip` (str)
- Returns: dict with registrar, creation/expiration dates, name servers, status, raw WHOIS text (first 2000 chars)

### crt_sh_certificates
Search TLS certificate transparency logs for subdomains.
- Parameters: `domain` (str)
- Returns: list of dicts with issuer, name, not_before (up to 100 results)

### wayback_snapshots
List Internet Archive Wayback Machine snapshots for a URL.
- Parameters: `url` (str), `from_date` (str, optional, format: YYYYMMDD), `to_date` (str, optional)
- Returns: list of dicts with snapshot metadata (up to 50 results)

### github_leaked_secrets
Search public GitHub code for leaked secrets or search terms.
- Parameters: `query` (str), `org` (str, optional)
- Returns: list of dicts with repo, path, url (up to 20 results)
- Requires: `GH_TOKEN` environment variable

## Installation

```bash
cd /path/to/claude-vibe-squad
uv sync --locked --python 3.13
source .venv/bin/activate
```

## Testing

Direct tool test:
```python
PYTHONPATH=plugins/chrono-recon python -c "from tools.dns import dns_enumerate; print(dns_enumerate('example.com'))"
```

MCP server test (via vibe-squad daemon):
```bash
curl -s -X POST http://127.0.0.1:9876/mcp/chrono-recon/dns_enumerate_tool \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'
```

## Dependencies

- mcp>=1.27.0 — MCP framework
- dnspython==2.7.* — DNS resolution
- python-whois==0.9.* — WHOIS lookups
- httpx>=0.27 — HTTP client (for crt.sh, wayback, github APIs)
