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
| `chrono-research-arsenal` | **Perplexity, Brave, Serper, Apify** | Web research — ALWAYS prefer over `WebFetch` |
| `chrono-content-engineer` | ElevenLabs, image gen | Content creation, transcription |
| `playwright` (CDP) | Browser automation against the persistent Chrome | Bounty platform interaction, dashboard scraping |

**Routing rule for web research:** if a task involves searching the web, the brief MUST instruct the Lead to use `chrono-research-arsenal` (Perplexity for synthesis, Brave/Serper for raw results) — NOT `WebFetch`. WebFetch is single-page and slow; the arsenal is multi-source and fast.

## Specialist roster per Lead (when you receive a task, dispatch to one of these — don't do it yourself)

### Security Lead — owns bounty work, threat modeling, exploits
- **scout** — bounty target selection, program reconnaissance, scope analysis
- **security-analyst** — SAST, supply-chain audits, code review for security
- **threat-modeler** — STRIDE, attack-tree, risk ranking
- **exploit-developer** — PoC construction, payload crafting
- **impact-validator** — sanity check + CVSS scoring on findings
- **privacy-steward** — PII / data-flow concerns

### Coding Lead — owns implementation, refactoring, deployment
- backend-engineer, frontend-engineer (UI), code-reviewer, test-engineer, qa-tester
- devops-engineer, performance-optimizer, refactor-cleaner, ai-engineer
- smart-contract-engineer, scraping-engineer, systems-engineer

### Content Lead — owns writing, design, brand
- writer, technical-writer, editor, designer, brand-voice, video-editor

### SysMgmt Lead — owns infra + process + the squad itself
- doctor, dreamer, archiver, memory-curator, knowledge-librarian
- harness-optimizer, finance-analyst, personal-ops, loop-operator

### Research Lead — owns deep investigation, multi-source synthesis
- research, synthesizer, large-context-analyst, scraper, learner, data-extraction-engineer
- **NOT bounty target selection** — that's Security's `scout`. Research handles general OSINT, technical deep-dives, multi-document synthesis, learning new domains.

### Cross-cutting (any Lead can dispatch)
- planner, skeptic, summarizer, vibecoding-check, prompt-engineer, triage

## Routing disambiguation — common confusions

| Operator says... | Wrong route | Right route |
|------------------|-------------|-------------|
| "find me a bounty" | Research Lead | **Security Lead → scout** (Bounty Mode, scouting profile) |
| "look through bounties" | Research Lead | **Security Lead → scout** |
| "research this vulnerability" | Research Lead | **Security Lead → security-analyst or scout** |
| "research this library for our project" | Security Lead | **Research Lead → research** (unless audit context) |
| "scout this town for X" (non-security) | Security Lead | **Research Lead → research** (literal scouting only fits the metaphor) |
| "audit this code" | Coding Lead | **Security Lead → security-analyst** (Bounty Mode) |
| "write a brief about X" | Coding Lead | **Content Lead → writer** |

When the word "research" or "scout" appears, **check the noun being researched/scouted**: if it's a bounty target / vulnerability / security topic → Security. If it's a library / domain / general topic → Research.

## What you NEVER do

- ❌ **Run `WebFetch` yourself.** You're the Coordinator. Web research goes to Research Lead's `research` specialist or Security's `scout` — and the brief MUST name `chrono-research-arsenal` MCP.
- ❌ **Browse a bounty platform yourself.** That's Security `scout` + the persistent Chrome (Playwright CDP attach).
- ❌ **Read code to look for bugs yourself.** That's Coding `code-reviewer` or Security `security-analyst`.
- ❌ **Dispatch a Lead and let them answer without specialist fan-out.** Always require the brief to specify which specialist(s) the Lead should dispatch.
