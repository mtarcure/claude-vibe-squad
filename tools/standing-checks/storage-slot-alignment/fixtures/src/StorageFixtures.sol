// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract VulnerableProxy {
    bool public initialized;
    address public proxyAdmin;
    address public implementation;
}

contract VulnerableImplementation {
    bool public initialized;
    address public owner;
    uint256 public value;
}

contract GoodEip1967Proxy {
    bytes32 internal constant IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    constructor(address implementation_) {
        bytes32 slot = IMPLEMENTATION_SLOT;
        assembly {
            sstore(slot, implementation_)
        }
    }
}

contract GoodImplementation {
    bool public initialized;
    address public owner;
    uint256 public value;
}
