#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
validator="$repo_root/bin/validate-capabilities.sh"

"$validator" --self-test
"$validator" \
  shared/capabilities/project/web-app.md \
  shared/capabilities/bounty/smart-contract-web3.md \
  shared/capabilities/content/image.md \
  shared/capabilities/project/self-extension-agent-tooling.md >/dev/null
