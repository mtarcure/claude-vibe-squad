---
name: dimensional-analysis-check
audience: specialist
description: "Use when numeric values cross arithmetic, API, storage, or time boundaries and a unit, scale, precision, rounding, signedness, or range mismatch could make the result wrong."
---

# Dimensional Analysis Check

Catch unit, scale, base, and precision errors by checking that every quantity's dimensions agree across an expression, an API boundary, and a storage round-trip.

## Steps
1. Inventory every numeric quantity the change touches and annotate each with its unit and scale: seconds vs milliseconds, bytes vs KiB, basis points vs percent vs fraction, token decimals, wei vs ether.
2. Check each arithmetic expression for dimensional consistency — added terms must share a unit, and a ratio's unit must be what the consumer expects.
3. Check every boundary crossing: function parameters, JSON fields, database columns, environment variables, and RPC payloads are where units silently change identity.
4. Verify conversion factors against the authoritative definition rather than an inline literal, and flag every magic constant that encodes a unit conversion.
5. Check precision and rounding: integer division truncation, float accumulation in loops, and fixed-point scaling applied twice or not at all.
6. Check signedness and range: values that can go negative, counters that can wrap, and durations that can exceed the field's width.
7. Check time explicitly — epoch vs monotonic, UTC vs local, inclusive vs exclusive interval bounds — as it is the most common dimensional defect.
8. Where a unit is only documented in a name, treat the name as an assertion to verify, not as evidence.

## Acceptance
- Every quantity in the reviewed change has a stated unit and scale.
- Each expression and each boundary crossing is dimensionally consistent, or the mismatch is reported.
- Conversion constants are traced to an authoritative definition.
- Rounding, truncation, overflow, and sign behavior are checked at the extremes, not just at typical values.
- Time values state their epoch, zone, and interval bound convention.
