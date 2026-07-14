# Panel review — `apply_promo()` in `billing/promo.py`

*Two specialist reviewers examined this change in parallel; a coordinator then synthesized their independent findings into this single report.*

**Panel members:** Code Reviewer · Security Analyst  **Coordinator:** Synthesizer

---

## The change under review

A 24-line `apply_promo(cart_total, promo_code, conn)` that looks up a promo code's percentage discount in a SQLite `promos` table and returns the discounted cart total.

## Verdict: **Changes needed before merge**

Two blocking defects — one security-critical, one a correctness bug — plus four quality issues. Notably, the two reviewers arrived **independently at the same top fix** (parameterize the query) from opposite directions: one as a security vulnerability, the other as a correctness break.

## Consensus — flagged by both reviewers

| Finding | Severity | Why it matters |
|---|---|---|
| Untrusted `promo_code` is string-formatted directly into the SQL | **Critical** (security) — and a correctness break | Attacker-controlled input is executed as SQL; even benign codes containing a quote break the query |
| `percent_off` from the row is applied with no bounds check | **High** (correctness) / **Medium** (security) | An out-of-range value (>100, negative, or hostile) silently produces a wrong — even negative — charge |

## Security Analyst — findings

1. **SQL injection (Critical).** `apply_promo()` builds its query as `"SELECT percent_off FROM promos WHERE code = '%s'" % promo_code`, formatting the caller-supplied `promo_code` straight into the SQL instead of binding it. Any attacker-controlled promo code is executed as SQL.
   *Fix:* use a parameterized query — `cur.execute("SELECT percent_off FROM promos WHERE code = ?", (promo_code,))` — and never string-format untrusted input into SQL.
2. **Unbounded trust in `percent_off` (Medium).** The discount is applied with no validation, so a hostile or corrupted value (including one reachable via the injection above) directly manipulates the charged price.
   *Fix:* validate that `percent_off` is a number within `[0, 100]` before applying it; reject or clamp anything outside that range.

## Code Reviewer — findings

1. **Discount not bounds-checked → negative or inflated total (High).** A row with `percent_off > 100` (or a negative value) drives the returned total below zero or above the original, a silent over/undercharge.
   *Fix:* clamp `percent_off` to `[0, 100]` (or reject out-of-range rows) and clamp the result with `max(0.0, cart_total - discount)`.
2. **Float money, returned unrounded (Medium).** Monetary math on `float` produces long fractional tails (e.g. a 9.99 total at 15% off) and accumulates rounding error.
   *Fix:* represent money with `decimal.Decimal` (or integer cents) and round to currency precision (2 dp) before returning.
3. **NULL `percent_off` raises `TypeError` (Medium).** `row[0]` is fed straight into arithmetic; if the column is `NULL`, `cart_total * None` crashes rather than degrading gracefully.
   *Fix:* guard for a `None` discount (treat as no discount, or raise a clear domain error).
4. **Cursor is never closed (Low).** `conn.cursor()` leaks a cursor on every call for long-lived connections.
   *Fix:* wrap it in `contextlib.closing()` / a `with` block, or close it in a `finally`.
5. **Unknown code and a genuine 0%-off code are indistinguishable (Low).** Both silently return the unchanged total, so callers can't detect an invalid code.
   *Fix:* return a richer result (an `applied` flag or the discount amount), or raise a `PromoNotFound`.

## Where the reviewers converged and differed

- **Converged:** both independently recommended the **parameterized query** as the top fix — the Security Analyst to close the injection, the Code Reviewer because the string-formatted query also breaks on any code containing a quote. One change resolves both findings.
- **Differed (in framing, not in substance):** the missing discount validation was rated **High** through a correctness lens (negative totals) and **Medium** through a security lens (price manipulation). There is no conflict — the union view is to treat it as **High**, since it is both a concrete correctness bug and a security exposure.

## Recommended fix order

1. **Parameterize the query** — `cur.execute("SELECT percent_off FROM promos WHERE code = ?", (promo_code,))`. Closes the **Critical** injection *and* the quote-character correctness break in one change.
2. **Validate/clamp `percent_off`** to `[0, 100]` and clamp the returned total to `≥ 0`. Closes the **High** correctness bug and blunts price manipulation.
3. **Use `Decimal`** (or integer cents) and round to 2 dp for the monetary result.
4. **Handle a `NULL` `percent_off`** explicitly.
5. **Close the cursor** with a context manager or `finally`.
6. **Distinguish an unknown code** from a genuine 0%-off code in the return value.

---

*How this report was produced: the two reviews above ran concurrently as independent specialists; the coordinator collected both returns, preserved each reviewer's distinct findings and severities, reconciled the one overlapping issue, and produced this single synthesized result.*
