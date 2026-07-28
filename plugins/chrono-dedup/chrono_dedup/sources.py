from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


USER_AGENT = "chrono-dedup/0.1 (+local prior-art check)"


class HttpTransport:
    def _open(self, request: Request, timeout: float) -> bytes:
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read(2_000_000)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"source unavailable: {type(exc).__name__}") from exc

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 8.0,
    ) -> dict[str, Any] | list[Any]:
        query = urlencode(
            [(key, value) for key, value in (params or {}).items() if value not in (None, "")]
        )
        request = Request(
            f"{url}?{query}" if query else url,
            headers={"User-Agent": USER_AGENT, **dict(headers or {})},
        )
        return json.loads(self._open(request, timeout).decode("utf-8"))

    def post_json(
        self,
        url: str,
        *,
        payload: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
        timeout: float = 8.0,
    ) -> dict[str, Any] | list[Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                **dict(headers or {}),
            },
            method="POST",
        )
        return json.loads(self._open(request, timeout).decode("utf-8"))

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float = 8.0,
    ) -> str:
        query = urlencode(
            [(key, value) for key, value in (params or {}).items() if value not in (None, "")]
        )
        request = Request(
            f"{url}?{query}" if query else url,
            headers={"User-Agent": USER_AGENT},
        )
        return self._open(request, timeout).decode("utf-8", errors="replace")


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        title = " ".join("".join(self._text).split())
        if title:
            self.links.append(
                {"title": title, "url": urljoin(self.base_url, self._href)}
            )
        self._href = None
        self._text = []


def _terms_match(record: Mapping[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=True).casefold()
    return any(term.casefold() in haystack for term in terms)


def _target_label(target: str | Mapping[str, Any]) -> str:
    if isinstance(target, str):
        return target
    return str(target.get("name") or target.get("id") or target.get("target") or "")


class SearchPageSource:
    def __init__(
        self,
        name: str,
        url: str,
        query_parameter: str,
        *,
        link_pattern: str,
        transport: HttpTransport | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self.query_parameter = query_parameter
        self.link_pattern = re.compile(link_pattern)
        self.transport = transport or HttpTransport()

    def search(
        self,
        target: str | Mapping[str, Any],
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        html = self.transport.get_text(
            self.url,
            params={
                self.query_parameter: " ".join(
                    value
                    for value in (_target_label(target), query["phrase"])
                    if value
                )
            },
        )
        parser = _LinkParser(self.url)
        parser.feed(html)
        records = [
            {
                "id": link["url"].rstrip("/").rsplit("/", 1)[-1],
                **link,
                "summary": link["title"],
            }
            for link in parser.links
            if self.link_pattern.search(link["url"])
        ]
        return [record for record in records if _terms_match(record, query["terms"])]


class SoloditSource:
    name = "solodit"
    api_url = "https://solodit.cyfrin.io/api/v1/solodit/findings"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport()

    @staticmethod
    def _tag_titles(finding: Mapping[str, Any]) -> list[str]:
        titles: list[str] = []
        for tag_score in finding.get("issues_issuetagscore") or []:
            if not isinstance(tag_score, Mapping):
                continue
            tag = tag_score.get("tags_tag")
            title = tag.get("title") if isinstance(tag, Mapping) else None
            if isinstance(title, str) and title:
                titles.append(title)
        return titles

    def search(
        self,
        target: str | Mapping[str, Any],
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        api_key = os.environ.get("SOLODIT_API_KEY")
        if not api_key:
            raise RuntimeError("Solodit credential is unavailable")
        keywords = " ".join(
            str(value)
            for value in (
                _target_label(target),
                query.get("phrase"),
            )
            if value
        )
        payload = self.transport.post_json(
            self.api_url,
            payload={
                "page": 1,
                "pageSize": 30,
                "filters": {"keywords": keywords},
            },
            headers={"X-Cyfrin-API-Key": api_key},
        )
        if not isinstance(payload, Mapping):
            return []
        findings = payload.get("findings", [])
        if not isinstance(findings, list):
            return []
        records: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            tags = self._tag_titles(finding)
            record = {
                "id": finding.get("id") or finding.get("slug"),
                "title": finding.get("title"),
                "summary": finding.get("summary") or finding.get("content"),
                "url": finding.get("source_link"),
                "weakness": tags,
                "keywords": [
                    value
                    for value in (
                        finding.get("protocol_name"),
                        finding.get("firm_name"),
                        *tags,
                    )
                    if value
                ],
            }
            if _terms_match(record, query["terms"]):
                records.append(record)
        return records


class GitHubAdvisoriesSource:
    name = "github_security_advisories"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport()

    def search(self, target: Any, item: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
        component = query.get("component")
        version = query.get("version")
        affects = f"{component}@{version}" if component and version else component
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = self.transport.get_json(
            "https://api.github.com/advisories",
            params={"affects": affects, "per_page": 30},
            headers=headers,
        )
        if not isinstance(payload, list):
            return []
        records = []
        for advisory in payload:
            if not isinstance(advisory, Mapping):
                continue
            vulnerabilities = advisory.get("vulnerabilities") or []
            first = vulnerabilities[0] if vulnerabilities and isinstance(vulnerabilities[0], Mapping) else {}
            package = first.get("package") if isinstance(first, Mapping) else {}
            records.append(
                {
                    "id": advisory.get("ghsa_id") or advisory.get("cve_id"),
                    "title": advisory.get("summary"),
                    "summary": advisory.get("description"),
                    "url": advisory.get("html_url"),
                    "component": package.get("name") if isinstance(package, Mapping) else component,
                    "version": version,
                    "cwe": advisory.get("cwes"),
                }
            )
        return [record for record in records if _terms_match(record, query["terms"])]


class CveSource:
    name = "cve"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport()

    @staticmethod
    def _affected(cve: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        components: set[str] = set()
        versions: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                criteria = value.get("criteria")
                if isinstance(criteria, str) and criteria.startswith("cpe:2.3:"):
                    parts = criteria.split(":")
                    if len(parts) > 5 and parts[4] not in {"", "*", "-"}:
                        components.add(parts[4].replace("_", "-"))
                    if len(parts) > 5 and parts[5] not in {"", "*", "-"}:
                        versions.add(parts[5])
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(cve.get("configurations"))
        return sorted(components), sorted(versions)

    def search(self, target: Any, item: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
        payload = self.transport.get_json(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params={"keywordSearch": query["phrase"], "resultsPerPage": 30},
        )
        if not isinstance(payload, Mapping):
            return []
        records = []
        for wrapper in payload.get("vulnerabilities", []):
            cve = wrapper.get("cve", {}) if isinstance(wrapper, Mapping) else {}
            descriptions = cve.get("descriptions", []) if isinstance(cve, Mapping) else []
            description = next(
                (
                    entry.get("value")
                    for entry in descriptions
                    if isinstance(entry, Mapping) and entry.get("lang") == "en"
                ),
                "",
            )
            cve_id = cve.get("id") if isinstance(cve, Mapping) else None
            components, versions = self._affected(cve)
            records.append(
                {
                    "id": cve_id,
                    "title": description or cve_id,
                    "summary": description,
                    "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}" if cve_id else None,
                    "component": components,
                    "version": versions,
                    "cwe": cve.get("weaknesses") if isinstance(cve, Mapping) else None,
                }
            )
        return records


class OsvSource:
    name = "osv"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport()

    def search(self, target: Any, item: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
        component = query.get("component")
        if not component:
            return []
        package: dict[str, Any] = {"name": component}
        ecosystem = item.get("ecosystem")
        if ecosystem:
            package["ecosystem"] = ecosystem
        request: dict[str, Any] = {"package": package}
        if query.get("version"):
            request["version"] = query["version"]
        payload = self.transport.post_json("https://api.osv.dev/v1/query", payload=request)
        if not isinstance(payload, Mapping):
            return []
        return [
            {
                "id": vuln.get("id"),
                "title": vuln.get("summary") or vuln.get("id"),
                "summary": vuln.get("details"),
                "url": f"https://osv.dev/vulnerability/{vuln.get('id')}",
                "component": component,
                "version": query.get("version"),
                "aliases": vuln.get("aliases"),
            }
            for vuln in payload.get("vulns", [])
            if isinstance(vuln, Mapping)
        ]


class TargetProgramHistorySource:
    name = "target_program_history"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport()

    def search(
        self,
        target: str | Mapping[str, Any],
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        url = None
        if isinstance(target, Mapping):
            url = target.get("disclosed_reports_url") or target.get("program_history_url")
        url = url or item.get("disclosed_reports_url") or item.get("program_history_url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise RuntimeError("target program has no disclosed-report history URL")
        html = self.transport.get_text(url)
        parser = _LinkParser(url)
        parser.feed(html)
        return [
            {
                "id": link["url"].rstrip("/").rsplit("/", 1)[-1],
                **link,
                "summary": link["title"],
            }
            for link in parser.links
            if _terms_match(link, query["terms"])
        ]


class ChronoVaultSource:
    name = "chrono_vault"

    def __init__(
        self,
        recall_fn: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.recall_fn = recall_fn

    def _local_recall(self, query: str, target: str) -> Mapping[str, Any]:
        vault_plugin = Path(__file__).resolve().parents[2] / "chrono-vault"
        script = f"""
import json
import sys

sys.path.insert(0, {str(vault_plugin)!r})
from lifecycle import get_note
from recall import recall

payload = json.load(sys.stdin)
result = recall(
    query=payload["query"],
    filters={{"target": payload["target"]}},
    limit=20,
)
for recalled in result.get("results", []):
    try:
        recalled["note"] = get_note(recalled["id"])
    except Exception:
        pass
print(json.dumps(result))
"""
        process = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps({"query": query, "target": target}),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError("chrono-vault recall unavailable")
        payload = json.loads(process.stdout)
        if not isinstance(payload, Mapping):
            raise RuntimeError("chrono-vault returned an invalid response")
        return payload

    def search(
        self,
        target: str | Mapping[str, Any],
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        target_name = (
            target
            if isinstance(target, str)
            else target.get("name") or target.get("id") or target.get("target")
        )
        recall_query = " ".join(
            str(value)
            for value in (
                target_name,
                query.get("component"),
                query.get("version"),
                query.get("phrase"),
            )
            if value
        )[:512]
        recall = self.recall_fn or self._local_recall
        payload = recall(recall_query, str(target_name))
        records = []
        for result in payload.get("results", []):
            if not isinstance(result, Mapping):
                continue
            snippet = str(result.get("snippet") or "")
            note = result.get("note") if isinstance(result.get("note"), Mapping) else {}
            full_text = " ".join(
                str(value)
                for value in (
                    note.get("title"),
                    note.get("body"),
                    note.get("keywords"),
                    snippet,
                )
                if value
            )
            key_match = re.search(r"(?:finding|chain):v1:[a-f0-9]{64}", full_text)
            records.append(
                {
                    "id": result.get("id"),
                    "title": note.get("title") or result.get("title") or result.get("id"),
                    "summary": note.get("body"),
                    "snippet": snippet,
                    "url": result.get("note_link"),
                    "target": note.get("target") or target_name,
                    "component": note.get("component"),
                    "weakness": note.get("attack_class"),
                    "keywords": note.get("keywords"),
                    "dedup_key": key_match.group(0) if key_match else None,
                }
            )
        return records


def default_sources(*, transport: HttpTransport | None = None) -> list[Any]:
    shared_transport = transport or HttpTransport()
    return [
        SearchPageSource(
            "hackerone_hacktivity",
            "https://hackerone.com/hacktivity/overview",
            "querystring",
            link_pattern=r"hackerone\.com/reports/\d+",
            transport=shared_transport,
        ),
        SearchPageSource(
            "immunefi",
            "https://immunefi.com/explore/",
            "search",
            link_pattern=r"immunefi\.com/(?:bug-bounty|blog)/",
            transport=shared_transport,
        ),
        SoloditSource(shared_transport),
        GitHubAdvisoriesSource(shared_transport),
        CveSource(shared_transport),
        OsvSource(shared_transport),
        TargetProgramHistorySource(shared_transport),
        ChronoVaultSource(),
    ]
