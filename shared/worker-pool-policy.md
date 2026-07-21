---
schema_version: worker-pool-policy/v1
policy_id: bigswarm-local-16gb-v1
status: needs_review
author_family: openai
review_model: claude
policy_tsv: shared/worker-pool-policy.tsv
policy_tsv_sha256: f10e5dc07f6c0b4d00faf792cd4ff06b8e1180b7b7b25bebede5c6643694a1f3
---

# Worker pool policy

This default-off policy is the reviewable configuration surface for P3 worker admission. The TSV is authoritative for numeric limits; this Markdown file binds its exact bytes and records the required cross-family reviewer. Runtime activation requires an external `approved` review state and the exact independently reviewed canonical policy hash; editing this file's status alone grants no authority.

The global pool is capped at six workers with one slot reserved for review. The memory gate projects each candidate lane's worker estimate onto current used memory and denies admission at or above 14,336 MiB; any explicit memory-pressure, active-swap, or compressor-pressure signal also denies admission. Runtime host measurements and provider states are mandatory inputs, never inferred as healthy.

Queue admission and lease admission are distinct. Queue-cap deferral leaves the durable task queued and does not consume a delivery attempt. Lease admission independently checks global and lane occupancy, reserved review capacity, unresolved author review debt, projected memory and pressure signals, write-scope overlap, per-lead subagent capacity, and provider capacity. A saturation decision never changes the requested lane.

Provider guards are concrete. Claude and GPT/Codex are capacity-guarded at two concurrent requests and 20 admissions per minute. Gemini and Kimi are additionally metered: each reviewed activation budget is 1,000,000 micro-USD, with conservative default reservations of 50,000 and 100,000 micro-USD per task respectively. Each admission persists its reservation in the registry transaction; existing reservations, externally reported spend, concurrency, and recent request counts are all included before another lease is admitted. Exhausted budget or concurrency/rate saturation defers the task without changing its lane or consuming a delivery attempt.

Review work is exempt from author-debt backpressure and may use the reserved review slot, which prevents settlement deadlock. Same-family work cannot settle its own debt. The supervisor uses bounded AIMD: after three stable scans it may increase a lane target by one; pressure or provider throttling reduces the target by at least one. A leased worker is marked draining and allowed to finish; it is never killed to satisfy a target.

The authoritative nudge scan is bounded to five seconds. Heartbeat, lease, and drain timeouts are 30, 300, and 600 seconds respectively. Runtime host memory comes from a macOS `sysctl`/`vm_stat`/`memory_pressure`/swap sample on every scan. The 16,384 MiB policy value is only a fail-closed fallback ceiling when live sampling fails; it is not reported as a healthy static measurement. Changing any policy value requires updating the TSV hash here and obtaining a new independent review before activation.
