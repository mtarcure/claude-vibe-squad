//! The adapter surface. Everything target-specific lives behind `TargetSpec`;
//! pointing the rig at a new TSS bridge means writing one impl, not editing the
//! engine.

use {
    crate::{signers::SignerPool, tss::TssOracle, world::World},
    arbitrary::Arbitrary,
    solana_instruction::Instruction,
    solana_pubkey::Pubkey,
};

/// One fuzzer-driven call. The field set is deliberately bridge-shaped: every
/// TSS bridge has a caller, an amount, a deadline, a replay nonce, some account
/// choices and a payload. `authorize` is the switch that makes the rig a
/// post-signature fuzzer rather than an auth-bouncer.
#[derive(Arbitrary, Debug, Clone)]
pub struct FuzzCall {
    /// Selects the instruction, modulo `TargetSpec::kinds().len()`.
    pub kind: u8,
    /// Selects the calling identity from the signer pool.
    pub signer: u8,
    /// Mint a genuine TSS signature (true) or carry one from a key the bridge
    /// does not know (false — the built-in negative control).
    pub authorize: bool,
    pub amount: u64,
    pub deadline_delta: i32,
    /// Replay-nonce material (sub_tx_id / message id).
    pub nonce: [u8; 8],
    /// Indices into `World::roster`.
    pub picks: [u8; 6],
    pub flags: u16,
    pub blob: Vec<u8>,
}

#[derive(Arbitrary, Debug, Clone)]
pub struct FuzzSession {
    pub calls: Vec<FuzzCall>,
}

/// What the adapter hands back for one call.
pub struct Plan {
    /// Index into `TargetSpec::kinds()`.
    pub kind: usize,
    /// Whether this instruction carries a signature the bridge should accept.
    pub authorized: bool,
    pub instruction: Instruction,
}

pub struct SeedCtx<'a> {
    pub world: &'a mut World,
    pub tss: &'a TssOracle,
    pub signers: &'a SignerPool,
    pub program_id: Pubkey,
    pub now: i64,
}

pub struct BuildCtx<'a> {
    pub world: &'a World,
    pub tss: &'a TssOracle,
    pub signers: &'a SignerPool,
    pub program_id: Pubkey,
    pub now: i64,
}

/// A property the rig re-checks after every successful call.
pub struct Invariant {
    pub name: &'static str,
    pub holds: bool,
    pub detail: String,
}

impl Invariant {
    pub fn ok(name: &'static str) -> Self {
        Invariant {
            name,
            holds: true,
            detail: String::new(),
        }
    }
    pub fn violated(name: &'static str, detail: impl Into<String>) -> Self {
        Invariant {
            name,
            holds: false,
            detail: detail.into(),
        }
    }
}

/// Implement this once per bridge. Nothing else in the rig changes.
pub trait TargetSpec {
    fn name(&self) -> &'static str;

    /// The address the program is deployed at. For Anchor programs this MUST be
    /// the `declare_id!` value: `anchor build` writes a fresh keypair that never
    /// matches it, so loading the ELF anywhere else makes every PDA wrong.
    fn program_id(&self) -> Pubkey;

    /// Raw SBF ELF bytes.
    fn elf(&self) -> Vec<u8>;

    /// Human names for each instruction kind, in index order.
    fn kinds(&self) -> &'static [&'static str];

    /// Per-kind: does this instruction verify a TSS signature? The rig asserts
    /// that an unauthorized call to a gated kind never succeeds.
    fn tss_gated(&self) -> &'static [bool];

    /// Register the identities the target's seeded state grants roles to.
    /// Called before `seed`.
    fn register_signers(&self, pool: &mut SignerPool);

    /// Install config / PDA / oracle accounts directly, modelling real
    /// post-deployment state. Direct seeding is not a privilege the attacker
    /// holds — it is the state a live deployment is already in.
    fn seed(&self, cx: &mut SeedCtx);

    /// Turn a fuzzer call into a concrete instruction, or `None` if this call
    /// cannot be rendered (the rig counts those separately so a spec that
    /// silently drops everything cannot look like a clean run).
    fn build(&self, call: &FuzzCall, cx: &BuildCtx) -> Option<Plan>;

    /// Properties re-checked after every successful call.
    fn invariants(&self, world: &World) -> Vec<Invariant> {
        let _ = world;
        Vec::new()
    }
}
