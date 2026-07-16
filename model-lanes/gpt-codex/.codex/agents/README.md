# GPT/Codex Agent Adapters

Generated from `shared/specialist-runtime-map.tsv`. Do not edit these by hand; edit canonical specialist markdown and rerun `python3 scripts/python/sync_agent_adapters.py`.

Codex-native adapters are standalone `.toml` files. Resolve a hyphenated
specialist to its underscore-form TOML `name` field; that field is
authoritative even when the generated filename uses hyphens. A same-name
`.md` file is only a compatibility alias for legacy predispatch checks and
must identify the native TOML target.
