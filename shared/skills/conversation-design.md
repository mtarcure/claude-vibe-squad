---
name: conversation-design
status: authored
---

# Conversation Design

Design a conversational flow — intents, turns, prompts, and recovery — so a voice/chat agent handles real dialogue, not just the happy path.

## Steps
1. Map the user intents and the jobs each conversation must complete; write the sample dialogues first.
2. Design turn-taking: what the agent asks, confirms, and remembers across the flow; keep prompts short and answerable.
3. Design error and recovery paths: no-input, no-match, ambiguity, correction, and escape-to-human.
4. Define confirmation strategy for consequential actions (explicit confirm before anything irreversible or costly).
5. Specify persona and tone as constraints, and mark any regulated/consequential flow (payments, health, identity) for review.

## Acceptance
- Happy path and recovery paths (no-input/no-match/ambiguity/handoff) are all designed.
- Consequential actions require explicit confirmation.
- Persona/tone are defined; regulated flows are flagged for review.
