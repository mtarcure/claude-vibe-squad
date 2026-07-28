#!/usr/bin/env python3
"""Invariant tests for V2 Task 2.7 — bin/watch-lane.sh card dashboard enhancement.

bin/watch-lane.sh ends in an infinite render loop, so it is not directly
sourceable for testing. WATCH_LANE_TEST_MODE=1 (checked once, at the very
end of the script) skips that loop while still defining every function —
these tests source the real script under that guard and invoke its real
bash functions via subprocess, asserting on real stdout. This tests the
actual shell logic, not a Python reimplementation of it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "bin" / "watch-lane.sh"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _visible_width(s: str) -> int:
    """Independent ground truth (Unicode East Asian Width), NOT dwidth()
    itself -- asserting a fix to dwidth() by calling dwidth() would be
    circular. Matches the exact metric codex's review used to prove the
    original bug ("Unicode East Asian display width")."""

    stripped = _ANSI_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in stripped)


def run_function(call: str, *, env: dict[str, str] | None = None) -> str:
    """Source watch-lane.sh in test mode and print the result of one call."""

    full_env = dict(os.environ)
    full_env["VAULT_ROOT"] = str(ROOT)
    full_env["WATCH_LANE_TEST_MODE"] = "1"
    if env:
        full_env.update(env)
    completed = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}" all >/dev/null 2>&1; {call}'],
        capture_output=True,
        text=True,
        timeout=10,
        env=full_env,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{call} failed: rc={completed.returncode} stderr={completed.stderr}")
    return completed.stdout


class BadgeTests(unittest.TestCase):
    def test_badge_model_matches_the_design_briefs_legend(self) -> None:
        self.assertEqual(run_function("badge_model claude"), "🟦")
        self.assertEqual(run_function("badge_model gpt-codex"), "🟩")
        self.assertEqual(run_function("badge_model gemini"), "🔶")
        self.assertEqual(run_function("badge_model kimi"), "🟣")

    def test_badge_department_matches_the_design_briefs_legend(self) -> None:
        # coding/content/sysmgmt use single-codepoint substitutes for the
        # design brief's literal ⚙️/✍️/🖥️ (each a base+variation-selector
        # PAIR that would break dwidth()/fit()'s single-codepoint glyph
        # matching and misalign card borders — verified via direct codepoint
        # inspection before choosing 🔧/📝/💻 as same-meaning replacements).
        self.assertEqual(run_function("badge_department security"), "🔒")
        self.assertEqual(run_function("badge_department research"), "🔬")
        self.assertEqual(run_function("badge_department coding"), "🔧")
        self.assertEqual(run_function("badge_department content"), "📝")
        self.assertEqual(run_function("badge_department sysmgmt"), "💻")
        self.assertEqual(run_function("badge_department shared"), "🧭")

    def test_card_status_badge_priority_review_beats_blocked_beats_running(self) -> None:
        # review-required must never hide, per the design brief — it wins
        # even when the lane also shows blocked or running underneath.
        self.assertEqual(run_function("card_status_badge claude blocked 1 0"), "👀")
        self.assertEqual(run_function("card_status_badge claude running 1 0"), "👀")
        self.assertEqual(run_function("card_status_badge claude blocked 0 0"), "⛔")
        self.assertEqual(run_function("card_status_badge claude running 0 0"), "⚡")
        self.assertEqual(run_function("card_status_badge claude queued 0 0"), "⏳")
        self.assertEqual(run_function("card_status_badge claude idle 0 0"), "✅")

    def test_a_fresh_settle_is_visibly_distinct_from_ordinary_idle(self) -> None:
        # REJECT defect 2: card_status_badge() ignored its 4th argument, so
        # idle-with-flag-0 and idle-with-flag-1 rendered byte-identical --
        # the settle notification had no card-visible effect at all. The
        # settled-flash MUST differ from plain idle, must still contain the
        # ✅ glyph (visually recognizable as "settled", not a new symbol),
        # and must keep the exact same display width (dwidth()/fit() never
        # measure this string; the header's pad math treats it as an opaque
        # fixed +2-column value).
        idle = run_function("card_status_badge claude idle 0 0")
        settled_flash = run_function("card_status_badge claude idle 0 1")
        self.assertNotEqual(idle, settled_flash)
        self.assertIn("✅", idle)
        self.assertIn("✅", settled_flash)
        self.assertEqual(_visible_width(idle), 2)
        self.assertEqual(_visible_width(settled_flash), 2)

    def test_settle_flash_never_outranks_review_blocked_running_or_queued(self) -> None:
        # Priority per the design brief: review > blocked > running >
        # queued > settled-flash > idle. A fresh settle must not hide a
        # higher-priority state underneath it.
        self.assertEqual(run_function("card_status_badge claude blocked 0 1"), "⛔")
        self.assertEqual(run_function("card_status_badge claude running 0 1"), "⚡")
        self.assertEqual(run_function("card_status_badge claude queued 0 1"), "⏳")
        self.assertEqual(run_function("card_status_badge claude blocked 1 1"), "👀")


class SpecialistDepartmentTests(unittest.TestCase):
    def test_department_lookup_matches_the_canonical_frontmatter(self) -> None:
        self.assertEqual(run_function("specialist_department code-reviewer").strip(), "coding")
        self.assertEqual(run_function("specialist_department scout").strip(), "security")
        self.assertEqual(run_function("specialist_department skeptic").strip(), "shared")

    def test_unknown_specialist_returns_empty(self) -> None:
        self.assertEqual(run_function("specialist_department not-a-real-specialist").strip(), "")


class CrewNameTests(unittest.TestCase):
    def test_crew_names_match_the_operator_approved_mapping(self) -> None:
        # Spot-check against _state/v2-finalization-2026-07-21-crew/crew-mapping.md
        # verbatim -- these are not invented here, they're carried through.
        self.assertEqual(run_function("specialist_crew_name exploit-developer").strip(), "Sukuna")
        self.assertEqual(run_function("specialist_crew_name reverse-engineer").strip(), "Sasuke")
        self.assertEqual(run_function("specialist_crew_name detection-engineer").strip(), "Hawkeye")
        self.assertEqual(run_function("specialist_crew_name incident-responder").strip(), "Levi")
        self.assertEqual(run_function("specialist_crew_name scout").strip(), "Killua")

    def test_every_canonical_specialist_has_a_crew_name(self) -> None:
        specialists = sorted(
            p.stem
            for p in (ROOT / "departments").glob("*/specialists/*.md")
        ) + sorted(p.stem for p in (ROOT / "shared" / "specialists").glob("*.md"))
        self.assertEqual(len(specialists), 73, specialists)
        missing = []
        for spec in specialists:
            name = run_function(f"specialist_crew_name {spec}").strip()
            if not name:
                missing.append(spec)
        self.assertEqual(missing, [], f"{len(missing)} specialists have no crew name: {missing}")


class ReviewRequiredTests(unittest.TestCase):
    def test_review_required_count_is_a_non_negative_integer_for_every_lane(self) -> None:
        for lane in ("gpt-codex", "claude", "gemini", "kimi"):
            out = run_function(f"review_required_count {lane}").strip()
            self.assertRegex(out, r"^\d+$", f"{lane}: {out!r}")

    def _fixture_registry(self, directory: Path, records: dict) -> Path:
        # Deliberately NOT under a fake VAULT_ROOT: watch-lane.sh sources
        # ${VAULT_ROOT}/shared/lead-windows.sh at load time (for
        # SOURCE_NAMESPACES etc), so a wholesale-fake VAULT_ROOT breaks
        # sourcing entirely. ACTIVE_TASKS_REGISTRY is a targeted,
        # backward-compatible override (defaults to the real
        # ${VAULT_ROOT}/_state/active-tasks.json when unset) that isolates
        # exactly the one file this test needs to control.
        path = directory / "active-tasks.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        return path

    def test_review_required_count_reflects_the_live_registry_status(self) -> None:
        # REJECT defect 1: the old implementation counted any outbox response
        # whose immutable frontmatter said needs_review and whose file mtime
        # was under 24h -- never the live registry. This drives it straight
        # from status=="review-required" per lane, with no file/age involved
        # at all.
        with tempfile.TemporaryDirectory() as directory:
            registry = self._fixture_registry(Path(directory), {
                "TASK-A": {"to_model": "claude", "status": "review-required"},
                "TASK-B": {"to_model": "claude", "status": "complete"},
                "TASK-C": {"to_model": "gpt-codex", "status": "review-required"},
            })
            env = {"ACTIVE_TASKS_REGISTRY": str(registry)}
            self.assertEqual(run_function("review_required_count claude", env=env).strip(), "1")
            self.assertEqual(run_function("review_required_count gpt-codex", env=env).strip(), "1")
            self.assertEqual(run_function("review_required_count gemini", env=env).strip(), "0")

    def test_review_required_count_is_zero_once_the_registry_shows_the_review_settled(self) -> None:
        # Codex's exact complaint: "the original response status is never
        # rewritten" -- an outbox-mtime heuristic can NEVER observe a review
        # actually settling. The live registry status IS rewritten by the
        # real settle mechanism (registry_reconciler.py), so a settled
        # review must read as zero regardless of how old the file is.
        with tempfile.TemporaryDirectory() as directory:
            registry = self._fixture_registry(Path(directory), {
                "TASK-A": {
                    "to_model": "claude", "status": "complete",
                    "review_settled_at": "2020-01-01T00:00:00Z",
                },
            })
            env = {"ACTIVE_TASKS_REGISTRY": str(registry)}
            self.assertEqual(run_function("review_required_count claude", env=env).strip(), "0")

    def test_refresh_review_snapshot_review_column_also_reflects_the_registry(self) -> None:
        # The production path (_refresh_review_snapshot -> REVIEW_SNAP ->
        # _lane_review_count), not just the standalone helper.
        with tempfile.TemporaryDirectory() as directory:
            registry = self._fixture_registry(Path(directory), {
                "TASK-A": {"to_model": "claude", "status": "review-required"},
            })
            out = run_function("_refresh_review_snapshot", env={"ACTIVE_TASKS_REGISTRY": str(registry)})
            claude_row = next(line for line in out.splitlines() if line.startswith("claude\t"))
            self.assertEqual(claude_row.split("\t")[1], "1")


class WidthAccountingRegressionTests(unittest.TestCase):
    """REJECT defect 3: a valid research avatar breaks card width."""

    def test_dwidth_correctly_counts_the_research_department_motif_glyph(self) -> None:
        # Codex: dwidth('[📜]')=3 although its real East Asian display width
        # is 4 -- 📜 (U+1F4DC) is EAW=W, verified independently via
        # unicodedata, and was simply missing from the hand-maintained list.
        self.assertEqual(run_function("dwidth '[📜]'").strip(), "4")

    def test_the_unknown_department_fallback_glyph_is_also_counted_correctly(self) -> None:
        # A second genuinely-wide glyph (❔, U+2754, EAW=W) found in the same
        # audit, missing from the same list for the same reason.
        self.assertEqual(run_function("dwidth '(?)'").strip(), "3")
        self.assertEqual(run_function("dwidth '❔'").strip(), "2")

    def test_a_research_department_specialist_avatar_fits_the_card_border_at_width_60(self) -> None:
        # Codex's exact repro: fmt_member 60 ... produced a 61-column row.
        # "research" has no bespoke crew avatar, so it falls through to the
        # department motif [📜] -- exactly the offending fallback path.
        label = run_function(
            'printf "%s" "$(badge_department research) $(specialist_avatar_glyph research 0) '
            '$(specialist_crew_name research) . research"'
        ).strip()
        row = run_function('fmt_member 60 "38;5;118" "o" "$LABEL" "00:00"', env={"LABEL": label})
        self.assertEqual(_visible_width(row), 60, repr(row))


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS-only: watch-lane temp checks use BSD stat -f",
)
class TempFileSafetyRegressionTests(unittest.TestCase):
    """REJECT defect 4: predictable shared /tmp paths allow out-of-target
    overwrite."""

    def test_private_cache_dir_is_mode_0700_and_owned_by_the_current_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = run_function(
                '_ensure_private_cache_dir && stat -f "%p %u" "$REVIEW_CACHE_DIR"',
                env={"TMPDIR": str(directory), "SQUAD_SESSION": "test-cachedir-mode"},
            ).strip()
            mode_octal, owner = out.split()
            self.assertEqual(mode_octal[-3:], "700", out)
            self.assertEqual(int(owner), os.getuid())

    def test_the_safe_snapshot_write_does_not_follow_a_preplanted_symlink(self) -> None:
        # Codex's exact repro: pre-creating snap.tmp as a symlink to a
        # victim file, then letting the background writer's `>` redirect
        # follow it, changed the victim's content to "OVERWRITTEN" and left
        # the final snapshot itself a symlink to the victim. mktemp (an
        # unpredictable name, so nothing could be pre-planted there) plus
        # mv/rename (which REPLACES whatever is at the destination -- even a
        # symlink -- rather than writing through it) closes both halves.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "victim.txt"
            victim.write_text("SECRET", encoding="utf-8")
            out = run_function(
                '_ensure_private_cache_dir '
                '&& ln -sf "$VICTIM" "$REVIEW_SNAP_FILE" '
                '&& _write_review_snapshot_safely "safe-content" '
                '&& printf "victim=%s snap_is_symlink=%s snap_content=%s" '
                '"$(cat "$VICTIM")" "$([ -L "$REVIEW_SNAP_FILE" ] && echo yes || echo no)" '
                '"$(cat "$REVIEW_SNAP_FILE")"',
                env={"TMPDIR": str(root), "SQUAD_SESSION": "test-symlink-safety", "VICTIM": str(victim)},
            )
            self.assertIn("victim=SECRET", out, out)
            self.assertIn("snap_is_symlink=no", out, out)
            self.assertIn("snap_content=safe-content", out, out)


class AvatarGlyphTests(unittest.TestCase):
    def test_avatar_glyph_is_stable_across_frames_when_animation_is_off(self) -> None:
        frame0 = run_function(
            "specialist_avatar_glyph exploit-developer 0", env={"SQUAD_CARD_ANIMATION": "off"}
        )
        frame1 = run_function(
            "specialist_avatar_glyph exploit-developer 1", env={"SQUAD_CARD_ANIMATION": "off"}
        )
        self.assertEqual(frame0, frame1)

    def test_a_specialist_without_a_bespoke_avatar_falls_back_to_the_department_motif(self) -> None:
        # ai-engineer has no bespoke crew_banner entry; must still render something
        # non-empty via the coding department's motif fallback (never blank).
        glyph = run_function("specialist_avatar_glyph ai-engineer 0")
        self.assertTrue(glyph.strip())

    def test_every_avatar_glyph_is_narrow_enough_for_the_compact_member_row(self) -> None:
        # fmt_member reserves very little room for the leading glyph slot; a
        # wide glyph would silently break card alignment across every lane.
        specialists = ["exploit-developer", "reverse-engineer", "detection-engineer", "incident-responder", "ai-engineer", "scout"]
        for spec in specialists:
            glyph = run_function(f"specialist_avatar_glyph {spec} 0")
            self.assertLessEqual(len(glyph), 4, f"{spec}: {glyph!r}")


class CrewBannerTests(unittest.TestCase):
    def test_the_four_fully_rendered_specialists_have_a_real_multi_line_banner(self) -> None:
        for spec in ("exploit-developer", "reverse-engineer", "detection-engineer", "incident-responder"):
            banner = run_function(f"crew_banner {spec} 0")
            self.assertGreaterEqual(len(banner.splitlines()), 2, spec)

    def test_blank_advisors_have_bespoke_banners(self) -> None:
        for specialist in ("sol", "fable"):
            banner = run_function(f"crew_banner {specialist} 0")
            self.assertGreaterEqual(len(banner.splitlines()), 2, specialist)


class AnimationOffSwitchTests(unittest.TestCase):
    def test_squad_card_animation_off_freezes_the_status_dot_pulse(self) -> None:
        on = run_function("dot_pulse_color 118 3", env={"SQUAD_CARD_ANIMATION": ""})
        off_a = run_function("dot_pulse_color 118 3", env={"SQUAD_CARD_ANIMATION": "off"})
        off_b = run_function("dot_pulse_color 118 7", env={"SQUAD_CARD_ANIMATION": "off"})
        self.assertEqual(off_a, off_b)
        self.assertEqual(off_a, "118")


if __name__ == "__main__":
    unittest.main()
