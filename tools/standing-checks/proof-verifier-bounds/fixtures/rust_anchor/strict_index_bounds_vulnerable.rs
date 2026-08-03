#![allow(dead_code)]

#[derive(Clone)]
pub struct Leaf {
    pub index: usize,
    pub data: Vec<u8>,
}

fn fold_hash(index_bytes: &[u8], data: &[u8], proof: u64) -> u64 {
    index_bytes
        .iter()
        .chain(data.iter())
        .fold(proof, |state, byte| state.rotate_left(5) ^ u64::from(*byte))
}

fn fold_value_only(data: &[u8], proof: u64) -> u64 {
    data.iter()
        .fold(proof, |state, byte| state.rotate_left(5) ^ u64::from(*byte))
}

pub fn verify(proof: &[u64], leaves: &[Leaf], leaf_count: usize) -> Result<u64, &'static str> {
    if leaf_count == 0 || leaves.is_empty() || proof.is_empty() {
        return Err("empty input");
    }

    // Deliberately omitted: per-leaf index bounds.

    for i in 1..leaves.len() {
        if leaves[i].index <= leaves[i - 1].index {
            return Err("non-canonical leaves");
        }
    }

    let mut leaf_pos = 0usize;
    let mut proof_pos = 0usize;
    let mut root = 0u64;
    while leaf_pos < leaves.len() && proof_pos < proof.len() {
        let index_bytes = leaves[leaf_pos].index.to_le_bytes();
        root ^= fold_hash(&index_bytes, &leaves[leaf_pos].data, proof[proof_pos]);
        leaf_pos += 1;
        proof_pos += 1;
    }

    if leaf_pos != leaves.len() {
        return Err("unconsumed leaves");
    }
    if proof_pos != proof.len() {
        return Err("unconsumed proof");
    }
    Ok(root)
}

