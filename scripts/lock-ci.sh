#!/usr/bin/env bash
# Regenerate the hash-locked requirement files used by the workflows: the
# test environment on the newest mcp 2.3.x release, plus the release build
# tools. Run after changing dependencies in pyproject.toml or
# requirements/build.in.
set -euo pipefail
cd "$(dirname "$0")/.."
override=$(mktemp)
trap 'rm -f "$override"' EXIT
printf 'mcp~=2.3.0\n' > "$override"
uv pip compile pyproject.toml --extra dev --extra http --extra wsgi --universal \
  --python-version 3.10 --generate-hashes --override "$override" \
  --custom-compile-command "bash scripts/lock-ci.sh" \
  -o requirements/ci.txt
uv pip compile requirements/build.in --universal --python-version 3.10 \
  --generate-hashes -o requirements/build.txt
