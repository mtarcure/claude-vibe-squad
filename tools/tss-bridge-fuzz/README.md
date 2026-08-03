# tss-bridge-fuzz

A reusable fuzzing rig for **TSS-signed Solana bridges**, built on
[Mollusk](https://github.com/anza-xyz/mollusk) (Anza, `mollusk-svm`).

## The premise

A coverage fuzzer pointed at a bridge **without a signing oracle spends its
entire budget bouncing off signature verification.** Every mutated payload fails
at the auth check, so the interesting region — the post-signature state space,
where replay guards, gas accounting, PDA lifecycle and CPI scope live — is never
entered.

This rig **holds the TSS key.** It mints the signature a legitimate relayer
would have carried, then mutates everything after it.

Holding the key is a lab device, not a claimed capability. The rig also keeps a
role-less identity that never holds a role, and a built-in forged-signature
negative control, so any claim about what an unprivileged actor can do is made
*with* the unprivileged actor.

## Why Mollusk

| | Mollusk | LiteSVM | `solana-test-validator` |
|---|---|---|---|
| Transaction dedup | none | **`AlreadyProcessed`** | yes |
| Setup cost per call | instruction only | tx + bank | RPC round trip |
| Runs in-sandbox | yes | yes | **no** — faucet cannot bind |
| `cargo-fuzz` + `arbitrary` | documented route | workable | no |

The dedup row is the one that bites. Under LiteSVM two byte-identical calls make
the *runtime* return `AlreadyProcessed` — a harness that reads that as "the
program's replay guard held" is reporting a guard it never tested. Mollusk has
no `Bank`, so every call reaches the program and you get the program's own
answer.

## Retargeting — what you must change

**One file: a `TargetSpec` impl.** Nothing in `rig/` knows about any particular
bridge. `targets/svm-gateway/src/lib.rs` is the worked example.

```
rig/                        target-agnostic — DO NOT edit to retarget
  spec.rs                   the TargetSpec trait + Arbitrary FuzzCall/FuzzSession
  tss.rs                    secp256k1 signing oracle + forged-signature control
  signers.rs                AccountsStorage<Keypair> — the stateful signer pool
  world.rs                  account store, fuzzer-addressable roster, rent model
  engine.rs                 Mollusk driver, state commit, invariant checks
  ledger.rs                 outcome accounting + the non-vacuity gate
  buf.rs                    borsh/Anchor byte builder
targets/<your-bridge>/      target-specific — this is what you write
fuzz/                       cargo-fuzz entry point (target-agnostic except the use line)
canary/                     proves Mollusk actually executes an ELF
```

To point the rig at a new bridge, implement these on your spec:

| Method | What it is |
|---|---|
| `program_id()` | the `declare_id!` value — **not** the keypair `anchor build` generates |
| `elf()` | raw `.so` bytes |
| `kinds()` | human names for each instruction, in index order |
| `tss_gated()` | per kind: does it verify a TSS signature? |
| `register_signers()` | the identities, and which ones the seeded state gives a role |
| `seed()` | config/PDA/oracle accounts + the fuzzer-addressable roster |
| `build()` | render a `FuzzCall` into an `Instruction` |
| `invariants()` | properties re-checked after every successful call |

### The three things that will cost you a day if you skip them

1. **`tss_preimage` must match the on-chain verifier byte for byte.** Get it
   wrong and every authorized call returns the auth error — which is
   indistinguishable from having no oracle at all. The smoke run's
   *authorized-success count* is the only proof the layout is right.
2. **Seed executable program accounts** for every program your instructions
   reference — system program, SPL token, and the target's own id (Anchor's
   `Option<Account>` ABI encodes `None` as "this slot holds the program id").
   Without them the runtime substitutes a non-executable stub and you get
   Anchor `3009 InvalidProgramExecutable` / runtime `UnsupportedProgramId`
   before any target logic runs.
3. **Bias the obvious kill-fields, keep a flag to unbias them.** A raw `i32`
   deadline delta is in the past half the time and burns the call on
   `SignatureExpired`. The adapter defaults to a valid window and restores the
   raw value under a flag bit, so expiry stays fuzzable without dominating.

## Building the target ELF

`anchor test` does **not** work: `anchor build` generates a local keypair that
never matches `declare_id!` and writes it into the IDL. Build the ELF directly
and load it at the **declared** id.

```bash
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"   # required
cargo-build-sbf --manifest-path <program>/Cargo.toml --sbf-out-dir ./.build/deploy
```

Without that `PATH` line Homebrew shadows the Agave install and `cargo-build-sbf`
exits 101.

**Verify the ELF matches the id you load it at.** Run the canary; a program
whose `declare_id!` differs returns Anchor `4100 DeclaredProgramIdMismatch`
instead of `101 InstructionFallbackNotFound`:

```bash
cargo run --release -p mollusk-canary --manifest-path canary/Cargo.toml -- <path/to/program.so>
```

## Running

```bash
# Deterministic smoke run — reports how many calls SUCCEEDED, and runs the
# false twin. Exits non-zero on a vacuous run.
cargo build --release
RUST_LOG=off ./target/release/smoke .build/deploy/universal_gateway.so 400

# libFuzzer campaign
TSS_BRIDGE_FUZZ_ELF=$PWD/.build/deploy/universal_gateway.so \
  cargo +nightly fuzz run tss_bridge --fuzz-dir fuzz --sanitizer=none -- -max_total_time=600

# What the campaign ACTUALLY reached (libFuzzer reports sessions, not successes)
RUST_LOG=off ./target/release/corpus-report \
  .build/deploy/universal_gateway.so fuzz/corpus/tss_bridge
```

`RUST_LOG=off` matters: Mollusk enables `solana_logger` by default, so a run
without it emits a program log line per instruction. Drop it when you want the
logs.

## The non-vacuity gate

A prior campaign reported **6.2 million "passing" calls with zero successful
calls** — a harness bouncing every input off an auth check, printed as a clean
run. A tool that silently failed to run and a tool that found nothing produce
the same empty output.

So this rig refuses to report a run as meaningful unless it can name:

* how many calls **SUCCEEDED** (not how many ran),
* how many **distinct instruction kinds** were reached — `covered N of M`,
* the split between calls carrying a **real** signature and a **forged** one.

`Vacuous` (0 successes) and `ORACLE DEAD` (successes, but none on a TSS-gated
instruction) both exit non-zero. `Partial` means some kinds were never reached
and is reported, not hidden.

**The false twin.** Every smoke run replays the same session with every
signature forged. If the armed and forged runs succeed equally often on gated
instructions, the depth is not coming from the oracle and the run says nothing.
This is the positive control for the harness itself.

## What counts as a lead

The fuzz target panics — so libFuzzer preserves the input — on:

* an **invariant violation** declared by the spec, or
* an **unauthorized call succeeding on a TSS-gated instruction** (`auth_bypasses`).

Both are leads, not findings. A lead becomes a finding only after a PoC
reproduces it with a `msg.sender`-equivalent swap control: the harness holds the
TSS key, so anything reproduced *with* the oracle armed must be re-shown with a
role-less actor before it means anything about an attacker.
