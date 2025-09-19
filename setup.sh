#!/usr/bin/env bash
# Convenience setup script (optional)
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

npm install
npx playwright install

echo "Environment ready. Activate with: source .venv/bin/activate"
