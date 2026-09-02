from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "python"))

from lane_capability_enforcement import RESEARCH_API_KEY_NAMES  # noqa: E402

ARSENAL_SERVER = ROOT / "plugins" / "chrono-research-arsenal" / "mcp_server.py"
ARSENAL_MANIFEST = (
    ROOT / "plugins" / "chrono-research-arsenal" / ".claude-plugin" / "plugin.json"
)
BOOTSTRAP = ROOT / "scripts" / "bootstrap-mcps.sh"
MCP_AUDIT = ROOT / "bin" / "mcp-audit.sh"

# Rows in the two shell MCP-registry arrays. The env names are always the LAST
# `|`-delimited field, but the field COUNT differs by file -- `bootstrap-mcps.sh`
# writes `name|command|ENVS` and `mcp-audit.sh` writes `name|tier|command|ENVS`
# -- so the shape is matched loosely and the env field is validated instead.
ROW_RE = re.compile(
    r'^\s*"(?P<name>[a-z-]+)\|(?P<rest>[^"]*)"\s*$',
    re.MULTILINE,
)
ENV_FIELD_RE = re.compile(r"^[A-Z][A-Z0-9_]*( [A-Z][A-Z0-9_]*)*$")


def shell_registry_env(path: Path, server: str) -> frozenset[str]:
    """Return the env names a shell MCP-registry array declares for ``server``."""
    for row in ROW_RE.finditer(path.read_text()):
        if row.group("name") != server:
            continue
        env = row.group("rest").rsplit("|", 1)[-1]
        if not ENV_FIELD_RE.match(env):
            raise AssertionError(
                f"{path.name}: {server} row has no env-name field; last field "
                f"parsed as {env!r}"
            )
        return frozenset(env.split())
    raise AssertionError(f"{path.name} declares no row for {server}")


class ResearchArsenalCredentialSingleSource(unittest.TestCase):
    """`RESEARCH_API_KEY_NAMES` owns this fact; three other homes copy it.

    Hard Rule 10 permits the copies only while a validator enforces the
    identity. It is not enforceable by derivation: `bin/doctor.sh` reads the
    bootstrap array as SOURCE TEXT (a runtime lookup would leave it with
    nothing to parse), `plugin.json` is static JSON that Claude Code loads
    without an interpreter, and `bin/mcp-audit.sh` must state the names it
    audits for a reader. So the copies stay literal and this pins them.

    The drift this catches is silent by construction: a name added here but
    not there is not a crash, it is a tool that returns "API key missing" at
    call time, or a doctor warning about a key nothing reads. Both were live
    before 2026-09-01 -- `bootstrap-mcps.sh` forwarded APIFY_TOKEN,
    BRAVE_API_KEY and SERPER_API_KEY, which no reader in the server has ever
    looked up, while doctor demanded all three from the operator's store.
    """

    def test_owning_tuple_is_exactly_what_the_server_reads(self) -> None:
        """The owner is not merely self-consistent -- it matches the code."""
        tree = ast.parse(ARSENAL_SERVER.read_text())
        read = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.endswith(("_API_KEY", "_TOKEN"))
        }
        self.assertEqual(read, set(RESEARCH_API_KEY_NAMES))

    def test_bootstrap_registry_matches_the_owner(self) -> None:
        self.assertEqual(
            shell_registry_env(BOOTSTRAP, "chrono-research-arsenal"),
            frozenset(RESEARCH_API_KEY_NAMES),
        )

    def test_mcp_audit_registry_matches_the_owner(self) -> None:
        self.assertEqual(
            shell_registry_env(MCP_AUDIT, "chrono-research-arsenal"),
            frozenset(RESEARCH_API_KEY_NAMES),
        )

    def test_plugin_manifest_forwards_exactly_the_owner(self) -> None:
        manifest = json.loads(ARSENAL_MANIFEST.read_text())
        env = manifest["mcpServers"]["chrono-research-arsenal"]["env"]
        self.assertEqual(set(env), set(RESEARCH_API_KEY_NAMES))
        # A forwarding declaration that does not pass the value through is a
        # third failure mode: present in the manifest, empty at call time.
        for name in RESEARCH_API_KEY_NAMES:
            self.assertEqual(env[name], "${" + name + "}")


if __name__ == "__main__":
    unittest.main()


class ObsidianCredentialRowAgreementTests(unittest.TestCase):
    """Every MCP row's credential set must agree between the registrar and the auditor.

    Found drifted: `scripts/bootstrap-mcps.sh` registers chrono-obsidian with
    CHRONO_VAULT_ROOT, and `bin/mcp-audit.sh` audited it WITHOUT that name. The
    omission is the one bootstrap-mcps.sh carries an eight-line comment about:
    without CHRONO_VAULT_ROOT the server exits before the MCP handshake, and
    every client reports only "Connection closed". A shell export cannot cover
    it, because clients pass the env dict INSTEAD OF the inherited environment.

    So `env_status` counted 2 present of 2 declared and printed `auth_ok=ok(2/2)`
    with `summary: issues=0` -- and doctor keys on that summary line. The audit
    that exists to catch this failure was declared blind to it, and the operator
    already has a standing note that an unset CHRONO_VAULT_ROOT kills recall
    silently and cannot self-detect.

    The pre-existing tests here pinned only the chrono-research-arsenal row, so
    the drift sat one row away from coverage.

    Catches: any row's credential set diverging between the two files, in either
    direction -- not just this one row, and not just this one name.
    """

    def test_every_shared_row_declares_the_same_credentials(self) -> None:
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        audit = MCP_AUDIT.read_text(encoding="utf-8")

        def rows(text: str, env_field: int) -> dict[str, set[str]]:
            found: dict[str, set[str]] = {}
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith('"') or "|" not in line:
                    continue
                parts = line.strip('"').split("|")
                if len(parts) <= env_field:
                    continue
                name = parts[0]
                if not name.startswith("chrono-"):
                    continue
                found[name] = {
                    tok for tok in parts[env_field].strip('"').split()
                    if tok.isupper() or "_" in tok
                }
            return found

        registered = rows(bootstrap, 2)   # name|command|env
        audited = rows(audit, 3)          # name|tier|command|env
        shared = set(registered) & set(audited)
        self.assertTrue(shared, "no chrono-* rows found in both files to compare")
        for name in sorted(shared):
            self.assertEqual(
                registered[name], audited[name],
                f"{name}: bootstrap-mcps.sh registers "
                f"{sorted(registered[name])} but mcp-audit.sh audits "
                f"{sorted(audited[name])}. A name the auditor does not declare "
                "is a name env_status cannot count, so a missing credential "
                "renders as a clean ok(N/N).",
            )
