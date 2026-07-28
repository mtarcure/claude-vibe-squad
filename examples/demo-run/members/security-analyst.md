specialist: security-analyst
status: completed
summary: apply_promo() in billing/promo.py builds its SQL by string-formatting the caller-supplied promo_code straight into the query, a classic SQL injection that also enables arbitrary discount manipulation.
claims:
  - finding: SQL injection — promo_code is interpolated into the query via Python % formatting instead of a bound parameter, so any attacker-controlled promo code is executed as SQL.
    severity: critical
    evidence: ["billing/promo.py apply_promo() line 16", "query built as \"SELECT percent_off FROM promos WHERE code = '%s'\" % promo_code"]
    confidence: high
    fix: Use a parameterized query — cur.execute("SELECT percent_off FROM promos WHERE code = ?", (promo_code,)) — and never string-format untrusted input into SQL.
  - finding: Unbounded trust in the returned percent_off — the discount is applied with no validation, so a hostile or corrupted value (e.g. injected via the SQLi above, or >100 / negative) directly manipulates the charged price.
    severity: medium
    evidence: ["billing/promo.py apply_promo() lines 22-24", "percent_off used directly in cart_total * percent_off / 100 with no range check"]
    confidence: medium
    fix: Validate percent_off is a number within [0, 100] before applying it and reject or clamp anything outside that range.
disagreements: []
tools_used: []
artifacts: []
limitations:
  - Reviewed the single 24-line function in isolation; callers, the promos schema, and how promo_code is sourced upstream were not in scope, so real-world exploitability of the injection depends on how this function is reached.
