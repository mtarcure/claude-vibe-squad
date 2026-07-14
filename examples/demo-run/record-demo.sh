#!/usr/bin/env bash
# Renders the real demo-run panel as a clean terminal cast (asciinema -> agg).
# All content is real data from examples/demo-run/ — this narrates, it does not fabricate.
set -u
c(){ printf '\033[%sm' "$1"; }
R="$(c 0)"; DIM="$(c '2;37')"; CY="$(c '1;36')"; YEL="$(c '1;33')"
GRN="$(c '2;32')"; AMB="$(c '1;33')"; RED="$(c '1;31')"; ORA="$(c '38;5;214')"; BOLD="$(c '1')"; VIO="$(c '38;5;135')"
p(){ printf '%b\n' "$1"; }

clear
p ""
p "  ${DIM}Vibe Squad — one request becomes one audited answer${R}"
p ""
sleep 1.0
p "  ${CY}chrono>${R} ${BOLD}review reviewed-change.py with a panel${R}"
sleep 1.1
p ""
p "  ${DIM}→ dispatching panel · coordinator ${R}${VIO}synthesizer${R}${DIM} · claude lane${R}"
p "    ${DIM}--panel ${R}${CY}code-reviewer,security-analyst${R}"
sleep 1.2
p ""
p "  ${YEL}⚡ SWARM ×2${R}   ${DIM}two specialists reviewing in parallel${R}"
sleep 0.5
p "     ${AMB}●${R} code-reviewer      ${AMB}running…${R}"
p "     ${AMB}●${R} security-analyst   ${AMB}running…${R}"
sleep 1.9
printf '\033[2A'
p "     ${GRN}✓${R} code-reviewer      ${DIM}done${R}   negative cart total          ${ORA}High${R}    "
p "     ${GRN}✓${R} security-analyst   ${DIM}done${R}   SQL injection                ${RED}Critical${R}"
sleep 0.5
p "     ${DIM}↳ ran concurrently — ~78s wall-clock, not ~143s serial${R}"
sleep 1.7
p ""
p "  ${DIM}→ coordinator synthesizes ${R}${BOLD}one${R}${DIM} evidence-weighted result${R}"
sleep 0.6
p "    ${BOLD}Verdict: changes needed before merge${R}"
p "    ${DIM}both reviewers converged on the same top fix from ${R}${BOLD}opposite${R}${DIM} angles${R}"
p "    ${DIM}— one change closes both the Critical and the High.${R}"
sleep 1.9
p ""
p "    ${GRN}→${R} panel-result.md   ${DIM}· one canonical artifact${R}"
sleep 0.7
p "    ${GRN}✓${R} ${DIM}git checkpoint auto-recorded before dispatch${R}"
sleep 2.0
p ""
