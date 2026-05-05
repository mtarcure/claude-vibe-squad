# Contributing

Vibe Squad is intentionally small and markdown-first. Contributions should make a single-operator local squad easier to run, safer to leave unattended, or clearer to audit.

## Architecture Rules

- Chrono is the only controller.
- GPT/Codex, Claude, Gemini, and Kimi are model leads, not department owners.
- `shared/specialist-runtime-map.tsv` is the routing source of truth.
- `departments/` is source namespace and mailbox compatibility storage only.
- Modes, specialist briefs, model lead prompts, and protocol rules stay in markdown.
- Scripts are launch, dispatch, watcher, validator, and routine rails.

## Adding Workflows

- Add cross-cutting specialists under `shared/specialists/`.
- Add namespace-specific specialist markdown under `departments/<source_namespace>/specialists/`.
- Add the specialist to `shared/specialist-runtime-map.tsv` with `best_model_lane`, `review_model`, `source_namespace`, tools, safety level, and notes.
- Add or update mode workflows in `shared/modes/` only when the operator-facing workflow changes.
- Keep prompts short and non-conflicting; avoid duplicating the same role contract in several files.

## Safety

No patch should introduce silent live sends, silent deletes, credential changes, private-memory export, or public-release changes without operator approval. High-risk work needs multi-model review with the reviewer read-only unless Chrono serializes a later write pass.

## Development Checks

Run the relevant checks before opening a PR:

```bash
bash -n bin/*.sh scripts/*.sh shared/*.sh
python3 -m py_compile scripts/python/*.py bin/*.py
bash bin/validate-specialists.sh
bash bin/product-hygiene.sh --public-export
bash bin/doctor.sh
```

For dispatch changes, smoke test at least one cross-namespace route where `source_namespace` and `to_model` differ.

## Style

- Bash: `set -uo pipefail`, `mkdir -p` before writes, atomic writes for state files.
- Python: keep scripts under `scripts/python/`; use type hints where they clarify behavior.
- Markdown: YAML frontmatter for specialists, modes, and profiles; concise instructions; no stale release-plan prose in canonical prompts.

By contributing, you agree your contribution is licensed under AGPL-3.0.
