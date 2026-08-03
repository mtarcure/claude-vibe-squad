// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract ProofVerifierControl {
    struct Leaf {
        uint256 index;
        bytes data;
    }

    error EmptyInput();
    error LeafIndexOutOfBounds();
    error NonCanonicalLeaves();
    error UnconsumedLeaves();
    error UnconsumedProof();

    function verify(bytes32[] memory proof, Leaf[] memory leaves, uint256 leafCount)
        external
        pure
        returns (bytes32 root)
    {
        if (leafCount == 0 || leaves.length == 0 || proof.length == 0) {
            revert EmptyInput();
        }

        for (uint256 i = 0; i < leaves.length; i++) {
            if (leaves[i].index >= leafCount) {
                revert LeafIndexOutOfBounds();
            }
        }

        for (uint256 i = 1; i < leaves.length; i++) {
            if (leaves[i].index <= leaves[i - 1].index) {
                revert NonCanonicalLeaves();
            }
        }

        uint256 leafPos;
        uint256 proofPos;
        while (leafPos < leaves.length && proofPos < proof.length) {
            root = keccak256(abi.encode(leaves[leafPos].index, leaves[leafPos].data, proof[proofPos]));
            leafPos++;
            proofPos++;
        }

        // Deliberately omitted: the real leaf cursor may retain a tail.
        if (proofPos != proof.length) {
            revert UnconsumedProof();
        }
        return root;
    }
}

