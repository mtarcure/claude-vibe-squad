//! `AccountsStorage<Keypair>` — the stateful signer pool.
//!
//! Trident's insight, kept: a fuzzer that invents a fresh random pubkey for
//! every call never satisfies a `has_one` / `Signer` constraint, so auth-gated
//! instructions are bounced instead of reached. The pool holds a small, stable
//! set of identities the fuzzer addresses *by index*, so a mutated byte swaps
//! the caller between admin, relayer and a role-less attacker rather than
//! producing an unrelated key that can never be right.
//!
//! Every identity is derived deterministically from a seed, so a libFuzzer
//! artifact replays to byte-identical pubkeys.

use {ed25519_dalek::SigningKey, solana_pubkey::Pubkey, std::collections::HashMap};

#[derive(Clone, Debug)]
pub struct PoolSigner {
    pub label: String,
    pub pubkey: Pubkey,
    /// ed25519 secret seed. Mollusk does not verify transaction signatures
    /// (it executes a single instruction, where `is_signer` is a flag), but the
    /// seed is kept so the same pool drives a LiteSVM or validator backend.
    pub secret: [u8; 32],
    /// True if the target's seeded state grants this identity a role
    /// (admin / operator / pauser / …). The rig uses this to build honest
    /// "role-less actor" claims.
    pub privileged: bool,
}

impl PoolSigner {
    pub fn signing_key(&self) -> SigningKey {
        SigningKey::from_bytes(&self.secret)
    }
}

#[derive(Default)]
pub struct SignerPool {
    entries: Vec<PoolSigner>,
    by_label: HashMap<String, usize>,
}

impl SignerPool {
    pub fn new() -> Self {
        Self::default()
    }

    /// Deterministically derive and register an identity.
    pub fn insert(&mut self, label: &str, seed_byte: u8, privileged: bool) -> Pubkey {
        let mut secret = [0u8; 32];
        secret[0] = seed_byte;
        for (i, b) in label.as_bytes().iter().take(31).enumerate() {
            secret[i + 1] = *b;
        }
        let sk = SigningKey::from_bytes(&secret);
        let pubkey = Pubkey::new_from_array(sk.verifying_key().to_bytes());
        let idx = self.entries.len();
        self.entries.push(PoolSigner {
            label: label.to_string(),
            pubkey,
            secret,
            privileged,
        });
        self.by_label.insert(label.to_string(), idx);
        pubkey
    }

    pub fn get(&self, label: &str) -> &PoolSigner {
        let idx = self.by_label[label];
        &self.entries[idx]
    }

    pub fn key(&self, label: &str) -> Pubkey {
        self.get(label).pubkey
    }

    /// Fuzzer-facing selection: any byte maps onto a real identity.
    pub fn pick(&self, idx: u8) -> &PoolSigner {
        &self.entries[idx as usize % self.entries.len()]
    }

    /// Fuzzer-facing selection restricted to identities holding no role.
    pub fn pick_roleless(&self, idx: u8) -> &PoolSigner {
        let roleless: Vec<&PoolSigner> = self.entries.iter().filter(|e| !e.privileged).collect();
        roleless[idx as usize % roleless.len()]
    }

    pub fn all(&self) -> &[PoolSigner] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}
