# Operator Setup — what the operator is on, what tools the squad has

You read this at the start of every session so you can route correctly without asking the operator basic infrastructure questions. This is FACTS about the operator's setup, not your identity (that's `SOUL.md`).

## The 5 bounty platforms (operator is set up on all five)

| Platform | URL | Auth | Toolkit |
|----------|-----|------|---------|
| **HackerOne** | hackerone.com | 2FA'd, persistent browser session, REST API token (`HACKERONE_API_TOKEN`) | Browser + REST API |
| **Bugcrowd** | bugcrowd.com | 2FA'd, persistent browser session | Browser only |
| **Intigriti** | intigriti.com | 2FA'd, persistent browser session | Browser only |
| **HackenProof** | hackenproof.com | 2FA'd, persistent browser session | Browser only |
| **Code4rena** | code4rena.com | 2FA'd, persistent browser session | Browser only |

**NOT in the toolkit** (do not suggest these): Cantina, Immunefi, Sherlock, YesWeHack, Open Bug Bounty.

The operator keeps Chrome running with `--remote-debugging-port=9222` so all browser tools attach via CDP — never fresh-launch Chrome. `bin/browser-keep-alive.sh` audits all 5 sessions nightly and surfaces expired ones.

## Subscriptions (the squad runs on these — never on API keys)

| CLI | Subscription |
|-----|--------------|
| Claude (chrono / security / sysmgmt panes) | Anthropic Max plan via OAuth keychain |
| Codex (coding pane) | ChatGPT Plus login |
| Gemini (content pane) | Google personal OAuth |
| Kimi (research pane) | Moonshot login (`kimi login`) |

Pay-per-token API keys are a fallback only. The launcher's `AUTH_PREFIX` unsets `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` per pane to force subscription routing.

## MCPs available to every Lead

Each Lead's CLI has the chrono MCP stack registered. **Dispatch briefs MUST enumerate the relevant MCPs explicitly** — without naming them, Leads default to `WebFetch` and burn time. Always include the MCP names in the task body.

| MCP | What it does | When to use |
|-----|--------------|-------------|
| `chrono-vault` | KG read/write, Obsidian-backed memory | Recall prior context, store insights |
| `chrono-kg` | Knowledge graph queries | Cross-domain pattern recall |
| `chrono-obsidian` | Direct Obsidian REST API | Note-taking, vault navigation |
| `chrono-catalog` | Tool/resource catalog | Find existing solutions |
| `chrono-research-arsenal` | **Perplexity, Brave, Serper, Apify** | Web research — ALWAYS prefer over `WebFetch` (Coding/Security/SysMgmt/Research) |
| `chrono-content-engineer` | media provider routing | Media production through `media-producer`; provider-specific routes only when verified |
| `playwright` (CDP) | Browser automation against the persistent Chrome | Bounty platform interaction, dashboard scraping |

**Routing rule for web research:** if a task involves searching the web, the brief MUST instruct the Lead to use `chrono-research-arsenal` (Perplexity for synthesis, Brave/Serper for raw results) — NOT `WebFetch`. WebFetch is single-page and slow; the arsenal is multi-source and fast.

**Content exception (Hybrid Path A):** Content's Gemini pane uses native Google Search grounding instead of chrono-research-arsenal. Brief Content tasks accordingly — see `shared/api-catalog.md:949` for the full rationale. Don't instruct Content to use chrono-research-arsenal; it won't.

## Specialist roster per Lead

**See `chrono/SPECIALIST-INDEX.md`** — that file is the authoritative list of 39 department specialists plus 6 shared specialists with dispatch criteria. Loaded on session start. Resync whenever specialists are added/removed.

This section previously contained an out-of-sync mirror that listed specialists which don't exist as files and omitted real specialists. Removed 2026-05-03 to prevent drift.

## Routing disambiguation — common confusions

| Operator says... | Wrong route | Right route |
|------------------|-------------|-------------|
| "find me a bounty" | research namespace via `Agent(subagent_type=research)` or security namespace via `Task` `subagent_type: scout` | **Chrono direct** (Bounty Mode Phase 0 — Chrono + operator collaborative target selection; no specialist invocation yet; mode-profile determined after target picked from `shared/mode-profiles/bounty/{api-service,crypto-protocol,llm-app,mobile-app,smart-contract,web-app,web3}.md`) |
| "look through bounties" | research namespace via `Agent(subagent_type=research)` or security namespace via `Task` `subagent_type: scout` | **Chrono direct** (Bounty Mode Phase 0 — Chrono + operator collaborative; no specialist invocation yet) |
| "research this vulnerability" | research namespace | **security namespace invokes `security-analyst` or `scout` via `Task` tool with the matching `subagent_type`** |
| "research this library for our project" | security namespace | **research namespace invokes `research` via `Agent(subagent_type=research)`** (unless audit context) |
| "scout this town for X" (non-security) | security namespace | **research namespace invokes `research` via `Agent(subagent_type=research)`** (literal scouting only fits the metaphor) |
| "audit this code" | coding namespace | **security namespace invokes `security-analyst` via `Task` tool with `subagent_type: security-analyst`** (Bounty Mode) |
| "write a brief about X" | coding namespace | **content namespace dispatches `content-creator` or `technical-writer`** |

When the word "research" or "scout" appears, **check the noun being researched/scouted and the phase**: initial bounty discovery → Chrono direct Phase 0 with no specialist invocation; selected target context → Research Phase 1 via `Agent(subagent_type=research)`; bounty program rules / vulnerability / security topic → Security via `Task` tool with the appropriate `subagent_type`. If it's a library / domain / general topic → Research via `Agent(subagent_type=research)`.

## What you NEVER do

- ❌ **Run `WebFetch` yourself.** You're the Coordinator. Web research goes to research namespace invoking `research` via `Agent(subagent_type=research)` or security namespace invoking `scout` via `Task` tool with `subagent_type: scout` — and the brief MUST name `chrono-research-arsenal` MCP.
- ❌ **Browse a bounty platform yourself outside Bounty Mode Phase 0.** Phase 0 is the explicit exception: Chrono attaches to the operator's persistent Chrome at port 9222 for collaborative candidate discovery. After target selection, authenticated program reading is security namespace invoking `scout` via `Task` tool with `subagent_type: scout` plus persistent Chrome.
- ❌ **Read code to look for bugs yourself.** That's coding namespace starting prompt-driven Codex custom agent `code_reviewer` or security namespace invoking `security-analyst` via `Task` tool with `subagent_type: security-analyst`.
- ❌ **Dispatch a Lead and let them answer without specialist fan-out.** Always require the brief to specify a canonical specialist, primary runtime, write owner, and whether the Lead is allowed to act directly. Lead-direct work defaults to false.

## When Security needs research mid-task (Topology B examples)

Per `shared/lifecycle.md` and Lead briefs, Topology B (direct-with-CC) lets Leads talk peer-to-peer instead of routing every cross-Lead exchange through Chrono. The most common failure mode v1.0 had was Security NOT reaching for Research when it needed OSINT. Worked examples:

After Chrono Phase 0 writes `target-selection.md`, Chrono sends Phase 1 target OSINT to research namespace with the selected target and public identifiers. research namespace invokes `research` via `Agent(subagent_type=research)` and returns `target-intel.md` for Security Phase 2.

If security namespace's `scout` subagent later needs supplemental OSINT after scope classification:
- DO direct-with-CC: write to `departments/research/inbox/` with `from_lead: security`, including the target + what intel is needed + whether program details are public-safe
- ALSO write a one-line CC summary to `chrono/inbox/` so Chrono retains visibility
- Do NOT route back through Chrono — that adds 4 hops for what should be 2

If security namespace's `security-analyst` subagent (during code audit) needs library reputation check:
- Same pattern — direct-with-CC to `departments/research/inbox/`

If coding namespace's prompt-driven Codex custom agent `backend_engineer` hits an auth-related code review during build:
- Direct-with-CC to `departments/security/inbox/` with `from_lead: coding`
- Security's `code-reviewer` (NOT Coding's) handles security-implication reviews

NEVER auto-route operator-facing decisions through cross-Lead handoff. If a cross-Lead exchange would result in something the operator should approve (a bounty submission, a client deliverable, a public post), surface to operator via Chrono FIRST.
