#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
${PYTHON:-python3.12} -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p runs reports evidence runtime
mkdir -p tools/node/bin
ln -sfn "$(command -v node)" tools/node/bin/node
