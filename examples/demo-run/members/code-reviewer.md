specialist: code-reviewer
status: completed
summary: apply_promo() in billing/promo.py is functionally close but has one high-severity correctness gap (unvalidated discount percentage can drive the total negative) plus several robustness and maintainability issues around float money math, NULL handling, and cursor cleanup.
claims:
  - finding: percent_off from the database is applied without any bounds check, so a row with percent_off > 100 or a negative value yields a negative or inflated cart total (silent undercharge/overcharge).
    severity: high
    evidence: ["apply_promo() lines 22-24"]
    confidence: high
    fix: Clamp percent_off to the [0, 100] range (or reject out-of-range rows) and clamp the returned total with max(0.0, cart_total - discount).
  - finding: Monetary values use float and the discounted total is returned unrounded, so inputs like a 9.99 total at 15% off produce long fractional tails and accumulate rounding error across calls.
    severity: medium
    evidence: ["apply_promo() line 23", "apply_promo() signature line 11"]
    confidence: high
    fix: Represent money with decimal.Decimal (or integer cents) and round the result to currency precision (2 dp) before returning.
  - finding: row[0] is fed straight into arithmetic; if the percent_off column is NULL, cart_total * None raises TypeError at runtime rather than degrading gracefully.
    severity: medium
    evidence: ["apply_promo() lines 22-23"]
    confidence: medium
    fix: Guard for a None percent_off (treat NULL as no discount, or raise a clear domain error) before computing the discount.
  - finding: The cursor returned by conn.cursor() is never closed, leaking a cursor on every call for long-lived connections.
    severity: low
    evidence: ["apply_promo() line 13"]
    confidence: high
    fix: Wrap the cursor in contextlib.closing() / a with-block, or close it in a finally clause.
  - finding: An unknown or expired code and a legitimate 0%-off code are indistinguishable — both silently return the unchanged total — so callers cannot detect an invalid code.
    severity: low
    evidence: ["apply_promo() lines 19-20"]
    confidence: medium
    fix: Return a richer result (e.g. an applied flag or discount amount) or raise a PromoNotFound so callers can tell "no such code" from "0% discount".
  - finding: Building the SQL by string-formatting the code breaks the query on any code containing a single quote, raising an OperationalError (the injection risk itself is deferred to the security reviewer).
    severity: low
    evidence: ["apply_promo() lines 15-17"]
    confidence: high
    fix: Use a parameterized query — cur.execute("SELECT percent_off FROM promos WHERE code = ?", (promo_code,)) — which also removes the quote-character correctness break.
disagreements: []
tools_used: []
artifacts: []
limitations:
  - The promos table schema is not available, so column nullability and code uniqueness are inferred from usage rather than confirmed.
  - Whether returning the unchanged total for an unknown code is the intended contract is assumed, not specified.
