---
name: audio-event-map-authoring
status: authored
---

# Audio Event Map Authoring

Author the typed game-event → audio-cue contract (`audio-event-map.json`) that hands an interactive-audio design to the engine.

## Steps
1. Enumerate the game events that drive audio; assign each a unique, stable event ID.
2. For each event, define the cue, transition/cancellation behavior, parameter IDs, and units/ranges.
3. Specify a missing-cue fallback for every event so the runtime never silently fails.
4. Record memory/voice-count/streaming budgets and loop/loudness/format requirements.
5. Version the schema and name the middleware/runtime target.
6. Add test scenarios that exercise transitions and cancellations.

## Acceptance
- Event and parameter IDs are unique and stable; schema version present.
- Every event has an explicit fallback; budgets and format requirements stated.
- Test scenarios cover transition and cancellation behavior.
