//! The account world: everything Mollusk needs handed to it, plus a
//! fuzzer-addressable roster.

use {
    solana_account::Account, solana_pubkey::Pubkey,
    std::collections::{BTreeMap, HashMap},
};

pub const SYSTEM_PROGRAM: Pubkey = solana_sdk_ids::system_program::ID;

/// Solana rent, computed rather than depended upon: `(128 + len) * 3480 * 2`.
/// Reproduces the runtime's 890_880 for 0 bytes and 946_560 for 8 bytes.
#[derive(Clone, Copy, Debug)]
pub struct RentModel {
    pub lamports_per_byte_year: u64,
    pub exemption_threshold_x2: u64,
}

impl Default for RentModel {
    fn default() -> Self {
        RentModel {
            lamports_per_byte_year: 3480,
            exemption_threshold_x2: 2,
        }
    }
}

impl RentModel {
    pub fn minimum_balance(&self, data_len: usize) -> u64 {
        (128 + data_len as u64) * self.lamports_per_byte_year * self.exemption_threshold_x2
    }
}

#[derive(Default)]
pub struct World {
    pub accounts: HashMap<Pubkey, Account>,
    /// Named, fuzzer-addressable account slots. A mutated byte picks a slot,
    /// so the fuzzer substitutes *plausible* accounts (an attacker's ATA, a
    /// non-canonical token account, the vault) instead of random keys that can
    /// only ever produce `AccountNotFound`.
    pub roster: Vec<(String, Pubkey)>,
    pub rent: RentModel,
}

impl World {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set(&mut self, key: Pubkey, account: Account) {
        self.accounts.insert(key, account);
    }

    pub fn owned(&mut self, key: Pubkey, owner: Pubkey, data: Vec<u8>, lamports: u64) {
        self.set(
            key,
            Account {
                lamports,
                data,
                owner,
                executable: false,
                rent_epoch: u64::MAX,
            },
        );
    }

    pub fn fund(&mut self, key: Pubkey, lamports: u64) {
        self.owned(key, SYSTEM_PROGRAM, vec![], lamports);
    }

    pub fn get(&self, key: &Pubkey) -> Option<&Account> {
        self.accounts.get(key)
    }

    pub fn lamports(&self, key: &Pubkey) -> u64 {
        self.accounts.get(key).map(|a| a.lamports).unwrap_or(0)
    }

    /// SPL token account amount (bytes 64..72), 0 if absent or too short.
    pub fn token_amount(&self, key: &Pubkey) -> u64 {
        self.accounts
            .get(key)
            .filter(|a| a.data.len() >= 72)
            .map(|a| u64::from_le_bytes(a.data[64..72].try_into().unwrap()))
            .unwrap_or(0)
    }

    pub fn register(&mut self, label: &str, key: Pubkey) {
        self.roster.push((label.to_string(), key));
    }

    /// Fuzzer-facing selection: any byte maps onto a registered account.
    pub fn pick(&self, idx: u8) -> Pubkey {
        self.roster[idx as usize % self.roster.len()].1
    }

    pub fn pick_labeled(&self, idx: u8) -> &(String, Pubkey) {
        &self.roster[idx as usize % self.roster.len()]
    }

    /// A stable snapshot of tracked balances, for invariant deltas.
    pub fn balances(&self, keys: &[(&str, Pubkey)]) -> BTreeMap<String, u64> {
        keys.iter()
            .map(|(n, k)| (n.to_string(), self.lamports(k)))
            .collect()
    }
}
