from mcp.server.fastmcp import FastMCP
from tools.dns import dns_enumerate
from tools.whois import whois_lookup
from tools.crt_sh import crt_sh_certificates
from tools.wayback import wayback_snapshots
from tools.github_secrets import github_leaked_secrets

mcp = FastMCP("chrono-recon")

@mcp.tool()
def dns_enumerate_tool(domain: str, record_types: list = None) -> dict:
    """Enumerate DNS records for a domain."""
    return dns_enumerate(domain, record_types)

@mcp.tool()
def whois_lookup_tool(domain_or_ip: str) -> dict:
    """Look up WHOIS registration info."""
    return whois_lookup(domain_or_ip)

@mcp.tool()
def crt_sh_certificates_tool(domain: str) -> list:
    """Search TLS certificate transparency logs for subdomains."""
    return crt_sh_certificates(domain)

@mcp.tool()
def wayback_snapshots_tool(url: str, from_date: str = None, to_date: str = None) -> list:
    """List Internet Archive Wayback Machine snapshots for a URL."""
    return wayback_snapshots(url, from_date, to_date)

@mcp.tool()
def github_leaked_secrets_tool(query: str, org: str = None) -> list:
    """Search public GitHub code for leaked secrets or terms."""
    return github_leaked_secrets(query, org)

if __name__ == "__main__":
    mcp.run()
