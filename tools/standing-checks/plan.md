# Execution plan

Task: `TASK-2026-08-04-0300-W1B-checks`

| Phase | Planned action | Completion evidence |
| --- | --- | --- |
| S0 | Lock exact local read-only target pins, writable paths, and forbidden external actions. | `target-integrity.md`, `verification-evidence.md` |
| S1 | Recall task-specific prior context once; do not treat recalled notes as proof. | Recall id `b2fcb3e5-5e83-4800-aaba-a5d1a00a2e9e` |
| S2 | Design deterministic table/verdict contracts, positive controls, and bounded target conclusions. | Both check READMEs; dispatcher plan subject `1cfb819a466e6dccd006e556ac553c8217d3b35adb9d53b5982f978a2466ecd0` |
| S3 | Implement an `rg`-backed Solidity/Rust proof census and a Forge-backed byte-range storage diff. | Both `check.py` runners and fixtures |
| S4 | Run vulnerable and guarded controls; repair detector/control failures rather than accepting vacuity. | `action-log.md`; both final-control reports |
| S5 | Repeat final controls, run both checks against exact local pins, and preserve literal output. | Reports and raw Forge evidence hash index |
| S6 | Verify target integrity, scope, no-self-inflicted execution, no-submit state, and bounded verdict language. | `target-integrity.md`, `verification-evidence.md` |
| S7 | Hash the canonical artifact list, record durable telemetry once, write return artifact, then write the envelope last. | Memory id `mem-e54e325279b1`; `artifact-hashes.sha256`; `run-manifest.json`; return artifact; envelope |

Plan/deliverable review is anti-affinity work for the dispatcher-selected Claude family and is not self-certified by this OpenAI author lane.
