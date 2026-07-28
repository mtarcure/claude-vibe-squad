---
name: level-design-patterns
status: authored
---

# Level Design Patterns

Turn a game-design contract into playable level structure: layout, pacing, gating, and a difficulty curve.

## Steps
1. Read the upstream game-design contract; derive the experience pillars the levels must serve.
2. Block out spaces and critical paths; place gates and rewards to control pacing.
3. Map the difficulty curve against explicit player-skill assumptions (teach → test → twist).
4. Annotate each beat with the intended feeling and the mechanic that produces it.
5. Mark playtest assertions per level (completable, no soft-locks, curve holds).
6. Return any unimplementable runtime trigger to `game-engineer` as an unresolved requirement.

## Acceptance
- Every referenced mechanic exists in the upstream game-design contract.
- The difficulty curve is intentional and tied to stated skill assumptions.
- Each level carries playtest assertions and has no dangling triggers.
