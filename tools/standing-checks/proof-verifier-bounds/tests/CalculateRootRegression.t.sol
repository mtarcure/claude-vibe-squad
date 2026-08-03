// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

struct RegressionLeaf {
    uint256 index;
    bytes32 hash;
}

contract VulnerableCalculateRoot {
    error EmptyInput();

    function calculateRoot(bytes32[] memory proof, RegressionLeaf[] memory leaves, uint256 leafCount)
        external
        pure
        returns (bytes32)
    {
        if (leafCount == 0 || leaves.length == 0) revert EmptyInput();
        if (leafCount == 1 && leaves.length == 1 && leaves[0].index == 0) {
            return leaves[0].hash;
        }

        uint256 leafPos;
        if (leafPos < leaves.length && leaves[leafPos].index < leafCount) {
            leafPos++;
            return leaves[leafPos - 1].hash;
        }

        // The vulnerable peak fallback accepts proof[0] while the out-of-range leaf remains unused.
        return proof[0];
    }
}

contract FixedCalculateRoot {
    error EmptyInput();
    error LeafIndexOutOfBounds();
    error UnconsumedLeaves();
    error UnconsumedProof();

    function calculateRoot(bytes32[] memory proof, RegressionLeaf[] memory leaves, uint256 leafCount)
        external
        pure
        returns (bytes32)
    {
        if (leafCount == 0 || leaves.length == 0) revert EmptyInput();
        for (uint256 i = 0; i < leaves.length; i++) {
            if (leaves[i].index >= leafCount) revert LeafIndexOutOfBounds();
        }

        uint256 leafPos;
        uint256 proofPos;
        bytes32 root;
        if (leafPos < leaves.length && leaves[leafPos].index < leafCount) {
            root = leaves[leafPos].hash;
            leafPos++;
        } else {
            root = proof[proofPos];
            proofPos++;
        }
        if (leafPos != leaves.length) revert UnconsumedLeaves();
        if (proofPos != proof.length) revert UnconsumedProof();
        return root;
    }
}

contract CalculateRootRegressionTest {
    function testVulnerableOutOfBoundsLeafIsIgnoredAndProofRootAccepted() public {
        VulnerableCalculateRoot verifier = new VulnerableCalculateRoot();
        bytes32 storedRoot = keccak256("stored-root");
        bytes32 maliciousLeaf = keccak256("malicious-payload");
        bytes32[] memory proof = new bytes32[](1);
        proof[0] = storedRoot;
        RegressionLeaf[] memory leaves = new RegressionLeaf[](1);
        leaves[0] = RegressionLeaf({index: 1, hash: maliciousLeaf});

        bytes32 calculated = verifier.calculateRoot(proof, leaves, 1);
        require(calculated == storedRoot, "vulnerable control did not reproduce root substitution");
        require(calculated != maliciousLeaf, "malicious leaf unexpectedly participated");
    }

    function testFixedRejectsSameOutOfBoundsLeaf() public {
        FixedCalculateRoot verifier = new FixedCalculateRoot();
        bytes32[] memory proof = new bytes32[](1);
        proof[0] = keccak256("stored-root");
        RegressionLeaf[] memory leaves = new RegressionLeaf[](1);
        leaves[0] = RegressionLeaf({index: 1, hash: keccak256("malicious-payload")});

        try verifier.calculateRoot(proof, leaves, 1) returns (bytes32) {
            revert("fixed verifier accepted out-of-bounds leaf");
        } catch (bytes memory reason) {
            require(_selector(reason) == FixedCalculateRoot.LeafIndexOutOfBounds.selector, "wrong rejection");
        }
    }

    function testFixedAcceptsValidSingleLeafNegativeControl() public {
        FixedCalculateRoot verifier = new FixedCalculateRoot();
        bytes32 expected = keccak256("valid-leaf");
        bytes32[] memory proof = new bytes32[](0);
        RegressionLeaf[] memory leaves = new RegressionLeaf[](1);
        leaves[0] = RegressionLeaf({index: 0, hash: expected});

        require(verifier.calculateRoot(proof, leaves, 1) == expected, "valid negative control rejected");
    }

    function _selector(bytes memory reason) private pure returns (bytes4 selector) {
        if (reason.length < 4) return bytes4(0);
        assembly {
            selector := mload(add(reason, 32))
        }
    }
}
