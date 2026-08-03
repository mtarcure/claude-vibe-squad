//! libFuzzer entry point.
//!
//! The corpus is a `FuzzSession` — a sequence of calls against ONE world, so
//! coverage comes from reachable state, not from a single isolated call.
//!
//!   TSS_BRIDGE_FUZZ_ELF=/path/to/program.so cargo +nightly fuzz run tss_bridge
//!
//! The oracle is armed: every `authorize=true` call carries a real TSS
//! signature, so libFuzzer's budget is spent on the post-signature state space
//! instead of on signature verification.

#![no_main]

use {
    libfuzzer_sys::fuzz_target,
    std::sync::OnceLock,
    target_svm_gateway::SvmGateway,
    tss_bridge_fuzz_rig::{Engine, FuzzSession},
};

static ELF: OnceLock<Vec<u8>> = OnceLock::new();

fn elf() -> &'static [u8] {
    ELF.get_or_init(|| {
        let path = std::env::var("TSS_BRIDGE_FUZZ_ELF")
            .expect("set TSS_BRIDGE_FUZZ_ELF to the program .so");
        std::fs::read(&path).unwrap_or_else(|e| panic!("read {path}: {e}"))
    })
}

fuzz_target!(|session: FuzzSession| {
    if session.calls.is_empty() || session.calls.len() > 64 {
        return;
    }
    let spec = SvmGateway {
        elf: elf().to_vec(),
        program_id: target_svm_gateway::PROGRAM_ID.parse().unwrap(),
        initial_vault_lamports: 100 * 1_000_000_000,
    };
    let mut engine = Engine::new(spec, [0x11; 32]);
    engine.run_session(&session);

    // An invariant violation or an unauthorized call landing on a TSS-gated
    // instruction is a lead. Panic so libFuzzer preserves the input.
    assert!(
        engine.ledger.violations.is_empty(),
        "invariant violated: {:?}",
        engine.ledger.violations
    );
    assert!(
        engine.ledger.auth_bypasses.is_empty(),
        "forged signature reached a TSS-gated instruction: {:?}",
        engine.ledger.auth_bypasses
    );
});
