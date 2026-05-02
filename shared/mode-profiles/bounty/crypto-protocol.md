---
name: crypto-protocol
extends: bounty
status: active
---

# Bounty Profile: Cryptographic Protocol

For cryptographic implementation reviews — TLS libraries, signature schemes, key derivation, MPC, ZK protocols.

## Auto-detection signals

- Target is a cryptographic library (wolfSSL, OpenSSL, BoringSSL, libsodium, etc.)
- Bounty mentions cryptographic protocol implementation
- Files: crypto-related .c / .rs / .go in scope

## Phase customizations

### Phase 1 Intelligence
- Read protocol spec (RFC, paper, formal protocol description)
- Identify target's claimed properties (which RFC compliance, which threat model)

### Phase 2 Recon
- Map protocol surface (handshake states, message types)
- Identify cryptographic primitives used (which curves, which AEAD, which KDFs)
- Note any custom / non-standard variations

### Phase 3 Threat Modeling
- Side-channel attacks (timing, cache, fault injection)
- Implementation flaws (constant-time violations, signature malleability)
- Protocol-level (downgrade attacks, replay, ambiguity)
- Cross-protocol attacks (one protocol's signed message accepted in another)

### Phase 5/6/7 Exploitation
- Differential testing (fuzz vs reference impl)
- Property-based testing for crypto invariants
- Static analysis for constant-time properties (ctgrind, ct-fuzz)
- Symbolic execution where feasible (KLEE, angr)
- For chrono memory: `wolfssl-crypto-target-analysis` skill applies

### Phase 9 Validation
- Crypto vulns often Critical severity (root-of-trust failure)
- Reproducibility critical — reviewers need to re-run

### Phase 10 Report
- Include attack code + theoretical analysis
- Cite the spec section being violated
- Reference any prior known similar issues

## Specialists most active

- smart-contract-engineer (Coding) — surprisingly applicable for ZK / MPC analysis
- exploit-developer (multi-model)
- threat-modeler (deep — protocol-level threat models matter most here)
- skeptic (council-consensus mode for high-stakes crypto findings)

## Tools

- ctgrind, ct-fuzz (constant-time analysis)
- AFL++, libfuzzer (fuzzing)
- KLEE, angr (symbolic execution)
- ProVerif, Tamarin (protocol-level formal verification)
