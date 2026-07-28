---
name: game-mechanics-balancing
status: authored
---

# Game Mechanics Balancing

Tune numbers and systems so the game is fair, readable, and holds its intended difficulty curve — by model, not guesswork.

## Steps
1. Read the game-design contract; identify the systems to balance and the pillar each must serve.
2. Build an explicit model of each system (costs, rewards, rates, probabilities); state assumptions about player skill.
3. Balance against the intended difficulty curve (teach → test → twist); avoid dominant strategies and dead options.
4. Identify feedback loops (positive/negative) and bound runaway or stalling states.
5. Define the playtest/telemetry assertions that would prove the balance holds; mark values needing live playtest data as provisional, not final.

## Acceptance
- Each balanced system has an explicit numeric model and skill assumption.
- No dominant strategy or dead option is left unexamined; feedback loops are bounded.
- Balance claims carry playtest/telemetry assertions; unverified values are marked provisional.
