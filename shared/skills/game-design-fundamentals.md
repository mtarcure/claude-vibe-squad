---
name: game-design-fundamentals
status: authored
---

# Game Design Fundamentals

Turn a game concept into a design contract: core loop, player fantasy, goals/obstacles, and the experience pillars everything else serves.

## Steps
1. State the player fantasy and the experience pillars (3–5) the game must deliver.
2. Define the core loop (the moment-to-moment action → reward → motivation cycle) and the session/meta loops around it.
3. Specify goals, obstacles, and the resources/verbs the player uses to act on the world.
4. Define the win/lose/progress conditions and how difficulty and mastery evolve over time.
5. Write the result as a contract downstream specialists consume (`level-design-patterns`, `narrative-structure`, `game-mechanics-balancing`); flag anything requiring engine support to `game-engineer`.

## Acceptance
- The core loop is explicit and tied to the stated player fantasy/pillars.
- Goals, obstacles, and player verbs are named, not implied.
- The output is a contract the level/narrative/balance specialists can build against.
