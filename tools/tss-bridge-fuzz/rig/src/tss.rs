//! The signing oracle. This is the reason the rig exists.
//!
//! A coverage fuzzer without a signing oracle spends its whole budget bouncing
//! off signature verification: every generated payload fails at the auth check,
//! so the post-signature state space is never entered. Holding the TSS key lets
//! the fuzzer mint the signature a legitimate relayer would have carried, and
//! then mutate everything *after* the signature.
//!
//! The oracle is target-agnostic. What varies per bridge is the *pre-image
//! layout* the on-chain verifier hashes — that lives in the target adapter's
//! `tss_preimage`, not here.

use sha3::{Digest, Keccak256};

pub fn keccak(data: &[u8]) -> [u8; 32] {
    let mut h = Keccak256::new();
    h.update(data);
    let out = h.finalize();
    let mut r = [0u8; 32];
    r.copy_from_slice(&out);
    r
}

/// A secp256k1 ECDSA signer standing in for the bridge's threshold-signature
/// committee. Deterministic from a seed so any crashing input replays exactly.
pub struct TssOracle {
    sk: libsecp256k1::SecretKey,
    /// keccak256(uncompressed pubkey[1..])[12..32] — the 20-byte Ethereum-style
    /// address most bridges store on-chain as the TSS identity.
    pub eth_address: [u8; 20],
}

/// The three bytes an SVM `secp256k1_recover` verifier needs.
#[derive(Clone, Debug)]
pub struct TssSignature {
    pub message_hash: [u8; 32],
    pub signature: [u8; 64],
    pub recovery_id: u8,
}

impl TssOracle {
    pub fn from_seed(seed: [u8; 32]) -> Self {
        // Reject the (vanishingly unlikely) invalid scalar by nudging it.
        let mut raw = seed;
        let sk = loop {
            match libsecp256k1::SecretKey::parse(&raw) {
                Ok(k) => break k,
                Err(_) => raw[31] = raw[31].wrapping_add(1),
            }
        };
        let pubk = libsecp256k1::PublicKey::from_secret_key(&sk);
        let ser = pubk.serialize(); // 65 bytes: 0x04 || X || Y
        let h = keccak(&ser[1..]);
        let mut eth_address = [0u8; 20];
        eth_address.copy_from_slice(&h[12..32]);
        TssOracle { sk, eth_address }
    }

    /// Sign a pre-image the target adapter assembled.
    pub fn sign(&self, preimage: &[u8]) -> TssSignature {
        let message_hash = keccak(preimage);
        self.sign_prehashed(message_hash)
    }

    pub fn sign_prehashed(&self, message_hash: [u8; 32]) -> TssSignature {
        let msg = libsecp256k1::Message::parse(&message_hash);
        let (sig, rid) = libsecp256k1::sign(&msg, &self.sk);
        TssSignature {
            message_hash,
            signature: sig.serialize(),
            recovery_id: rid.serialize(),
        }
    }

    /// A structurally valid signature from a key the bridge does not know.
    ///
    /// This is the rig's built-in negative control. `authorize=false` calls use
    /// it so that "the fuzzer got in" can be distinguished from "auth is
    /// broken": if these succeed on a TSS-gated instruction, that is a finding,
    /// not coverage.
    pub fn forge(&self, preimage: &[u8], forger_seed: u8) -> TssSignature {
        let mut raw = [0x5Au8; 32];
        raw[0] = forger_seed | 1;
        let other = TssOracle::from_seed(raw);
        other.sign(preimage)
    }

    pub fn eth_hex(&self) -> String {
        self.eth_address
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    }
}
