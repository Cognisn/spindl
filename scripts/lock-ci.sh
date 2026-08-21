#!/usr/bin/env bash
# Regenerate the hash-locked CI requirement files, one per supported mcp
# series. Run after changing dependencies in pyproject.toml.
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
