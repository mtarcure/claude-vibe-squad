---
name: interactive-audio-design
status: authored
---

# Interactive Audio Design

Design the interactive layer over generated audio assets: adaptive music, dynamic SFX systems, spatial audio, mix/ducking, and audio state machines.

## Steps
1. Derive audio states from the game state model (menu, explore, combat, etc.); define entry/exit and transition rules between them.
2. Design adaptive music as layers/stems with transition behavior (crossfade, stinger, horizontal re-sequence) tied to state.
3. Design the SFX system: sound pools, round-robin/randomization to avoid repetition, and spatialization rules.
4. Define mix buses and ducking rules (e.g. duck SFX under dialogue) as deterministic parameters, not vibes.
5. For each cue, specify trigger, parameters, and a memory/voice-count/streaming budget; name the middleware/runtime target.
6. Hand rendering to the audio asset specialists and integration to `game-engineer`; never self-clear voice-likeness.

## Acceptance
- Every audio state has entry/exit + transition behavior; no unbounded voice count.
- Mix and ducking rules are deterministic and parameterized.
- Each cue names its trigger, parameters, and budget; middleware target stated.
