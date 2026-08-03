//! Byte builder for hand-encoding Anchor/borsh instruction data and account
//! state. Target-agnostic: bridges differ in *which* fields they pack, not in
//! how borsh packs them.

use solana_pubkey::Pubkey;

#[derive(Default, Clone)]
pub struct Buf(pub Vec<u8>);

impl Buf {
    pub fn new() -> Self {
        Buf(Vec::new())
    }
    pub fn b(mut self, x: &[u8]) -> Self {
        self.0.extend_from_slice(x);
        self
    }
    pub fn u8(mut self, x: u8) -> Self {
        self.0.push(x);
        self
    }
    pub fn u16(mut self, x: u16) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn u32(mut self, x: u32) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn u64(mut self, x: u64) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn i32(mut self, x: i32) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn i64(mut self, x: i64) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn u128(mut self, x: u128) -> Self {
        self.0.extend_from_slice(&x.to_le_bytes());
        self
    }
    pub fn key(self, k: &Pubkey) -> Self {
        self.b(k.as_ref())
    }
    /// borsh `Vec<u8>`: u32 LE length prefix.
    pub fn vecu8(mut self, v: &[u8]) -> Self {
        self.0.extend_from_slice(&(v.len() as u32).to_le_bytes());
        self.0.extend_from_slice(v);
        self
    }
    /// borsh `String`: u32 LE length prefix.
    pub fn string(mut self, s: &str) -> Self {
        self.0.extend_from_slice(&(s.len() as u32).to_le_bytes());
        self.0.extend_from_slice(s.as_bytes());
        self
    }
    /// Zero-pad an account buffer out to its declared `LEN`.
    pub fn pad_to(mut self, n: usize) -> Self {
        while self.0.len() < n {
            self.0.push(0);
        }
        self
    }
    pub fn done(self) -> Vec<u8> {
        self.0
    }
}

/// Anchor's 8-byte discriminator: first 8 bytes of sha256 of a namespaced name.
pub fn anchor_disc(namespace: &str, name: &str) -> [u8; 8] {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(format!("{namespace}:{name}").as_bytes());
    let out = h.finalize();
    let mut r = [0u8; 8];
    r.copy_from_slice(&out[..8]);
    r
}

pub fn ix_disc(name: &str) -> [u8; 8] {
    anchor_disc("global", name)
}

pub fn acct_disc(name: &str) -> [u8; 8] {
    anchor_disc("account", name)
}
