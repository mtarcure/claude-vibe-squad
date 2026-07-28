#!/usr/bin/env bash
# Renders the real file-based dispatch loop as a clean terminal cast (asciinema -> agg).
# Structure mirrors an actual task packet + mailbox flow — it narrates, it does not fabricate.
set -u
c(){ printf '\033[%sm' "$1"; }
R="$(c 0)"; DIM="$(c '2;37')"; CY="$(c '1;36')"; YEL="$(c '1;33')"; GRN="$(c '2;32')"
AMB="$(c '1;33')"; BOLD="$(c '1')"; VIO="$(c '38;5;135')"; GRY="$(c '38;5;245')"
p(){ printf '%b\n' "$1"; }
clear
p ""
p "  ${DIM}Vibe Squad — one plain-language request becomes an inspectable file${R}"
p ""
sleep 1.0
p "  ${CY}chrono>${R} ${BOLD}add rate-limiting to the login endpoint${R}"
sleep 1.2
p ""
p "  ${DIM}→ Chrono writes a typed task packet${R}"
sleep 0.7
p "    ${GRY}departments/coding/inbox/${R}${CY}TASK-2026-07-15-…-a1b2.md${R}"
sleep 0.5
p "    ${GRY}---${R}"
p "    ${DIM}specialist:${R}    ${VIO}backend-engineer${R}"
p "    ${DIM}to_model:${R}      ${YEL}gpt-codex${R}      ${GRY}# routed by capability, not folder${R}"
p "    ${DIM}write_scope:${R}   ${GRN}[src/auth/]${R}    ${GRY}# bounded${R}"
p "    ${DIM}review_model:${R}  ${VIO}claude${R}         ${GRY}# different family checks it${R}"
p "    ${GRY}---${R}"
sleep 2.2
p ""
p "  ${DIM}→ validated · write-scope checked · nudged the ${R}${YEL}gpt-codex${R}${DIM} lane${R}"
sleep 1.2
p "     ${AMB}●${R} backend-engineer   ${AMB}working…${R}"
sleep 1.8
printf '\033[1A'
p "     ${GRN}✓${R} backend-engineer   ${DIM}done${R}   token-bucket + tests"
sleep 0.8
p ""
p "  ${DIM}→ result returns to the outbox${R}"
sleep 0.6
p "    ${GRN}→${R} ${GRY}departments/coding/outbox/${R}${CY}TASK-…-a1b2-response.md${R}"
p "    ${GRN}→${R} ${GRY}src/auth/${R}${CY}rate_limit.py${R}   ${DIM}· only inside the declared scope${R}"
sleep 1.8
p ""
p "  ${DIM}→ Chrono surfaces one answer — every step readable with ${R}${BOLD}git${R}${DIM} + a terminal${R}"
sleep 2.0
p ""
