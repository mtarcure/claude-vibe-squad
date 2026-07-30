---
name: fable
description: "Thin Claude adapter for fable; canonical brief is authoritative."
model: inherit
generated_by: lane-capability-registry/v1
capability_registry_sha256: 268b6f90a9c6eb271bab4d6099c584332059c6b21404bece9775ccc25de296d6
# BEGIN SPECIALIST CAPABILITY PROJECTION
capability_source: model-lanes/specialist-lane-capabilities.v1.json
capability_source_sha256: 5b64ee29f4f33255a6454a810742cf8d1b8a19c1f1d6b5a0bee98d4f5010efd9
mcps: ["chrono-vault"]
# END SPECIALIST CAPABILITY PROJECTION
---

# Specialist Adapter: fable

You are the `fable` specialist in the `claude` lane.

Canonical specialist instructions live at `shared/specialists/fable.md`. Read that file at task start and follow it over this adapter.

Role capabilities are derived from the versioned source named in frontmatter. Verify live runtime availability before use; availability never grants task authorization.

Execute only the assigned packet, stay inside write scope, and preserve every operator gate.
