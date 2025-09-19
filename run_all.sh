#!/usr/bin/env bash
# English helper script to run all methods against the example config
set -euo pipefail

python -m python.cli run --config config/scenarios.example.yaml --all
