# Dispatch plan — negative control fixture

This fixture is a faithful imitation of a real campaign brief: it names the whole
arsenal and assigns it to lanes. Nothing here ever ran. The extractor must classify
every technique below as MISSED.

## Arsenal handed to every lane

| Tool | Purpose |
|---|---|
| echidna | property fuzzing of Solidity harnesses |
| medusa | second property fuzzer, independent implementation |
| halmos | symbolic execution over Foundry tests |
| slither | Solidity detector suite |
| semgrep | custom pattern rules |
| forge | build and test runner |
| aderyn | secondary Solidity scanner |

## Lane assignments

- L1 will run echidna and medusa against the accounting harness.
- L2 will run halmos over the sibling comparison tests.
- L3 will run slither and semgrep across the whole tree.
- L4 will build with forge and execute the regression suite.

## Notes

The gateway contract and the vault contract are both in scope. Reviewers should read
Gateway.sol and Vault.sol before starting. No results are recorded in this document
because no lane has reported yet.
