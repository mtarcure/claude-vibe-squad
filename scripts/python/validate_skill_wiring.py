#!/usr/bin/env python3
"""Stop skill-wiring rot on the *proven* claude load path.

WHY THIS EXISTS
  The claude board load path for project skills is the repo-root ``.claude/skills/``
  directory. Proven live 2026-08-18 (TASK-2026-08-18-1354-1d8a9427) by invoking
  ``Skill(probe-canary)``: the runtime resolved the bare name and printed its base
  directory under ``<worktree>/.claude/skills/probe-canary``. The pre-existing home
  validator (``scripts/python/validate_capability_homes.py`` -> ``actual_skill_names()``)
  models the claude skills root as ``model-lanes/claude/.claude/skills``, which holds
  no skills and is NOT a load path. THIS validator uses the corrected path model.
  (Correcting the old validator's model is a separate follow-up: that file is not in
  this task's write scope; it should be retired or repointed at ``.claude/skills`` so
  the two do not disagree — one fact, one home.)

WHAT IT ENFORCES (hard failures -> exit 1)
  1. Integrity of every wired skill under ``<root>/.claude/skills/<name>/SKILL.md``:
       - frontmatter parses,
       - ``name:`` matches the directory name,
       - ``description:`` is present and >= MIN_DESC_LEN chars.
     A skill in the load path with no/short description can never trigger — that is the
     exact failure this whole effort fixes. The check is self-maintaining: it inspects
     whatever is wired, so it never red-lines the un-wired rollout backlog.
  2. Dual-home drift: while a pilot skill lives in BOTH ``.claude/skills/<name>/SKILL.md``
     (winner) and legacy ``shared/skills/<name>.md`` (retained pending retirement), their
     bodies (frontmatter stripped) must stay identical. A drifted flat copy fails, naming
     the ``.claude/skills`` copy as canonical. This enforces Hard Rule 10 for the window
     where two copies coexist.
  3. Trigger distinctness: no two wired skills (and no wired skill vs a known plugin
     competitor) may have descriptions that fire on the same situation. Two skills whose
     triggers overlap make BOTH unreliable at match time — worse than leaving one unwired.
     A near-pair that is deliberately distinct despite shared vocabulary is recorded in
     ``ADJUDICATED_DISTINCT`` with a reason (Hard Rule 10: a named place states the winner);
     anything else above ``COLLISION_THRESHOLD`` fails until disambiguated or retired.
  4. Per-lane reach wiring (the non-claude lanes share ``.agents/skills/``):
       - mirror integrity: every mirrored ``.agents/skills/<name>/SKILL.md`` must be a
         byte-identical regular-file copy of ``.claude/skills/<name>/SKILL.md`` (the named
         winner). A symlink, missing file, or byte drift fails. ``probe-canary`` and skills
         native to ``.agents`` remain distinct per-path exceptions.
       - gemini bridge: ``model-lanes/gemini/.agents/skills`` must be a regular materialized
         directory whose loadable entries correspond to shared-home skills (gemini's cwd is
         model-lanes/gemini; without the bridge it sees only built-in skills).
       - kimi launcher: ``bin/board-supervisor.sh`` must pass ``--skills-dir`` to override
         kimi's broader default discovery with the shared specialist skill home.
  5. Audience routing (who a skill is FOR — see ``model-lanes/SKILL-HOMES.md``):
       - every wired skill declares ``audience: chrono`` or ``audience: specialist``.
         The test is not "could a specialist read this" but "does a specialist ever
         PERFORM this action?" — board dispatch / registry settlement / reviewer routing
         are Chrono's; audit flows / generation craft / verification gates are the
         specialists'. A skill with no/invalid ``audience:`` fails.
       - ``audience: chrono`` skills must NOT be mirrored into the specialist home
         ``.agents/skills/`` — they can never fire for a specialist, so a mirror is pure
         trigger noise competing for a shared attention budget. (``probe-canary`` is the
         one exemption: a per-path infra canary that is deliberately present in both homes.)
       - ``audience: specialist`` skills MUST be present in ``.agents/skills/`` — otherwise
         codex/gemini/kimi cannot reach them at all.
     A handful of ``audience: chrono`` mirrors that predate this rule and cannot be removed
     by a board worker without operator-authorized deletion are carried in ``PENDING_DEMOTION``
     as a LOUD note rather than a hard failure (same "don't red-line CI on blocked rollout
     work" stance as the backlog note below); they clear the moment the operator deletes them.

WHAT IT REPORTS (informational -> never fails the gate)
  - active-thread drift: a charter whose DONE-WHEN checklist is fully checked but
    remains under ``_state/chrono/thread-charters/active/``, any unresolved ``QUEUE``
    entry, malformed three-field charter syntax, and stale ``observed_at`` evidence.
    These are owed-attention reports, never a blocking hook or gate.
  - rollout backlog: demand-referenced + authored skills not yet reachable under
    ``.claude/skills/`` — the remaining rollout after the pilot. Wire on demand.
  - orphan-wired: a wired skill nothing demands (excluding INFRA_WIRED).
  - per-lane skill reach: for each lane (claude / gpt-codex / gemini / kimi), how many
    skills it can actually enumerate and by what mechanism, plus coverage gaps (a
    ``.claude/skills`` skill not mirrored to ``.agents/skills`` = unreachable by the
    non-claude lanes; an ``.agents``-native skill = unreachable by claude). This replaces
    the earlier "lanes never checked (enumeration unproven)" stance: the original paths
    were enumerated live 2026-08-18 (TASK-2026-08-18-1633-3c7b63ef), and Kimi was
    re-probed against installed 1.40.0 on 2026-09-01.

  To promote the backlog to a hard gate once the rollout completes, change the final
  ``return 1 if errors else 0`` to ``return 1 if errors or backlog else 0``. Left as a
  note deliberately: a hard demanded->wired gate today would red-line CI on every skill
  not yet wired during a staged pilot.

PILOT / DUAL-HOME STATUS (2026-08-18, TASK-2026-08-18-1408-6b24b180)
  Source-of-truth is MOVE (skill dirs win; ``shared/skills/`` retired) — accepted in
  principle. During the pilot the pilot skills live in BOTH homes; the ``.claude/skills``
  copy is the winner (it is the live load path). Deletion of the flat files is a separate
  operator-approved cleanup, executed after the pilot is proven live.

USAGE
  validate_skill_wiring.py [--root DIR]     validate the tree at DIR (default: cwd)
  validate_skill_wiring.py --self-test      run the built-in fail-then-pass fixture
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from pathlib import Path

from chrono_state.thread_charters import CHARTERS_REL, clip, load_active_charters

MIN_DESC_LEN = 40
CLAUDE_SKILLS_REL = ".claude/skills"  # CORRECTED claude load path (repo-root); proven 2026-08-18
FLAT_SKILLS_REL = "shared/skills"     # legacy flat home, retained during the pilot
REGISTRY_REL = "shared/registries/skill-tool-registry.tsv"
DEMAND_DIRS = ("shared/capabilities", "shared/specialists", "shared/modes", "departments")

# Skills that legitimately live in the load path with no demand reference (infra/canary).
INFRA_WIRED = {"probe-canary"}

# ---- Audience routing (who a skill is FOR) ----------------------------------
# Every wired skill declares one of these. `chrono` = an action only the controller
# ever performs (board dispatch, registry settlement, reviewer routing, lane failover,
# budget gates); `specialist` = work a lane specialist performs (audit flows, offensive
# bench work, generation craft, verification gates). The discriminator is NOT "could a
# specialist READ this" (they can read anything) but "does a specialist ever PERFORM this
# action?". See model-lanes/SKILL-HOMES.md. A chrono skill mirrored into the specialist
# home (.agents/skills) is pure trigger noise: it competes for match attention against
# skills the specialist can actually act on, and it can never fire for them.
AUDIENCE_VALUES = ("chrono", "specialist")

# audience:chrono skills still physically mirrored in .agents/skills that a board worker
# cannot remove, because this rollout task carried no `authorized_delete_paths` and deletion
# is an operator-gated held category (write_scope is deliberately NOT deletion authority —
# see scripts/python/worktree_isolation.py). Each entry downgrades the condition-B failure
# for that ONE named mirror to a LOUD note until the operator authorizes + executes the
# deletion and removes it here. This is the Hard Rule 10 "a named place records the pending
# winner" pattern, and it matches this file's standing stance of not red-lining CI on blocked
# rollout work (see the backlog note in run()). A stale entry is harmless: it only has any
# effect while the named skill is actually still present in .agents/skills.
PENDING_DEMOTION = {
    "dispatch-packet-authoring":
        "board-dispatch skill; mirror removal needs operator-authorized deletion (TASK-2026-08-18-1807-a72707a2)",
    "review-settlement":
        "registry-settlement skill; mirror removal needs operator-authorized deletion (TASK-2026-08-18-1807-a72707a2)",
    "cross-family-review-routing":
        "reviewer-routing skill; mirror removal needs operator-authorized deletion (TASK-2026-08-18-1807-a72707a2)",
}

# ---- Per-lane skill reach ---------------------------------------------------
# Every board lane can now reach project skills. The original paths were proven
# live 2026-08-18 (TASK-2026-08-18-1633-3c7b63ef); kimi was re-probed against
# installed kimi 1.40.0 on 2026-09-01 after a contradictory later claim. The
# mechanisms differ per CLI:
#   - claude    reads `<cwd=worktree-root>/.claude/skills/`  (its proven load path)
#   - gpt-codex reads `<cwd=worktree-root>/.agents/skills/`  (resolves probe-canary bare)
#   - gemini    is the routing identifier for the agy-backed lane. Its cwd is
#               model-lanes/gemini, so the tracked regular-file materialization at
#               `model-lanes/gemini/.agents/skills` remains the lane-local skill home.
#   - kimi      reads skills natively. Live probe: `kimi --help` described repeatable
#               `--skills-dir` as overriding default discovery; an isolated session `/help`
#               listed `/skill:live-probe-7c91` when supplied by that flag; the same slash
#               command was `Unknown` without it. A no-flag session at the repository root
#               also advertised project skills, proving default project discovery exists.
#               The supervisor's explicit `.agents/skills` override is therefore a scope
#               boundary: it selects the specialist home and excludes controller-only skills.
# The non-claude lanes share `.agents/skills/`, which mirrors cross-lane
# `.claude/skills` entries as byte-identical regular-file copies. The named canonical
# winner is `.claude/skills` (Hard Rule 10; see model-lanes/SKILL-HOMES.md), and
# check_mirror_integrity below makes drift a hard failure. Some skills may be homed
# natively in `.agents/skills` instead. probe-canary is intentionally a distinct
# per-path canary in each home and is never identity-checked as a mirror.
AGENTS_SKILLS_REL = ".agents/skills"
GEMINI_BRIDGE_REL = "model-lanes/gemini/.agents"   # tracked regular materialization
SUPERVISOR_REL = "bin/board-supervisor.sh"
# (lane, cwd-relative-to-root, convention-dir-relative-to-that-cwd, how-it-was-proven)
LANE_REACH = (
    ("claude", ".", CLAUDE_SKILLS_REL,
     "cwd .claude/skills (Skill(probe-canary) resolved bare, 2026-08-18)"),
    ("gpt-codex", ".", AGENTS_SKILLS_REL,
     "cwd .agents/skills (codex resolved probe-canary bare)"),
    ("gemini", "model-lanes/gemini", AGENTS_SKILLS_REL,
     "cwd .agents/skills via the model-lanes/gemini/.agents bridge used by agy"),
    ("kimi", ".", AGENTS_SKILLS_REL,
     "explicit --skills-dir .agents/skills; in-session /help listed injected canary "
     "(kimi 1.40.0 live probe, 2026-09-01)"),
)

# ---- Trigger-distinctness (collision) check ---------------------------------
# A wired skill can parse cleanly, name-match, and carry a long description and
# still be USELESS if a *second* wired skill's description fires on the same
# situation: at match time the runtime cannot tell them apart, so BOTH become
# unreliable. That is worse than leaving one unwired. This check flags wired
# skills whose trigger descriptions overlap.
#
# Metric: overlap coefficient (|A∩B| / min(|A|,|B|)) over significant, lightly
# singularised trigger tokens. It is corpus-INDEPENDENT — a pair's score never
# shifts when some third skill is added — which a tf-idf/cosine approach is not.
COLLISION_THRESHOLD = 0.20

# Plugin skills are competitors too: a wired doc that duplicates a live plugin
# skill's trigger collides with it exactly as it would with one of ours. There
# is no proven in-repo way to enumerate every external plugin skill (same reason
# UNPROVEN_LANES exists), so we carry the known twins the 2026-08-18 skill-library
# audit identified, copied verbatim from the live session skill listing. Extend
# this as new twins surface; a missing competitor is a known limit, not a lie.
PLUGIN_COMPETITORS = {
    "superpowers:verification-before-completion":
        "Use when about to claim work is complete, fixed, or passing, before committing or "
        "creating PRs - requires running verification commands and confirming output before "
        "making any success claims; evidence before assertions always",
    "superpowers:writing-skills":
        "Use when creating new skills, editing existing skills, or verifying skills work "
        "before deployment",
}

# Near-pairs a human reviewed and ruled DELIBERATELY distinct despite lexical
# overlap. This is the "a named file states the winner" half of Hard Rule 10:
# the tool surfaces overlap, a person adjudicates it, and the reason is recorded
# so the next reader is not left re-deciding. Key = frozenset of the two names.
#
# Why this exists rather than a smarter metric: three lexical measures
# (bag-of-words overlap, shared bigrams, tf-idf cosine) were run over this
# library and NONE separates a real trigger collision from mere shared
# domain-vocabulary — an offensive skill and its bench-level sub-skill share the
# coverage enumeration (web/SaaS/cloud/…) without ever firing on the same
# moment. So the check is intentionally sensitive and defers the judgement call
# to this reviewed list instead of pretending a threshold can make it.
ADJUDICATED_DISTINCT = {
    frozenset({"systematic-attacking", "systematic-bug-hunting"}):
        "coarse whole-campaign method vs the bench-level hunting loop invoked *within* it; "
        "shared tokens are the domain-coverage enumeration, not a firing predicate",
    frozenset({"chain-construct", "dedup-prior-art-check"}):
        "chain-construct composes weak findings into an impact chain; dedup-prior-art-check "
        "proves a lead is not already known before/after submission — opposite moments that "
        "share only bug-bounty vocabulary",
}

# Stopwords for trigger tokenisation: generic verbs/prepositions/skill boilerplate
# that carry no situation signal. Kept deliberately broad so domain nouns survive.
_COLLISION_STOP = frozenset("""
a an the of to in on for and or but with without into onto from by as at is are be been being it its
this that these those each any some no not use used using when where while before after during over
under out off up down about across against between within whenever whether than then so single one two
three step steps work works via per would could should may might can cannot never always only just also
both either all other another own same such very much many few we you they them us make makes making
take taken reader true real more most less has have had will shall must does did doing every something
anything everything nothing you are new your
""".split())


def _trigger_tokens(desc: str) -> set[str]:
    """Significant (non-stopword, len>=3), lightly singularised tokens of a trigger."""
    out: set[str] = set()
    for w in re.findall(r"[a-z][a-z0-9]{2,}", desc.lower()):
        if w in _COLLISION_STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # claims->claim, citations->citation; merges trivial plurals
        out.add(w)
    return out


def _overlap_coeff(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def check_trigger_collisions(wired: dict[str, Path]) -> tuple[list[str], list[str]]:
    """Flag wired skills (and wired-vs-plugin) whose triggers fire on the same situation.

    Returns (errors, report_lines). A pair scoring >= COLLISION_THRESHOLD is an error
    unless its {name, name} is in ADJUDICATED_DISTINCT. At least one side of every pair
    is one of OUR wired skills (plugin-vs-plugin is not our problem to fix). Skills whose
    description is missing/short are skipped — the integrity check already fails them.
    """
    ours: dict[str, str] = {}
    for name, path in wired.items():
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        d = (fm or {}).get("description", "")
        if len(d) >= MIN_DESC_LEN:
            ours[name] = d
    everyone = {**ours, **PLUGIN_COMPETITORS}
    toks = {n: _trigger_tokens(d) for n, d in everyone.items()}

    errors: list[str] = []
    scored: list[tuple[float, str, str]] = []
    seen: set[frozenset] = set()
    for a in ours:
        for b in everyone:
            if a == b:
                continue
            key = frozenset({a, b})
            if key in seen:
                continue
            seen.add(key)
            score = _overlap_coeff(toks[a], toks[b])
            if score <= 0:
                continue
            lo, hi = sorted((a, b))
            scored.append((score, lo, hi))
            if score >= COLLISION_THRESHOLD and key not in ADJUDICATED_DISTINCT:
                shared = ", ".join(sorted(toks[a] & toks[b]))
                errors.append(
                    f"trigger collision ({score:.2f} >= {COLLISION_THRESHOLD:.2f}): "
                    f"'{lo}' and '{hi}' fire on overlapping situations — disambiguate one "
                    f"description, retire one, or record the pair in ADJUDICATED_DISTINCT with "
                    f"a reason. shared trigger tokens: {shared}")
    scored.sort(reverse=True)
    report = [f"top trigger overlaps (>= {COLLISION_THRESHOLD:.2f} fails unless adjudicated):"]
    for score, a, b in scored[:8]:
        if frozenset({a, b}) in ADJUDICATED_DISTINCT:
            tag = " [adjudicated-distinct]"
        elif score >= COLLISION_THRESHOLD:
            tag = " <- FAIL"
        else:
            tag = ""
        report.append(f"    {score:.2f}  {a} x {b}{tag}")
    return errors, report


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return a flat dict of the leading ``---`` YAML block, or None if absent/broken.

    Values are read as single-line scalars, which is all the skill frontmatter uses.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def strip_frontmatter(text: str) -> str:
    """Return the body after a leading ``---`` block (or the whole text if none)."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            return text[nl + 1:] if nl != -1 else ""
    return text


def wired_skills(root: Path) -> dict[str, Path]:
    """name -> SKILL.md path for every skill dir directly under .claude/skills/."""
    out: dict[str, Path] = {}
    base = root / CLAUDE_SKILLS_REL
    if base.is_dir():
        for skill_md in sorted(base.glob("*/SKILL.md")):
            out[skill_md.parent.name] = skill_md
    return out


def check_skill_directories(root: Path) -> list[str]:
    """Every immediate skill directory in the live Claude home must be loadable."""
    errors: list[str] = []
    base = root / CLAUDE_SKILLS_REL
    if not base.is_dir():
        return errors
    for entry in sorted(base.iterdir(), key=lambda path: path.name.casefold()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            errors.append(
                f"{CLAUDE_SKILLS_REL}/{entry.name}: skill directory contains no SKILL.md"
            )
    return errors


def _skill_dirs(base: Path) -> dict[str, Path]:
    """name -> SKILL.md for every ``<base>/<name>/SKILL.md`` (follows symlinked dirs)."""
    out: dict[str, Path] = {}
    if base.is_dir():
        for skill_md in sorted(base.glob("*/SKILL.md")):
            out[skill_md.parent.name] = skill_md
    return out


def check_mirror_integrity(root: Path) -> list[str]:
    """The .agents/skills mirror must not drift from its .claude/skills home.

    When a skill name exists in both homes, ``.claude/skills`` is the named winner
    (Hard Rule 10) and the ``.agents`` copy must contain exactly the same SKILL.md
    bytes. Mirrors are regular directories containing regular files: any symlink is
    a hard failure because launch hygiene rejects symlinks in the writable tree.
    ``.agents``-native skills have no canonical same-name file and are left alone;
    ``probe-canary`` is a distinct per-path canary and is exempt from byte identity.
    """
    errors: list[str] = []
    base = root / AGENTS_SKILLS_REL
    if not base.is_dir():
        return errors
    for entry in sorted(base.iterdir()):
        rel = f"{AGENTS_SKILLS_REL}/{entry.name}"
        if entry.is_symlink():
            errors.append(
                f"{rel}: mirror is a symlink — mirrors must be regular directories "
                f"containing byte-identical regular-file copies")
            continue
        if entry.name in INFRA_WIRED:
            continue

        canonical = root / CLAUDE_SKILLS_REL / entry.name / "SKILL.md"
        if not canonical.is_file():
            continue  # .agents-native skill; no same-name canonical mirror to compare
        if not entry.is_dir():
            errors.append(
                f"{rel}: mirror is not a regular directory; expected {rel}/SKILL.md")
            continue

        mirror = entry / "SKILL.md"
        if mirror.is_symlink():
            errors.append(
                f"{rel}/SKILL.md: mirror is a symlink — expected a regular-file copy")
            continue
        if not mirror.is_file():
            errors.append(f"{rel}/SKILL.md: missing regular-file mirror")
            continue
        try:
            identical = canonical.read_bytes() == mirror.read_bytes()
        except OSError as exc:
            errors.append(f"{rel}/SKILL.md: could not compare mirror bytes ({exc})")
            continue
        if not identical:
            errors.append(
                f"{rel}/SKILL.md: bytes differ from canonical "
                f"{CLAUDE_SKILLS_REL}/{entry.name}/SKILL.md; refresh the mirror copy")
    return errors


def check_gemini_bridge(root: Path) -> list[str]:
    """Gemini reaches shared skills through a regular cwd bridge materialization.

    Gemini's process cwd is model-lanes/gemini and it enumerates skills from
    ``<cwd>/.agents/skills``; without that bridge it sees only built-in skills
    (the exact suppression this validator guards).

    The bridge and its entries must NOT be symlinks. launch_hygiene.py refuses to
    start a board worker when a symlink exists in the writable tree. The bridge may
    be a lane-specific subset, but every loadable entry must name a skill in the
    shared ``.agents/skills`` home; an empty, malformed, or unrelated directory is
    not a bridge. Verified live 2026-08-18: gemini enumerates project skills from a
    regular directory.
    """
    errors: list[str] = []
    base = root / AGENTS_SKILLS_REL
    if not base.is_dir() or not any(base.iterdir()):
        return errors
    bridge = root / GEMINI_BRIDGE_REL
    if bridge.is_symlink():
        errors.append(
            f"{GEMINI_BRIDGE_REL}: is a symlink — launch_hygiene.py refuses to start a "
            f"board worker when a symlink is present in the writable tree, so this "
            f"deadlocks dispatch; replace it with a regular directory of copies")
        return errors
    bridge_skills = bridge / "skills"
    if bridge_skills.is_symlink():
        errors.append(
            f"{GEMINI_BRIDGE_REL}/skills: is a symlink — the bridge must contain regular copies")
        return errors
    if not bridge_skills.is_dir():
        errors.append(
            f"{GEMINI_BRIDGE_REL}/skills: missing — gemini runs with cwd "
            f"model-lanes/gemini and would enumerate only built-in skills")
        return errors

    shared = set(_skill_dirs(base))
    bridged = _skill_dirs(bridge_skills)
    for entry in sorted(bridge_skills.iterdir()):
        # Finder may create .DS_Store here. Hidden non-directory metadata is not a
        # skill entry, but symlinks and dot-named directories still need the normal
        # bridge checks below (a dot-named directory can be a genuine skill).
        if entry.name.startswith(".") and not entry.is_symlink() and not entry.is_dir():
            continue
        if entry.is_symlink():
            errors.append(
                f"{GEMINI_BRIDGE_REL}/skills/{entry.name}: is a symlink — bridge entries "
                f"must be regular directories")
        elif not entry.is_dir() or not (entry / "SKILL.md").is_file():
            errors.append(
                f"{GEMINI_BRIDGE_REL}/skills/{entry.name}: malformed bridge entry; "
                f"expected a regular directory containing SKILL.md")
        elif (entry / "SKILL.md").is_symlink():
            errors.append(
                f"{GEMINI_BRIDGE_REL}/skills/{entry.name}/SKILL.md: is a symlink — "
                f"expected a regular-file copy")
    if not bridged:
        errors.append(
            f"{GEMINI_BRIDGE_REL}/skills: contains no loadable project skills")
    unknown = sorted(set(bridged) - shared)
    if unknown:
        errors.append(
            f"{GEMINI_BRIDGE_REL}/skills: contains skill(s) absent from the shared "
            f"{AGENTS_SKILLS_REL} home: {', '.join(unknown)}")
    return errors


def check_kimi_launcher(root: Path) -> list[str]:
    """The kimi launch must select the shared specialist home with ``--skills-dir``."""
    errors: list[str] = []
    sup = root / SUPERVISOR_REL
    if not sup.is_file():
        return errors
    text = sup.read_text(encoding="utf-8", errors="ignore")
    if "--skills-dir" not in text:
        errors.append(
            f"{SUPERVISOR_REL}: no `--skills-dir` wiring for kimi — default project "
            f"discovery can surface controller-only skills; explicitly select "
            f"{AGENTS_SKILLS_REL} as the specialist home")
    return errors


def per_lane_coverage(root: Path) -> tuple[list[str], list[str]]:
    """Compute real per-lane skill reach + enforce the wiring that provides it.

    Returns (errors, report_lines). Errors are active breakage (symlinked/drifted
    mirror, invalid gemini bridge, unwired kimi launcher). The report states, per lane,
    how many skills that lane can actually enumerate and by what mechanism, plus the
    coverage deltas (skills a lane cannot reach). This replaces the old blanket
    "gemini/kimi/gpt-codex never checked (enumeration unproven)" note.
    """
    errors = (
        check_mirror_integrity(root)
        + check_gemini_bridge(root)
        + check_kimi_launcher(root)
    )
    claude_dirs = _skill_dirs(root / CLAUDE_SKILLS_REL)
    claude_set = set(claude_dirs)
    shared_set = set(_skill_dirs(root / AGENTS_SKILLS_REL))
    # audience:chrono skills are INTENTIONALLY not mirrored (specialists never act on them),
    # so they are not a coverage gap — exclude them from the "unreachable" report.
    chrono_named = {n for n, p in claude_dirs.items() if skill_audience(p) == "chrono"}

    report: list[str] = ["per-lane skill reach (proven enumeration paths):"]
    for lane, cwd, conv, how in LANE_REACH:
        reach = _skill_dirs(root / cwd / conv)
        loc = f"{cwd.rstrip('/') or '.'}/{conv}"
        report.append(f"    {lane:9s} {len(reach):3d} skill(s) via {loc}  [{how}]")

    unmirrored = sorted((claude_set - shared_set) - INFRA_WIRED - chrono_named)
    if unmirrored:
        report.append(
            f"    coverage gap: {len(unmirrored)} .claude/skills specialist skill(s) NOT mirrored to "
            f"{AGENTS_SKILLS_REL}/ — unreachable by codex/gemini/kimi (mirror to fix): "
            f"{', '.join(unmirrored)}")
    native_only = sorted((shared_set - claude_set) - INFRA_WIRED)
    if native_only:
        report.append(
            f"    coverage gap: {len(native_only)} {AGENTS_SKILLS_REL}-native skill(s) not homed "
            f"in {CLAUDE_SKILLS_REL}/ — unreachable by claude: {', '.join(native_only)}")
    return errors, report


def skill_audience(path: Path) -> str | None:
    """Return the ``audience:`` frontmatter value of a SKILL.md, or None if absent."""
    fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    value = (fm or {}).get("audience", "")
    return value or None


def check_audience(root: Path, wired: dict[str, Path]) -> tuple[list[str], list[str]]:
    """Enforce the audience routing of every wired skill against its physical homes.

    Three hard conditions (returns errors), plus a loud-note channel:
      A. every wired skill declares ``audience:`` and it is one of AUDIENCE_VALUES;
      B. an ``audience: chrono`` skill must NOT be mirrored into ``.agents/skills/``
         (a specialist can never act on it — the mirror is pure trigger noise). Downgraded
         to a note for the PENDING_DEMOTION mirrors a worker cannot delete without operator
         authorization;
      C. an ``audience: specialist`` skill MUST be present in ``.agents/skills/`` (else
         codex/gemini/kimi cannot reach it at all).
    ``probe-canary`` (INFRA_WIRED) is exempt from B/C: it is a per-path infra canary that is
    deliberately present in both homes with its own body in each.
    """
    errors: list[str] = []
    notes: list[str] = []
    agents_base = root / AGENTS_SKILLS_REL
    # Conditions B/C reason about the specialist mirror home. If the home DIRECTORY is
    # absent there is nothing to mirror into and no drift to police (an empty-but-present
    # home still enforces: every specialist skill then reads as unreachable, which is true).
    # Condition A (audience must be declared) is about the .claude skill itself and always fires.
    agents_home_present = agents_base.is_dir()
    for name, path in sorted(wired.items()):
        rel = path.relative_to(root)
        aud = skill_audience(path)
        if aud is None:
            errors.append(
                f"{rel}: missing 'audience:' — every wired skill must declare "
                f"audience: {' | '.join(AUDIENCE_VALUES)} (who PERFORMS this action)")
            continue
        if aud not in AUDIENCE_VALUES:
            errors.append(
                f"{rel}: audience '{aud}' is not one of {' | '.join(AUDIENCE_VALUES)}")
            continue
        if name in INFRA_WIRED:
            continue  # per-path infra canary: intentionally in both homes
        if not agents_home_present:
            continue  # no shared specialist home present; mirror routing (B/C) not applicable
        mirrored = (agents_base / name / "SKILL.md").is_file()
        if aud == "chrono" and mirrored:
            msg = (
                f"{AGENTS_SKILLS_REL}/{name}: audience:chrono skill must not be mirrored into "
                f"the specialist home — a specialist never performs this action, so the mirror "
                f"is pure trigger noise; remove {AGENTS_SKILLS_REL}/{name}/")
            if name in PENDING_DEMOTION:
                notes.append(
                    f"PENDING DEMOTION: {AGENTS_SKILLS_REL}/{name} — {PENDING_DEMOTION[name]}")
            else:
                errors.append(msg)
        elif aud == "specialist" and not mirrored:
            errors.append(
                f"{AGENTS_SKILLS_REL}/{name}: audience:specialist skill is missing from the "
                f"specialist home — codex/gemini/kimi cannot reach it; mirror it there")
    return errors, notes


def check_integrity(root: Path, wired: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    for name, path in sorted(wired.items()):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(f"{rel}: no parseable YAML frontmatter (need name: + description:)")
            continue
        if fm.get("name", "") != name:
            errors.append(f"{rel}: frontmatter name '{fm.get('name', '')}' != directory '{name}'")
        desc = fm.get("description", "")
        if not desc:
            errors.append(f"{rel}: missing 'description:' — a skill with no description can never trigger")
        elif len(desc) < MIN_DESC_LEN:
            errors.append(f"{rel}: description too short ({len(desc)}<{MIN_DESC_LEN}) to be trigger-shaped")
    return errors


def check_dual_home_drift(root: Path, wired: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    flat_dir = root / FLAT_SKILLS_REL
    for name, path in sorted(wired.items()):
        flat = flat_dir / f"{name}.md"
        if not flat.is_file():
            continue
        a = strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).strip()
        b = strip_frontmatter(flat.read_text(encoding="utf-8", errors="ignore")).strip()
        if a != b:
            errors.append(
                f"{CLAUDE_SKILLS_REL}/{name}/SKILL.md body diverges from legacy "
                f"{FLAT_SKILLS_REL}/{name}.md — canonical winner is the .claude/skills copy; "
                f"update or retire the flat file")
    return errors


def registry_authored(root: Path) -> set[str]:
    reg = root / REGISTRY_REL
    if not reg.is_file():
        return set()
    with reg.open(encoding="utf-8", newline="") as fh:
        return {
            r["name"]
            for r in csv.DictReader(fh, delimiter="\t")
            if r.get("record_kind") == "skill"
            and r.get("verified_state") in {"authored", "yes"}
            and r.get("name")
        }


def demand_referenced(root: Path, universe: set[str]) -> set[str]:
    """Subset of `universe` named (word-boundary) by any demand-dir markdown file."""
    if not universe:
        return set()
    found: set[str] = set()
    for d in DEMAND_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for f in base.rglob("*.md"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for name in universe - found:
                if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", text):
                    found.add(name)
            if found == universe:
                return found
    return found


def thread_charter_reports(root: Path) -> list[str]:
    """Report active-charter debt without changing the validator's exit status."""
    reports: list[str] = []
    try:
        charters = load_active_charters(root / CHARTERS_REL)
    except Exception as exc:  # noqa: BLE001 — reporting must not become a gate
        return [f"{CHARTERS_REL}: charter report unavailable ({exc})"]
    for charter in charters:
        try:
            rel = charter.path.relative_to(root)
        except ValueError:
            rel = charter.path
        for issue in charter.issues:
            reports.append(f"{rel}: invalid charter: {issue}")
        if charter.done_when_met:
            reports.append(
                f"{rel}: DONE-WHEN is met but the charter status is still active "
                f"(move it out of {CHARTERS_REL}/ through the normal lifecycle)"
            )
        for loop in charter.unresolved_queues:
            reports.append(
                f"{rel}: unresolved QUEUE {loop.queue_id}: {clip(loop.raw[2:], 220)}"
            )
        if charter.stale_claims:
            stamps = ", ".join(claim.observed_at for claim in charter.stale_claims[:3])
            extra = " …" if len(charter.stale_claims) > 3 else ""
            reports.append(
                f"{rel}: {len(charter.stale_claims)} stale current claim(s) "
                f"(observed_at={stamps}{extra}; refresh before calling current)"
            )
    return reports


def run(root: Path, verbose: bool = True) -> int:
    root = root.resolve()
    wired = wired_skills(root)

    collision_errors, collision_report = check_trigger_collisions(wired)
    coverage_errors, coverage_report = per_lane_coverage(root)
    audience_errors, audience_notes = check_audience(root, wired)
    errors = (
        check_skill_directories(root)
        + check_integrity(root, wired)
        + check_dual_home_drift(root, wired)
        + collision_errors
        + coverage_errors
        + audience_errors
    )

    authored = registry_authored(root)
    demanded = demand_referenced(root, authored)
    backlog = sorted(demanded - set(wired))
    orphan = sorted(set(wired) - demanded - INFRA_WIRED)
    charter_reports = thread_charter_reports(root)

    # `verbose` is off only for the self-test's internal expected-failure runs, so a real
    # failing gate run always prints its FAIL lines; the self-test asserts on exit codes.
    if verbose:
        for e in errors:
            print(f"FAIL[skill-wiring] {e}", file=sys.stderr)
        if backlog:
            shown = ", ".join(backlog[:20]) + (" …" if len(backlog) > 20 else "")
            print(f"note[skill-wiring] rollout backlog: {len(backlog)} demand-referenced authored "
                  f"skill(s) not yet wired under {CLAUDE_SKILLS_REL}/ (wire on demand): {shown}",
                  file=sys.stderr)
        if orphan:
            print(f"note[skill-wiring] wired but not demand-referenced (candidate orphan): "
                  f"{', '.join(orphan)}", file=sys.stderr)
        for line in collision_report:
            print(f"note[skill-wiring] {line}", file=sys.stderr)
        for line in coverage_report:
            print(f"note[skill-wiring] {line}", file=sys.stderr)
        for line in audience_notes:
            print(f"note[skill-wiring] {line}", file=sys.stderr)
        for line in charter_reports:
            print(f"report[thread-charter] {line}", file=sys.stderr)
        print(f"{'FAIL' if errors else 'ok'}[skill-wiring] {len(wired)} wired skill(s) checked under "
              f"{CLAUDE_SKILLS_REL}/; {len(errors)} error(s)", file=sys.stderr)

    return 1 if errors else 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        good = root / CLAUDE_SKILLS_REL / "good-skill"
        good.mkdir(parents=True)
        (good / "SKILL.md").write_text(
            "---\nname: good-skill\naudience: specialist\ndescription: "
            "Use when you need a well-formed pilot fixture with a real trigger-shaped description.\n"
            "---\n\n# Good skill\n")
        # 1. clean tree with one well-formed wired skill -> PASS
        if run(root, verbose=False) != 0:
            print("self-test FAILED: a well-formed wired skill should pass")
            return 1
        # 1b. a directory on the live skill path without SKILL.md is not loadable -> FAIL
        empty = root / CLAUDE_SKILLS_REL / "empty-skill"
        empty.mkdir()
        if run(root, verbose=False) == 0:
            print("self-test FAILED: a skill directory without SKILL.md should fail")
            return 1
        empty.rmdir()
        # 2. add a wired skill with NO description -> FAIL
        #
        # Every defect below is isolated: the fixture carries a valid `audience:` so the
        # ONLY thing wrong with it is the one branch under test. The earlier version
        # omitted `audience:`, so check_audience failed the fixture on its own and the
        # exit-code assertion passed with all three check_integrity branches deleted --
        # the self-test claimed integrity coverage it did not have.
        dead = root / CLAUDE_SKILLS_REL / "dead-skill"
        dead.mkdir(parents=True)
        (dead / "SKILL.md").write_text(
            "---\nname: dead-skill\naudience: specialist\n---\n\n# Dead skill\n")
        if run(root, verbose=False) == 0:
            print("self-test FAILED: a description-less wired skill should fail")
            return 1
        # 2b. a description too short to be trigger-shaped -> FAIL
        (dead / "SKILL.md").write_text(
            "---\nname: dead-skill\naudience: specialist\ndescription: Too short.\n"
            "---\n\n# Dead skill\n")
        if run(root, verbose=False) == 0:
            print("self-test FAILED: a short-description wired skill should fail")
            return 1
        # 2c. frontmatter name disagreeing with the directory -> FAIL
        (dead / "SKILL.md").write_text(
            "---\nname: not-dead-skill\naudience: specialist\ndescription: "
            "Use when demonstrating that a frontmatter name which disagrees with its "
            "directory is caught.\n---\n\n# Dead skill\n")
        if run(root, verbose=False) == 0:
            print("self-test FAILED: a name/directory mismatch should fail")
            return 1
        # 3. fix it -> PASS again
        (dead / "SKILL.md").write_text(
            "---\nname: dead-skill\naudience: specialist\ndescription: "
            "Use when demonstrating that adding a real description flips the gate back to green.\n"
            "---\n\n# Dead skill\n")
        if run(root, verbose=False) != 0:
            print("self-test FAILED: the fixed skill should pass")
            return 1
        # 4. dual-home drift: a flat copy whose body diverges -> FAIL
        flat = root / FLAT_SKILLS_REL
        flat.mkdir(parents=True)
        (flat / "good-skill.md").write_text("---\nname: good-skill\n---\n\n# DIFFERENT body\n")
        if run(root, verbose=False) == 0:
            print("self-test FAILED: a drifted dual-home flat copy should fail")
            return 1
        # 5. make the flat copy agree -> PASS
        (flat / "good-skill.md").write_text("---\nname: good-skill\n---\n\n# Good skill\n")
        if run(root, verbose=False) != 0:
            print("self-test FAILED: an in-agreement dual-home flat copy should pass")
            return 1

    # 6. Trigger-collision guard: the truth/verification cluster must FAIL, then PASS once
    #    the near-clones are retired and claim-verification is disambiguated — the exact
    #    cluster and fix from TASK-2026-08-18-1456-5085fbce (proof on the named cluster).
    cv_colliding = ("Use before publishing or shipping any deliverable that makes factual, quoted, "
        "calculated, or forecast claims: decompose it into load-bearing claims and verify each "
        "against an exact evidence span (Hard Rule 8 truth gate).")
    cv_disambiguated = ("Use to fact-check a finished deliverable's stated facts — its statistics, "
        "quotations, named sources, dates, and forecasts — by decomposing them into load-bearing "
        "factual claims and matching each to the exact source span that confirms or refutes it "
        "(Hard Rule 8 truth gate). Scope is whether what the text asserts as fact is accurate — the "
        "truth of the content itself, not whether a task's tooling actually ran.")

    def _wire_cluster(root: Path, skills: dict[str, str]) -> None:
        for name, desc in skills.items():
            d = root / CLAUDE_SKILLS_REL / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\naudience: specialist\ndescription: {desc}\n---\n\n# {name}\nbody\n")

    with tempfile.TemporaryDirectory() as tb:
        rb = Path(tb)
        _wire_cluster(rb, {
            "claim-verification": cv_colliding,
            "cite-properly": "Use when an artifact, report, or memory note makes factual claims — "
                "attach a checkable source to every non-obvious claim (file:line, command + output, "
                "URL + date, note id).",
            "claim-validation-gate": "Use before a review, report, or completion envelope leaves: "
                "refuse to let an unverified factual assertion ship; every claim carries its evidence "
                "or is downgraded.",
            "citation-audit": "Use when content already carries citations: resolve each citation, "
                "read the source, and confirm it actually supports the claim, not merely mentions "
                "the topic.",
            # a wired copy of a live plugin skill = straight duplicate of a PLUGIN_COMPETITORS entry
            "verification-before-completion":
                PLUGIN_COMPETITORS["superpowers:verification-before-completion"],
        })
        before, _ = check_trigger_collisions(wired_skills(rb))
        if not before:
            print("self-test FAILED: the truth/verification cluster should collide")
            return 1

    with tempfile.TemporaryDirectory() as ta:
        ra = Path(ta)
        # near-clones + the plugin-twin copy are retired (absent); claim-verification disambiguated
        _wire_cluster(ra, {"claim-verification": cv_disambiguated})
        after, _ = check_trigger_collisions(wired_skills(ra))
        if after:
            print(f"self-test FAILED: disambiguated cluster should pass, got: {after}")
            return 1

    # 7. Per-lane reach: a correctly wired multi-lane tree passes; a byte-different mirror,
    #    a symlink mirror, a dangling mirror, a dot-named real skill, a symlink gemini bridge,
    #    a missing gemini cwd bridge, and an unwired kimi --skills-dir each fail. A regular
    #    hidden metadata file such as .DS_Store passes. (Only the coverage checks can fail here
    #    — the single wired skill is clean otherwise.) Both valid mirrors and the bridge are
    #    REGULAR copies: launch_hygiene.py refuses to start a board worker when a symlink is
    #    present in the writable tree.
    def _mk_bridge(root: Path) -> Path:
        bridge = root / GEMINI_BRIDGE_REL
        bridge.mkdir(parents=True, exist_ok=True)   # regular-dir cwd bridge
        skills = bridge / "skills"
        skills.mkdir(exist_ok=True)                  # gemini enumerates <cwd>/.agents/skills
        for source in sorted((root / AGENTS_SKILLS_REL).glob("*/SKILL.md")):
            target = skills / source.parent.name / "SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())  # regular materialized bridge copy
        return bridge

    def _remove_bridge(bridge: Path) -> None:
        skills = bridge / "skills"
        for skill_md in sorted(skills.glob("*/SKILL.md")):
            skill_md.unlink()
            skill_md.parent.rmdir()
        skills.rmdir()
        bridge.rmdir()

    with tempfile.TemporaryDirectory() as tl:
        rl = Path(tl)
        _wire_cluster(rl, {"foo": "Use when exercising the per-lane coverage fixture — a real "
                                  "trigger-shaped description long enough to clear the gate."})
        agents = rl / AGENTS_SKILLS_REL
        agents.mkdir(parents=True)
        canonical = rl / CLAUDE_SKILLS_REL / "foo" / "SKILL.md"
        mirror_dir = agents / "foo"
        mirror_dir.mkdir()
        mirror = mirror_dir / "SKILL.md"
        mirror.write_bytes(canonical.read_bytes())                         # valid regular copy
        bridge = _mk_bridge(rl)                                            # valid regular-dir bridge
        (rl / SUPERVISOR_REL).parent.mkdir(parents=True, exist_ok=True)
        (rl / SUPERVISOR_REL).write_text("kimi launch: --skills-dir .agents/skills\n")
        if run(rl, verbose=False) != 0:
            print("self-test FAILED: a correctly wired multi-lane tree should pass")
            return 1
        dot_metadata = bridge / "skills" / ".DS_Store"
        dot_metadata.write_bytes(b"Finder metadata fixture\n")
        if run(rl, verbose=False) != 0:
            print("self-test FAILED: a non-symlink hidden metadata file should be ignored")
            return 1
        dot_metadata.unlink()
        dot_skill = bridge / "skills" / ".not-shared"
        dot_skill.mkdir()
        (dot_skill / "SKILL.md").write_text(
            "---\nname: .not-shared\n---\n\n# Dot-named real skill entry\n")
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a dot-named real skill directory should still be checked")
            return 1
        (dot_skill / "SKILL.md").unlink()
        dot_skill.rmdir()
        mirror.write_bytes(canonical.read_bytes() + b"\nmirror drift\n")
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a byte-different .agents/skills mirror should fail")
            return 1
        mirror.write_bytes(canonical.read_bytes())                         # restore valid copy
        mirror.unlink()
        mirror_dir.rmdir()
        os.symlink("../../.claude/skills/foo", agents / "foo")            # forbidden symlink
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a symlink .agents/skills mirror should fail")
            return 1
        (agents / "foo").unlink()
        mirror_dir.mkdir()
        mirror = mirror_dir / "SKILL.md"
        mirror.write_bytes(canonical.read_bytes())                         # restore valid copy
        os.symlink("../../.claude/skills/missing", agents / "bar")        # dangling mirror
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a dangling .agents/skills mirror should fail")
            return 1
        (agents / "bar").unlink()
        wrong = bridge / "skills" / "not-shared"
        wrong.mkdir()
        (wrong / "SKILL.md").write_text("---\nname: not-shared\n---\n\n# Wrong bridge entry\n")
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a bridge entry absent from the shared home should fail")
            return 1
        (wrong / "SKILL.md").unlink()
        wrong.rmdir()
        _remove_bridge(bridge)                                             # symlink bridge
        os.symlink("../../.agents", bridge)
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a symlink gemini bridge should fail")
            return 1
        bridge.unlink()                                                    # missing bridge
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: a missing gemini cwd bridge should fail")
            return 1
        _mk_bridge(rl)                                                     # restore valid bridge
        (rl / SUPERVISOR_REL).write_text("kimi launch: (no skills-dir wired)\n")  # unwired kimi
        if run(rl, verbose=False) == 0:
            print("self-test FAILED: an unwired kimi --skills-dir should fail")
            return 1

    # 8. Audience routing: A (missing/invalid audience), B (chrono skill mirrored into the
    #    specialist home), C (specialist skill missing from it) each fail, then pass once
    #    corrected. Descriptions are deliberately disjoint so the collision check stays silent
    #    and ONLY the audience gate is under test.
    DESC_SPEC = ("Use when auditing a Solidity vault for reentrancy and oracle manipulation "
                 "before a bench engagement begins.")
    DESC_CHRONO = ("Use when routing a finished board packet to an anti-affinity reviewer lane "
                   "and settling the registry entry afterwards.")

    def _wire_aud(root: Path, name: str, desc: str, audience: str | None) -> None:
        d = root / CLAUDE_SKILLS_REL / name
        d.mkdir(parents=True, exist_ok=True)
        aud = f"audience: {audience}\n" if audience else ""
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\n{aud}description: {desc}\n---\n\n# {name}\nbody\n")

    def _mirror(agents: Path, name: str, desc: str, audience: str = "specialist") -> None:
        m = agents / name
        m.mkdir(parents=True, exist_ok=True)
        (m / "SKILL.md").write_text(
            f"---\nname: {name}\naudience: {audience}\ndescription: {desc}\n---\n\n# {name}\nbody\n")

    def _unmirror(agents: Path, name: str) -> None:
        (agents / name / "SKILL.md").unlink()
        (agents / name).rmdir()

    with tempfile.TemporaryDirectory() as tud:
        ru = Path(tud)
        _wire_aud(ru, "spec-skill", DESC_SPEC, "specialist")
        _wire_aud(ru, "chrono-skill", DESC_CHRONO, "chrono")
        agents = ru / AGENTS_SKILLS_REL
        agents.mkdir(parents=True)
        _mirror(agents, "spec-skill", DESC_SPEC)          # specialist correctly mirrored
        _mk_bridge(ru)                                      # valid gemini bridge
        (ru / SUPERVISOR_REL).parent.mkdir(parents=True, exist_ok=True)
        (ru / SUPERVISOR_REL).write_text("kimi launch: --skills-dir .agents/skills\n")
        # baseline: specialist mirrored, chrono NOT mirrored -> PASS
        if run(ru, verbose=False) != 0:
            print("self-test FAILED: correct audience wiring should pass")
            return 1
        # A. a wired skill with no audience -> FAIL
        _wire_aud(ru, "spec-skill", DESC_SPEC, None)
        if run(ru, verbose=False) == 0:
            print("self-test FAILED: a wired skill missing audience: should fail")
            return 1
        _wire_aud(ru, "spec-skill", DESC_SPEC, "specialist")   # restore -> (rechecked below)
        # B. an audience:chrono skill mirrored into the specialist home -> FAIL
        _mirror(agents, "chrono-skill", DESC_CHRONO, "chrono")
        if run(ru, verbose=False) == 0:
            print("self-test FAILED: an audience:chrono skill mirrored to .agents/skills should fail")
            return 1
        _unmirror(agents, "chrono-skill")                  # remove chrono mirror -> PASS
        if run(ru, verbose=False) != 0:
            print("self-test FAILED: removing the chrono mirror should pass")
            return 1
        # C. an audience:specialist skill missing from the specialist home -> FAIL
        _unmirror(agents, "spec-skill")
        if run(ru, verbose=False) == 0:
            print("self-test FAILED: an audience:specialist skill missing from .agents/skills should fail")
            return 1
        _mirror(agents, "spec-skill", DESC_SPEC)           # restore specialist mirror -> PASS
        if run(ru, verbose=False) != 0:
            print("self-test FAILED: restoring the specialist mirror should pass")
            return 1

    # 9. Active-thread drift is informational but loud: completed-active and
    #    unresolved-QUEUE cases report; an incomplete clean charter and an append-only
    #    queue resolution do not.  The run gate stays green in all four fixtures.
    def _write_charter(root: Path, name: str, loops: str, done: str) -> None:
        active = root / CHARTERS_REL
        active.mkdir(parents=True, exist_ok=True)
        (active / f"{name}.md").write_text(
            "## THE ASK\nWire the fixture.\n\n"
            f"## OPEN LOOPS\n{loops}\n\n"
            f"## DONE-WHEN\n{done}\n",
            encoding="utf-8",
        )

    with tempfile.TemporaryDirectory() as tc:
        rc = Path(tc)
        _write_charter(rc, "clean", "- (none)", "- [ ] proof remains")
        if thread_charter_reports(rc):
            print("self-test FAILED: a clean incomplete charter should not report")
            return 1
        if run(rc, verbose=False) != 0:
            print("self-test FAILED: charter reports must never block the validator")
            return 1

    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        _write_charter(rd, "done", "- (none)", "- [x] proof complete")
        reports = thread_charter_reports(rd)
        if not any("DONE-WHEN is met" in report for report in reports):
            print("self-test FAILED: a completed active charter should report")
            return 1

    queue_line = (
        "- 2026-08-18T12:00:00Z | QUEUE Q-001 | later work "
        "— why: separate; resume: return to proof"
    )
    with tempfile.TemporaryDirectory() as tq:
        rq = Path(tq)
        _write_charter(rq, "queued", queue_line, "- [ ] proof remains")
        reports = thread_charter_reports(rq)
        if not any("unresolved QUEUE Q-001" in report for report in reports):
            print("self-test FAILED: an unresolved queue should report")
            return 1

    with tempfile.TemporaryDirectory() as tr:
        rr = Path(tr)
        resolution = (
            queue_line
            + "\n- 2026-08-18T12:01:00Z | DECLINE resolves Q-001 | later work "
            "— why: no longer needed; resume: return to proof"
        )
        _write_charter(rr, "resolved", resolution, "- [ ] proof remains")
        if any("unresolved QUEUE" in report for report in thread_charter_reports(rr)):
            print("self-test FAILED: an appended queue resolution should clear the report")
            return 1

    print("self-test PASSED (integrity: pass clean / fail on missing SKILL.md or description / pass fixed; "
          "dual-home: fail on drift / pass in agreement; "
          "collision: truth/verification cluster fails, then passes after retire + disambiguate; "
          "per-lane: valid multi-lane tree passes, byte-different / symlink / dangling mirrors, "
          "hidden metadata passes, dot-skill / wrong-content / symlink / missing bridges, and "
          "unwired kimi each fail; "
          "audience: correct routing passes, missing-audience / chrono-mirrored / "
          "specialist-unmirrored each fail then pass; "
          "thread-charter: clean is quiet, completed-active and unresolved-QUEUE report, "
          "append-only resolution clears without blocking)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate claude-lane skill wiring integrity.")
    ap.add_argument("--root", default=".", help="repository root to validate (default: cwd)")
    ap.add_argument("--self-test", action="store_true", help="run the built-in fail-then-pass fixture")
    # parse_known_args: this validator shares bin/validate-capabilities.sh's argv with a sibling
    # validator; tolerate flags meant only for the sibling.
    args, _unknown = ap.parse_known_args(argv)
    if args.self_test:
        return self_test()
    return run(Path(args.root))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
