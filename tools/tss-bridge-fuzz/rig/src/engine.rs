//! The Mollusk-backed execution engine.
//!
//! Mollusk is used rather than LiteSVM or `solana-test-validator` for three
//! reasons that matter to a fuzzer specifically:
//!
//!   1. No `AccountsDB`/`Bank`, so no blockhash and no transaction dedup. Two
//!      byte-identical calls both reach the program. A LiteSVM harness reports
//!      the second as `AlreadyProcessed`, which is the *runtime* deduplicating
//!      — it says nothing about the program's own replay guard, and a harness
//!      that mistakes one for the other reports a guard it never tested.
//!   2. Instruction-level entry, so a generated call costs a program execution
//!      and nothing else. This is what makes `cargo-fuzz` iteration rates
//!      usable.
//!   3. It resolves as a plain dependency. `solana-test-validator` cannot bind
//!      a faucet in-sandbox ("Operation not permitted"), and Trident's Solana
//!      dependency conflict is what produced a scaffold that executed 0 calls.

use {
    crate::{
        ledger::Ledger,
        signers::SignerPool,
        spec::{BuildCtx, FuzzCall, FuzzSession, SeedCtx, TargetSpec},
        tss::TssOracle,
        world::World,
    },
    mollusk_svm::{program::loader_keys::LOADER_V3, Mollusk},
    solana_account::Account,
    solana_instruction::Instruction,
    solana_pubkey::Pubkey,
};

pub struct Engine<S: TargetSpec> {
    pub mollusk: Mollusk,
    pub spec: S,
    pub world: World,
    pub tss: TssOracle,
    pub signers: SignerPool,
    pub ledger: Ledger,
    call_index: u64,
}

pub struct CallOutcome {
    pub kind: String,
    pub authorized: bool,
    pub ok: bool,
    pub result: String,
    pub compute_units: u64,
}

impl<S: TargetSpec> Engine<S> {
    /// Build a fresh engine: load the ELF, derive the TSS key, register the
    /// signer pool, seed the world.
    pub fn new(spec: S, tss_seed: [u8; 32]) -> Self {
        let program_id = spec.program_id();
        let elf = spec.elf();

        let mut mollusk = Mollusk::default();
        mollusk.add_program_with_loader_and_elf(&program_id, &LOADER_V3, &elf);

        let tss = TssOracle::from_seed(tss_seed);
        let mut signers = SignerPool::new();
        spec.register_signers(&mut signers);

        let mut world = World::new();
        let now = mollusk.sysvars.clock.unix_timestamp;
        {
            let mut cx = SeedCtx {
                world: &mut world,
                tss: &tss,
                signers: &signers,
                program_id,
                now,
            };
            spec.seed(&mut cx);
        }

        Engine {
            mollusk,
            spec,
            world,
            tss,
            signers,
            ledger: Ledger::default(),
            call_index: 0,
        }
    }

    pub fn now(&self) -> i64 {
        self.mollusk.sysvars.clock.unix_timestamp
    }

    /// Execute one instruction against the current world, committing resulting
    /// accounts only on success (a failed call must not corrupt the state the
    /// next call explores).
    pub fn execute(&mut self, ix: &Instruction) -> (bool, String, u64) {
        let mut accounts: Vec<(Pubkey, Account)> = Vec::with_capacity(ix.accounts.len() + 1);
        let mut seen = std::collections::HashSet::new();
        for meta in &ix.accounts {
            if seen.insert(meta.pubkey) {
                let acct = self
                    .world
                    .get(&meta.pubkey)
                    .cloned()
                    .unwrap_or_else(Account::default);
                accounts.push((meta.pubkey, acct));
            }
        }

        let result = self.mollusk.process_instruction(ix, &accounts);
        let ok = result.program_result.is_ok();
        if ok {
            for (pubkey, account) in result.resulting_accounts.iter() {
                self.world.set(*pubkey, account.clone());
            }
        }
        let rendered = match &result.raw_result {
            Ok(()) => "Ok".to_string(),
            Err(e) => format!("{e:?}"),
        };
        (ok, rendered, result.compute_units_consumed)
    }

    /// Render and run one fuzzer call, updating the ledger.
    pub fn run_call(&mut self, call: &FuzzCall) -> Option<CallOutcome> {
        let now = self.now();
        let plan = {
            let cx = BuildCtx {
                world: &self.world,
                tss: &self.tss,
                signers: &self.signers,
                program_id: self.spec.program_id(),
                now,
            };
            self.spec.build(call, &cx)
        };

        let Some(plan) = plan else {
            self.ledger.record_unbuildable();
            self.call_index += 1;
            return None;
        };

        let kind = self.spec.kinds()[plan.kind].to_string();
        let gated = self.spec.tss_gated()[plan.kind];
        let (ok, rendered, cu) = self.execute(&plan.instruction);

        self.ledger.record(
            &kind,
            plan.authorized,
            gated,
            ok,
            if ok { None } else { Some(rendered.clone()) },
            cu,
            self.call_index,
        );

        if ok {
            for inv in self.spec.invariants(&self.world) {
                if !inv.holds {
                    self.ledger
                        .violations
                        .push((self.call_index, inv.name.to_string(), inv.detail));
                }
            }
        }

        self.call_index += 1;
        Some(CallOutcome {
            kind,
            authorized: plan.authorized,
            ok,
            result: rendered,
            compute_units: cu,
        })
    }

    pub fn run_session(&mut self, session: &FuzzSession) {
        for call in &session.calls {
            self.run_call(call);
        }
    }

    /// The false twin. Runs the same session with every signature forged, so
    /// the pair answers "is the depth bought by the signing oracle, or is the
    /// bridge's auth simply not checked?". A rig whose authorized and
    /// unauthorized runs succeed equally often has not proved anything.
    pub fn run_session_deauthorized(&mut self, session: &FuzzSession) {
        for call in &session.calls {
            let mut c = call.clone();
            c.authorize = false;
            self.run_call(&c);
        }
    }

    pub fn report(&self) -> String {
        self.ledger.report(self.spec.kinds())
    }
}
