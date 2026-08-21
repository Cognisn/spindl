#!/usr/bin/env bash
# Regenerate the hash-locked requirement files used by the workflows: one
# test environment per supported mcp series, plus the release build tools.
# Run after changing dependencies in pyproject.toml or requirements/build.in.
set -euo pipefail
cd "$(dirname "$0")/.."
declare -A series=([mcp1]="1.29.0" [mcp2]="2.0.0")
for tag in "${!series[@]}"; do
  override=$(mktemp)
  printf 'mcp==%s\n' "${series[$tag]}" > "$override"
  uv pip compile pyproject.toml --extra dev --extra http --universal \
    --python-version 3.10 --generate-hashes --override "$override" \
    -o "requirements/ci-${tag}.txt"
  rm -f "$override"
done
uv pip compile requirements/build.in --universal --python-version 3.10 \
  --generate-hashes -o requirements/build.txt
