#!/usr/bin/env bash
# Nightly error aggregator.
# Greps tmux-logs + nightly-failures + doctor-logs for ERROR/Traceback/FAILED
# patterns and writes structured entries to _state/errors.jsonl.
# Schema: {ts, source_log, pane, error_signature, line_summary}

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
ERRORS="${VAULT}/_state/errors.jsonl"
TS=$(date -u +%FT%TZ)
mkdir -p "$(dirname "$ERRORS")"

# Aggregate from tmux-logs (per-pane stdout)
for log in "${VAULT}"/_state/tmux-logs/*.log; do
    [ -f "$log" ] || continue
    pane=$(basename "$log" .log)
    grep -nE "ERROR|Traceback|FAILED|panic|fatal" "$log" 2>/dev/null | tail -50 | while IFS=: read -r linenum line; do
        # Sanitize line for JSON (strip quotes/backslashes/newlines)
        safe_line=$(echo "$line" | head -c 200 | tr -d '"\\\n\r\t')
        sig=$(echo "$safe_line" | shasum -a 256 | cut -c1-12)
        printf '{"ts":"%s","source_log":"tmux-logs/%s","pane":"%s","error_signature":"%s","line_num":%s,"line_summary":"%s"}\n' \
            "$TS" "$(basename "$log")" "$pane" "$sig" "$linenum" "$safe_line" \
            >> "$ERRORS"
    done
done

# Aggregate from nightly-failures (one entry per file — failures are pre-aggregated upstream)
for fail in "${VAULT}"/_state/nightly-failures/*.log "${VAULT}"/_state/nightly-failures/*.md; do
    [ -f "$fail" ] || continue
    sig=$(shasum -a 256 < "$fail" | cut -c1-12)
    printf '{"ts":"%s","source_log":"nightly-failures/%s","error_signature":"%s","content_path":"%s"}\n' \
        "$TS" "$(basename "$fail")" "$sig" "$fail" \
        >> "$ERRORS"
done

# Aggregate from doctor-logs (only entries with status: failed or unhealthy)
for dlog in "${VAULT}"/_state/doctor-logs/*.json; do
    [ -f "$dlog" ] || continue
    if grep -q '"status".*"\(failed\|unhealthy\)"' "$dlog" 2>/dev/null; then
        sig=$(shasum -a 256 < "$dlog" | cut -c1-12)
        printf '{"ts":"%s","source_log":"doctor-logs/%s","error_signature":"%s","content_path":"%s"}\n' \
            "$TS" "$(basename "$dlog")" "$sig" "$dlog" \
            >> "$ERRORS"
    fi
done

# Count what we just wrote
new_count=$(grep -c "\"ts\":\"$TS\"" "$ERRORS" 2>/dev/null || echo 0)
echo "Aggregated $new_count error entries to $ERRORS"
