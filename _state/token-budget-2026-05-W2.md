# Token Budget — Week of 2026-05-W2

baseline_source: operator-entered (insufficient history)
baseline_date: 2026-05-03
alert_threshold: baseline × 1.5

## Per-pane baseline (dispatches/day)

| Pane | Baseline (per day) | Alert threshold (1.5×) |
|------|--------------------|--------------------------|
| chrono | 50 | 75 |
| coding | 50 | 75 |
| security | 50 | 75 |
| content | 50 | 75 |
| sysmgmt | 50 | 75 |
| research | 50 | 75 |

## Notes

- First week monitoring (2026-05-03 → 2026-05-10): finance-analyst runs daily; alerts fire on any pane crossing 1.5× baseline
- After first week: revert to weekly cadence
- Triggered by: bin/finance-daily.sh (called by launchd or cron during first week)
- Baseline rationale: dispatch-log.jsonl as of 2026-05-03 spans only ~6 hours (first entry 2026-05-02T17:43Z, last 2026-05-03T00:05Z), well under the 7-day window required for an auto-derived baseline. Operator-entered default of 50 dispatches/day/Lead applies until the log accumulates ≥7 days of history.
- Recompute trigger: when `_state/dispatch-log.jsonl` first contains entries spanning ≥7 days, regenerate this file from the auto-derived counts.
