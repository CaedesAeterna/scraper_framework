#!/usr/bin/env python3
"""
English-language core CLI for running scenarios and computing metrics.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from tqdm import tqdm

from .evaluator import Evaluator

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_METHODS = [
    "requests",
    "scrapy",
    "selenium",
    "puppeteer",
    "playwright",
]


def run_node_scraper(script: str, url: str, timeout: int):
    """Run a Node-based scraper (puppeteer/playwright) and return JSON result dict.

    The Node script should print a single JSON line with keys: {"ok": bool, "data": {...}, "error": str|null, "timestamps": {...}}
    """
    try:
        proc = subprocess.run(
            ["node", script, "--url", url, "--timeout", str(timeout)],
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            return {"ok": False, "error": "no output", "data": {}, "timestamps": {}}
        # Expect last line to be JSON
        line = stdout.splitlines()[-1]
        return json.loads(line)
    except Exception as e:
        return {"ok": False, "error": str(e), "data": {}, "timestamps": {}}


class Runner:
    def __init__(self, config_path: Path):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.evaluator = Evaluator(self.config)

    def run_target_with_method(self, target: dict, method: str, timeout: int) -> dict:
        url = target["url"]
        res = {"ok": False, "data": {}, "error": None, "timestamps": {}}
        if method == "requests":
            from .scrapers.requests_bs import scrape as rq_scrape
            res = rq_scrape(url, timeout)
        elif method == "scrapy":
            from .scrapers.scrapy_runner import run_scrapy
            res = run_scrapy(url, timeout)
        elif method == "selenium":
            from .scrapers.selenium_runner import scrape as se_scrape
            res = se_scrape(url, timeout)
        elif method == "puppeteer":
            script = str(ROOT / "js" / "scrapers" / "puppeteer_scraper.js")
            res = run_node_scraper(script, url, timeout)
        elif method == "playwright":
            script = str(ROOT / "js" / "scrapers" / "playwright_scraper.js")
            res = run_node_scraper(script, url, timeout)
        else:
            res = {"ok": False, "data": {}, "error": f"unsupported method: {method}", "timestamps": {}}
        return res

    def run(self, methods, repeats: int):
        targets = self.config.get("targets", [])
        results = []
        for target in tqdm(targets, desc="Targets"):
            name = target.get("name", target.get("url"))
            for method in methods:
                timeout = self.config.get("time_budget", {}).get(method, {}).get("timeout_seconds", 15)
                for r in range(repeats):
                    run_res = self.run_target_with_method(target, method, timeout)
                    eval_res = self.evaluator.evaluate_single(target, method, run_res)
                    results.append(eval_res)
        return results


def main():
    parser = argparse.ArgumentParser(description="Run scraping scenarios and compute metrics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Execute scenarios")
    run_p.add_argument("--config", required=True, help="Path to scenarios yaml")
    run_p.add_argument("--methods", nargs="*", default=[], help="Subset of methods to run")
    run_p.add_argument("--all", action="store_true", help="Run all methods")

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if args.all:
        methods = SUPPORTED_METHODS
    else:
        methods = args.methods or ["requests"]

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    repeats = int(cfg.get("sampling", {}).get("repeats", 1))

    runner = Runner(config_path)
    results = runner.run(methods, repeats)

    # Persist
    out_json = RESULTS_DIR / "results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Aggregate CSV
    from .evaluator import results_to_csv
    out_csv = RESULTS_DIR / "results.csv"
    results_to_csv(results, out_csv)

    # Pretty print summary table
    print(f"Saved: {out_json} and {out_csv}")


if __name__ == "__main__":
    main()
