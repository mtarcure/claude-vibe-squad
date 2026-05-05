---
name: llm-app
extends: bounty
status: active
---

# Bounty Profile: LLM / Agent Application

For prompt injection, agent jailbreaks, tool abuse, indirect prompt injection. Newer category — bounty programs increasingly accept LLM findings.

## Auto-detection signals

- Target is described as "AI assistant" / "agent" / "LLM-powered"
- URL of a chatbot or agent platform
- File: model card, tool schemas, system prompts mentioned

## Phase customizations

### Phase 2 Program Scope
- Read model card if available
- Identify available tools / functions the agent can call
- Look for system prompt leaks (sometimes accessible)
- Tools: prompt-engineer specialist for jailbreak pattern catalog; invoking Lead uses its native syntax (`@prompt-engineer` for Gemini, `Task` with `subagent_type: prompt-engineer` for Claude, or `Agent(subagent_type=prompt-engineer)` for Kimi).

### Phase 3 Recon
- Map prompt surface (what inputs reach the model)
- Map tool surface (what tools agent has, with what scopes)
- Test baseline jailbreaks (known patterns from open research)

### Phase 4 Threat Modeling
- Direct prompt injection
- Indirect prompt injection (via documents, URLs, etc.)
- Jailbreaks (override safety constraints)
- Tool abuse (use legitimate tools for malicious purpose)
- Data exfiltration via tool chains

### Phase 6/7/8 Exploitation
- garak for systematic prompt-attack scans
- Manual jailbreak chains
- Multi-step agent attacks (chain prompt injection → tool abuse → data exfil)
- Test across models if multi-LLM target

### Phase 10 Validation
- LLM bounty rubrics differ — some pay for jailbreaks, others only for data leaks
- Check program rules carefully — many LLM bounties exclude DAN-style jailbreaks
- Reproducibility critical (LLM responses are non-deterministic)

### Phase 11 Report
- Include conversation transcripts as evidence
- Show reproduction conditions (temperature, system prompt version, etc.)

## Specialists most active

- prompt-engineer (cross-cutting — knows jailbreak patterns)
- security namespace invokes `exploit-developer` via `Task` tool with `subagent_type: exploit-developer` (multi-step jailbreak chains)
- ai-engineer (Coding cross-Lead — for agent-system specific attacks)
- security namespace invokes `skeptic` via `Task` tool with `subagent_type: skeptic` to verify findings reproduce reliably

## Tools

- garak (Nvidia's LLM red-team toolkit)
- promptfoo (eval framework, useful for jailbreak attack panels)
- AdvBench / HarmBench corpora
