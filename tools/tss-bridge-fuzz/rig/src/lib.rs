//! # tss-bridge-fuzz
//!
//! A target-agnostic fuzzing rig for TSS-signed Solana bridges, built on
//! Mollusk.
//!
//! The premise: a coverage fuzzer pointed at a bridge without a signing oracle
//! spends its entire budget bouncing off signature verification. Every mutated
//! payload fails at the auth check, so the interesting region — the
//! post-signature state space, where replay guards, accounting, PDA lifecycle
//! and CPI scope live — is never entered. This rig HOLDS the TSS key, mints the
//! signature a legitimate relayer would have carried, and mutates everything
//! after it.
//!
//! Holding the key is a lab device, not a claimed capability: the rig also
//! keeps a role-less identity that never signs, and a forged-signature negative
//! control, so any claim about what an unprivileged actor can do is made with
//! the unprivileged actor.
//!
//! Retargeting is one `TargetSpec` impl — see `README.md`.

pub mod buf;
pub mod engine;
pub mod ledger;
pub mod signers;
pub mod spec;
pub mod tss;
pub mod world;

pub use {
    engine::{CallOutcome, Engine},
    ledger::{Ledger, NonVacuityReport, Vacuity},
    signers::{PoolSigner, SignerPool},
    spec::{BuildCtx, FuzzCall, FuzzSession, Invariant, Plan, SeedCtx, TargetSpec},
    tss::{keccak, TssOracle, TssSignature},
    world::{RentModel, World, SYSTEM_PROGRAM},
};

/// Deterministic byte source, so the smoke run and any replay agree.
pub fn deterministic_bytes(seed: u64, len: usize) -> Vec<u8> {
    let mut state = seed | 1;
    let mut out = Vec::with_capacity(len);
    while out.len() < len {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        out.extend_from_slice(&state.to_le_bytes());
    }
    out.truncate(len);
    out
}
