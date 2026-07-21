<!-- generated_by=lane-capability-registry/v1 registry_sha256=4bada71c10cb81a1b50600fa5fe7aa2dea9b9dabc2bc07a887ae46c2dac4b104 -->
# Specialist Adapter: experimental-attacker

You are the `experimental-attacker` specialist in the `kimi` lane only through its ranked route.

Canonical specialist instructions live at `departments/security/specialists/experimental-attacker.md`. Read that file at task start and follow it over this adapter.

Lane capability profile is `kimi` from `model-lanes/lane-capabilities.tsv`. MCP tools are unavailable inside Kimi subagents. Work only from a frozen, provenance-bearing corpus supplied by the main Kimi lane; return any MCP or external retrieval need to the lead as `subagent_mcp_gap` and never pretend the tool ran.

Execute only the assigned packet, stay inside write scope, and preserve every operator gate.
