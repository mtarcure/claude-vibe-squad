"""Three observability gates must FAIL when the thing they guard is broken.

Each gate here previously reported success without proving anything:

  * ``mcp_probe.py`` called ``usable=true`` on a bare stdio handshake, so a server
    whose tool dispatch was dead audited as healthy.
  * ``mcp-audit.sh``'s ``env_status`` printed ``ok(1/5)`` -- the word "ok" beside
    a count that says four credentials are missing.
  * ``mcp-audit.sh`` declared credentials for ``chrono-research-arsenal`` that no
    tool reads, and omitted the one three of its six tools require.
  * ``vs-board-dashboard.py`` ignored the snapshot's exit status, so a crashed
    snapshot rendered the byte-identical "awaiting dispatch" hourglass as a
    genuinely quiet squad.

Every assertion below is on observed behaviour -- a process's stdout, a shell
function's output, a tool's return value. None reads the source of the thing it
tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock


ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "scripts" / "python" / "mcp_probe.py"
AUDIT = ROOT / "bin" / "mcp-audit.sh"
DASHBOARD = ROOT / "bin" / "vs-board-dashboard.py"
ARSENAL = ROOT / "plugins" / "chrono-research-arsenal" / "mcp_server.py"


# --------------------------------------------------------------------------
# A fake newline-delimited JSON-RPC stdio server, so probe behaviour can be
# driven into each failure mode without touching a real MCP.
# --------------------------------------------------------------------------
FAKE_SERVER = '''\
import json, os, sys

MODE = os.environ.get("FAKE_MCP_MODE", "healthy")
TOOLS = json.loads(os.environ.get("FAKE_MCP_TOOLS", '[{"name": "health"}]'))
RECORD = os.environ.get("FAKE_MCP_RECORD")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        continue
    method = msg.get("method")
    if RECORD:
        with open(RECORD, "a", encoding="utf-8") as fh:
            fh.write(str(method) + "\\n")
    mid = msg.get("id")
    if mid is None:
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"resources": []}})
    elif method == "tools/call":
        if MODE == "deaf-dispatch":
            continue
        name = (msg.get("params") or {}).get("name")
        if name in {t["name"] for t in TOOLS}:
            payload = os.environ.get("FAKE_MCP_CALL_PAYLOAD")
            result = {"content": [{"type": "text", "text": payload or "ok"}]}
            if payload:
                result["structuredContent"] = json.loads(payload)
            send({"jsonrpc": "2.0", "id": mid, "result": result})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32602, "message": "Unknown tool: %s" % name}})
'''


def _fields(line: str) -> dict[str, str]:
    """Parse the probe's `k=v k=v` output line into a dict."""
    return dict(part.split("=", 1) for part in line.split() if "=" in part)


class McpProbeUsabilityTest(unittest.TestCase):
    """`usable=true` must mean a tool call round-tripped, not that stdio opened."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = Path(self.tmp.name) / "fake_server.py"
        self.server.write_text(FAKE_SERVER, encoding="utf-8")

    def _probe(self, *opts: str, **env: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, **env}
        return subprocess.run(
            [sys.executable, str(PROBE), *opts, sys.executable, str(self.server)],
            capture_output=True, text=True, timeout=60, env=environment,
        )

    def test_handshake_without_working_dispatch_is_not_usable(self) -> None:
        """The gate's whole point: a server that answers initialize and
        tools/list but never answers tools/call is NOT usable.

        Catches: dropping the tools/call round-trip requirement, i.e. reverting
        to `usable=true` whenever an initialize response arrived.
        """
        result = self._probe(FAKE_MCP_MODE="deaf-dispatch")
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("usable"), "false", result.stdout)
        self.assertEqual(fields.get("tool_call"), "absent", result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_server_advertising_zero_tools_is_not_usable(self) -> None:
        """A server exposing no tools cannot serve any request, however
        cleanly it handshakes.

        Catches: removing the non-empty tool-list requirement.
        """
        result = self._probe(FAKE_MCP_TOOLS="[]")
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("usable"), "false", result.stdout)
        self.assertEqual(fields.get("tool_count"), "0", result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_healthy_server_is_usable(self) -> None:
        """The gate must still pass a server that works -- otherwise it is a
        different kind of useless.

        Catches: an over-strict gate that fails everything (which would make the
        first two tests pass vacuously).
        """
        result = self._probe()
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("usable"), "true", result.stdout)
        self.assertEqual(fields.get("tool_count"), "1", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_probe_actually_sends_a_tools_call(self) -> None:
        """Proof the probe invokes something rather than just claiming to.

        Catches: setting tool_call=ok from the tools/list response without ever
        putting a tools/call on the wire.
        """
        record = Path(self.tmp.name) / "methods.txt"
        self._probe(FAKE_MCP_RECORD=str(record))
        methods = record.read_text(encoding="utf-8").split()
        self.assertIn("tools/call", methods, methods)

    def test_default_dispatch_probe_uses_a_nonexistent_tool(self) -> None:
        """The default probe must not invoke a real tool -- MCP tools have side
        effects (they write to the KG, spend API credit). It proves the dispatch
        path by calling a name that cannot exist and requiring a clean rejection.

        Catches: changing the default to invoke the first advertised tool.
        """
        record = Path(self.tmp.name) / "methods.txt"
        result = self._probe(
            FAKE_MCP_RECORD=str(record), FAKE_MCP_TOOLS='[{"name": "record_finding"}]'
        )
        fields = _fields(result.stdout)
        # The fake server answers a known tool with a result and an unknown one
        # with an error; `error` therefore proves the real tool was NOT invoked.
        self.assertEqual(fields.get("tool_call"), "error", result.stdout)
        self.assertEqual(fields.get("usable"), "true", result.stdout)

    def test_expected_probe_rejection_is_not_counted_as_a_server_error(self) -> None:
        """The sentinel call always draws an error response; reporting it in
        `errors=` would put a permanent phantom error on every healthy server.

        Catches: counting every error message, including the probe's own.
        """
        result = self._probe()
        self.assertEqual(_fields(result.stdout).get("errors"), "0", result.stdout)

    def test_named_tool_that_fails_is_reported_unusable(self) -> None:
        """With --call NAME the operator is asking about that specific tool, so
        an error response means unusable (unlike the sentinel probe).

        Catches: treating any tools/call response as success regardless of --call.
        """
        result = self._probe("--call", "no_such_tool")
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("tool_call"), "error", result.stdout)
        self.assertEqual(fields.get("usable"), "false", result.stdout)

    def test_named_tool_that_succeeds_is_reported_usable(self) -> None:
        """Catches: --call being parsed but never actually invoked, or its
        success result being ignored."""
        result = self._probe("--call", "health")
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("tool_call"), "ok", result.stdout)
        self.assertEqual(fields.get("usable"), "true", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_a_tool_reporting_its_own_broken_state_is_not_usable(self) -> None:
        """The gate the sentinel cannot reach, and the reason --call exists.

        chrono-vault's `health` answers a tools/call perfectly while reporting
        `recall_ready: false` -- a dead read path behind a server that
        handshakes and dispatches. Measured 2026-08-08 (see _index_health in
        plugins/chrono-vault/mcp_server.py): health reported root_valid:true
        while every recall errored "index schema is stale". A JSON-RPC error
        never arrives, so error/isError alone cannot see this.

        Catches: judging a named call only by its transport status.
        """
        result = self._probe(
            "--call", "health",
            FAKE_MCP_CALL_PAYLOAD=json.dumps(
                {"root_valid": True, "index_dirty": False, "recall_ready": False}
            ),
        )
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("tool_call"), "unhealthy", result.stdout)
        self.assertEqual(fields.get("usable"), "false", result.stdout)
        self.assertIn("recall_ready", fields.get("tool_call_detail", ""), result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_a_false_flag_that_means_healthy_does_not_read_as_broken(self) -> None:
        """`index_dirty: false` is the HEALTHY value, so a blanket "any false
        boolean is broken" rule would invert it and fail every good vault --
        which would also make the test above pass for the wrong reason.

        Catches: gating on every false field instead of the named assertions.
        """
        result = self._probe(
            "--call", "health",
            FAKE_MCP_CALL_PAYLOAD=json.dumps(
                {"root_valid": True, "index_dirty": False, "recall_ready": True,
                 "fts5": True, "legacy_stores": []}
            ),
        )
        fields = _fields(result.stdout)
        self.assertEqual(fields.get("tool_call"), "ok", result.stdout)
        self.assertEqual(fields.get("usable"), "true", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_probe_returns_promptly_for_a_responsive_server(self) -> None:
        """A probe that always burns its full read window makes doctor and
        launch slow, which is why this gate was skipped in practice.

        Catches: removing the early exit once every response has arrived.
        """
        started = time.monotonic()
        self._probe()
        self.assertLess(time.monotonic() - started, 4.0)


class McpAuditEnvStatusTest(unittest.TestCase):
    """`ok` must mean every declared credential is present."""

    def _env_status(self, vars_arg: str, present: dict[str, str]) -> str:
        script = (
            f'MCP_AUDIT_LIB_ONLY=1 source "{AUDIT}"\n'
            'unset VS_GATE_A VS_GATE_B VS_GATE_C\n'
            + "".join(f'export {k}="{v}"\n' for k, v in present.items())
            + f'env_status "{vars_arg}"\n'
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=60,
            env={**os.environ, "MCP_AUDIT_LIB_ONLY": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_partial_coverage_does_not_render_as_ok(self) -> None:
        """One credential of three present is not "ok" in any English.

        Catches: reverting to `[[ $present -gt 0 ]] && echo ok(...)`.
        """
        status = self._env_status(
            "VS_GATE_A VS_GATE_B VS_GATE_C", {"VS_GATE_A": "set"}
        )
        self.assertEqual(status, "partial(1/3)")
        self.assertFalse(status.startswith("ok"), status)

    def test_full_coverage_renders_ok(self) -> None:
        """Catches: a fix that never says ok, making the partial test vacuous."""
        status = self._env_status(
            "VS_GATE_A VS_GATE_B VS_GATE_C",
            {"VS_GATE_A": "set", "VS_GATE_B": "set", "VS_GATE_C": "set"},
        )
        self.assertEqual(status, "ok(3/3)")

    def test_no_coverage_renders_missing(self) -> None:
        status = self._env_status("VS_GATE_A VS_GATE_B VS_GATE_C", {})
        self.assertEqual(status, "missing(0/3)")

    def test_no_declared_credentials_renders_na(self) -> None:
        self.assertEqual(self._env_status("", {}), "n/a")

    def test_a_declared_variable_set_to_empty_counts_as_missing(self) -> None:
        """An exported-but-empty key authenticates nothing.

        Catches: switching the presence test from -n to a bare `declared?` check.
        """
        status = self._env_status(
            "VS_GATE_A VS_GATE_B VS_GATE_C", {"VS_GATE_A": "set", "VS_GATE_B": ""}
        )
        self.assertEqual(status, "partial(1/3)")


class McpAuditDeclaredCredentialsTest(unittest.TestCase):
    """The audited credential list must match the credentials the server reads.

    The comparison is against observed tool behaviour: each tool is called with
    an empty environment and asked which credential it wanted. A credential no
    tool ever names is dead weight in the audit; one that a tool names but the
    audit omits is an outage the audit cannot see.
    """

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("_arsenal_probe", ARSENAL)
        assert spec and spec.loader
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    def _declared(self) -> set[str]:
        script = (
            f'MCP_AUDIT_LIB_ONLY=1 source "{AUDIT}"\n'
            'for entry in "${MCPS[@]}"; do\n'
            '  IFS="|" read -r name _tier _args vars <<<"$entry"\n'
            '  if [[ "$name" == "chrono-research-arsenal" ]]; then echo "$vars"; fi\n'
            'done\n'
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=60,
            env={**os.environ, "MCP_AUDIT_LIB_ONLY": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return set(result.stdout.split())

    def _credentials_tools_ask_for(self) -> set[str]:
        """Call every credential-gated tool with no credentials and collect the
        names they report missing. Each returns before any network call.

        `arxiv_search` is deliberately not called: it takes no credential and
        would reach the network, so it can contribute no name either way.
        """
        calls = (
            ("xai_search", lambda s: s.xai_search(query="probe")),
            ("perplexity_search", lambda s: s.perplexity_search(query="probe")),
            ("firecrawl_scrape", lambda s: s.firecrawl_scrape(url="https://example.com")),
            ("firecrawl_crawl", lambda s: s.firecrawl_crawl(url="https://example.com")),
            ("firecrawl_parse", lambda s: s.firecrawl_parse(
                filename="probe.pdf", content_base64="cHJvYmU=")),
        )
        wanted: set[str] = set()
        cleared = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_TOKEN"))}
        with unittest.mock.patch.dict(os.environ, cleared, clear=True):
            for name, call in calls:
                result = call(self.server)
                self.assertFalse(result.get("ok"), f"{name} succeeded without credentials")
                match = re.search(r"\b([A-Z][A-Z0-9_]*(?:_API_KEY|_TOKEN))\b", str(result))
                self.assertIsNotNone(match, f"{name} did not name a credential: {result}")
                wanted.add(match.group(1))
        return wanted

    def test_audit_declares_exactly_the_credentials_the_tools_ask_for(self) -> None:
        """Catches: restoring APIFY_TOKEN/BRAVE_API_KEY/SERPER_API_KEY (which no
        tool reads, so their absence can never explain an outage), or dropping
        FIRECRAWL_API_KEY (which three of the six tools require).
        """
        declared = self._declared()
        wanted = self._credentials_tools_ask_for()
        self.assertEqual(
            declared, wanted,
            f"audit declares {sorted(declared)}, tools ask for {sorted(wanted)}",
        )

    def test_firecrawl_credential_is_audited(self) -> None:
        """Named explicitly because its omission was the live blind spot: three
        of six tools return `FIRECRAWL_API_KEY missing` without it.
        """
        self.assertIn("FIRECRAWL_API_KEY", self._declared())


class DashboardSnapshotFailureTest(unittest.TestCase):
    """A dashboard that cannot read the board must not draw a calm idle board."""

    IDLE_MARKER = "awaiting dispatch"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "bin").mkdir(parents=True)
        (self.vault / "shared" / "cards").mkdir(parents=True)
        self.snapshot = self.vault / "bin" / "vs-board-snapshot.py"

    def _render(self, snapshot_body: str, **extra: str) -> str:
        self.snapshot.write_text(snapshot_body, encoding="utf-8")
        env = {
            **os.environ,
            "VAULT_ROOT": str(self.vault),
            "VS_DASH_WIDTH": "72",
            "VS_DASH_HEIGHT": "26",
            "VS_DASH_COLOR": "0",
            # Never touch the running squad's real /tmp state files.
            "VS_DASH_HITMAP": str(self.vault / "hitmap.tsv"),
            "VS_SWARM_STATUS": str(self.vault / "swarm.status"),
            "VS_DASH_HISTSTATE": str(self.vault / "hist.state"),
            **extra,
        }
        result = subprocess.run(
            [sys.executable, str(DASHBOARD)],
            capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_failed_snapshot_is_not_rendered_as_idle(self) -> None:
        """The exact bug: a snapshot that dies prints nothing on stdout, and no
        spawns renders as a serene hourglass. Failure must look like failure.

        Catches: dropping the returncode check in _snapshot_lines.
        """
        out = self._render(
            "import sys\n"
            "sys.stderr.write('board state unreadable\\n')\n"
            "sys.exit(3)\n"
        )
        self.assertNotIn(self.IDLE_MARKER, out)
        self.assertIn("SNAPSHOT FAILED", out)
        self.assertIn("3", out)

    def test_failed_snapshot_surfaces_the_stderr_reason(self) -> None:
        """An operator staring at a broken pane needs the reason in the pane.

        Catches: rendering a generic banner that discards the child's stderr.
        """
        out = self._render(
            "import sys\n"
            "sys.stderr.write('ValueError: corrupt dispatch descriptor\\n')\n"
            "sys.exit(1)\n"
        )
        self.assertIn("corrupt dispatch descriptor", out)

    def test_a_genuinely_idle_board_still_renders_idle(self) -> None:
        """Catches: a fix that reports failure unconditionally, which would make
        the failure tests pass while destroying the idle view.
        """
        out = self._render("import sys\nsys.exit(0)\n")
        self.assertIn(self.IDLE_MARKER, out)
        self.assertNotIn("SNAPSHOT FAILED", out)

    def test_snapshot_timeout_is_not_rendered_as_idle(self) -> None:
        """A hung snapshot is the other silent path to a false idle board.

        Catches: letting TimeoutExpired escape (a traceback loses the pane) or
        swallowing it into an empty spawn list.
        """
        out = self._render(
            "import time\ntime.sleep(30)\n", VS_DASH_SNAPSHOT_TIMEOUT="1"
        )
        self.assertNotIn(self.IDLE_MARKER, out)
        self.assertIn("SNAPSHOT FAILED", out)

    def test_failed_snapshot_does_not_report_idle_on_the_tmux_status_bar(self) -> None:
        """The status segment is the at-a-glance signal; it lied too.

        Catches: fixing only the pane body and leaving _write_swarm_status
        writing its "· idle ·" tag on a failed read.
        """
        self._render("import sys\nsys.exit(4)\n")
        status = (self.vault / "swarm.status").read_text(encoding="utf-8")
        self.assertNotIn("idle", status)

    def test_live_spawns_still_render_after_a_successful_snapshot(self) -> None:
        """Catches: a returncode check that also breaks the normal path."""
        out = self._render(
            "print('@SPAWN\\tt-1\\tcodex\\tscout\\t1000\\t999\\t/tmp/x.log\\tgpt-5')\n"
            "print('@SUMMARY\\thunt the regression')\n"
        )
        self.assertIn("hunt the regression", out)
        self.assertNotIn("SNAPSHOT FAILED", out)
        self.assertNotIn(self.IDLE_MARKER, out)


if __name__ == "__main__":
    unittest.main()


class AuthStatusReachesTheVerdictTests(unittest.TestCase):
    """`env_status` computing `partial(2/3)` is worth nothing if the verdict drops it.

    `bin/mcp-audit.sh` printed auth_ok into the per-server row and then counted
    issues/warnings from registered/reachable/usable only. `bin/doctor.sh:925-932`
    keys entirely on the `summary: issues=N warnings=N` line, so with
    FIRECRAWL_API_KEY unset the log read `auth_ok=partial(2/3)` while doctor
    printed "MCP usability audit passed" -- three of six arsenal tools dead.

    A signal computed and then discarded before the machine-readable verdict is
    the same defect as a gate that cannot fail.

    Catches: reverting `credential_shortfall` to a no-op, or counting only
    registered/reachable/usable again.
    """

    def _shortfall(self, status: str) -> int:
        """Run the real helper: does this auth_ok state count against the verdict?"""
        script = (
            f'MCP_AUDIT_LIB_ONLY=1 source "{AUDIT}"\n'
            f'if credential_shortfall "{status}"; then echo 1; else echo 0; fi\n'
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True,
            env={**os.environ, "MCP_AUDIT_LIB_ONLY": "1"},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return int(out.stdout.strip())

    def test_partial_credentials_count_against_the_verdict(self) -> None:
        self.assertEqual(self._shortfall("partial(2/3)"), 1)

    def test_missing_credentials_count_against_the_verdict(self) -> None:
        self.assertEqual(self._shortfall("missing(0/3)"), 1)

    def test_full_credentials_do_not(self) -> None:
        """Control: a healthy server must not be penalised."""
        self.assertEqual(self._shortfall("ok(3/3)"), 0)

    def test_not_applicable_does_not(self) -> None:
        """Control: a server declaring no credentials is not a shortfall."""
        self.assertEqual(self._shortfall("n/a"), 0)
