# cosmos-sdk-audit-checklist

Known critical-bug classes for Cosmos-SDK / CometBFT chains and appchains. Run every item against custom modules (`x/*`), the app wiring (`app/`), and the ante chain. These are the classes that halt chains or move funds.

## Non-determinism → consensus fork/halt (the #1 Cosmos class)
Any code reached in consensus (`DeliverTx`, `BeginBlock`, `EndBlock`, msg handlers, `ValidateBasic`) MUST be deterministic across nodes. Grep for:
- **Map iteration** without sorted keys (`for k := range someMap` that affects state/events) → nodes diverge.
- **`time.Now()` / wall-clock** instead of `ctx.BlockTime()` in a state-affecting path (telemetry/queries are fine; state is not).
- **`math/rand`**, goroutine/scheduling-dependent order, floating point, `os`/env/filesystem reads, non-deterministic serialization.
- Iterating a `sdk.Context` store and mutating during iteration.

## Begin/EndBlocker panics → chain halt
`Begin/EndBlock` panics are NOT recovered (unlike `DeliverTx`). Any panic reachable from permissionless state (a delegation, a zero-power validator, a division, a `LegacyNewDecFromStr` on attacker-influenced input, an out-of-range slice) = a chain halt. Audit every division/decimal/slice/`MustXxx` in ABCI paths for a reachable panic. (Historical: x/group EndBlock zero-tally error — GHSA-47ww.)

## Unmetered / unbounded functions → DoS
EndBlocker or msg handlers that do work proportional to unbounded state (a list an attacker can grow cheaply: pending items, ballots, groups, gasless accounts) → sustained griefing / slowdown / halt. Check every loop over a growable collection for gas metering + a bound.

## AnteHandler bypass
- Nested/inner messages (authz `MsgExec`, group proposals, ICA) that skip the ante checks applied to top-level msgs — recursion must re-classify (fee, sig, gas) on inner msgs.
- Gasless / fee-abstraction whitelists: does a "free" path let an attacker execute value-moving msgs or grow state for free? Does account-init verify the signer's sig before bypassing later sig decorators?
- Sequence/nonce ordering and replay across the ante.

## authz / module authorization
- Historical authz bypasses (Elderflower/Jackfruit) enabling inflation/theft — confirm every `Msg*` handler enforces the correct signer/authority (gov module account, admin param). Registry/config mutations especially.
- `x/group`, `x/gov`, ICA, IBC packet-forward / rate-limit / wasm composition — audit the interaction, not just each module alone.

## Fund/decimal precision
Token conversion, reward division (F1 distribution), fee/refund math — check extrema, rounding direction, and over/underflow (`G115`-style uint conversions in HAND-WRITTEN code; generated `*.pulsar.go` conversions are false positives).

## Dependencies (always)
Run `osv-scanner --lockfile go.mod` + check cometbft/cosmos-sdk/ibc versions against published GHSAs/ASAs — a shipped-vulnerable consensus dep with a reachable in-scope impact is a real finding (though often dedup-dead / "known"; see [[known-advisory-backport-check]]). Note: `govulncheck` needs a buildable module.

## Tools
`gosec -severity=medium ./...`, `staticcheck ./...`, `semgrep --config=p/gosec --config=p/golang`, `osv-scanner`, `go test -race` for concurrency, native `go test -fuzz` for parsers. Related: [[cross-chain-bridge-audit]] for the interop layer.
