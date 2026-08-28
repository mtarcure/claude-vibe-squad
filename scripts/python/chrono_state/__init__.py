"""Chrono state spine.

File-backed correctness for the long-running orchestrator: a bounded active-task
registry, an append-only decision-authority record (separate from Vault), the
append-only Markdown workboard authority, compaction snapshot/policy helpers, and a
token-bounded resume capsule. Chrono's context window is a disposable cache over these
files.
"""
