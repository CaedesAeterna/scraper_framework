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
from .pseudo_ground_truth import PseudoGroundTruthBuilder

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
RAW_RESULTS_DIR = ROOT / "results_raw"
RAW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

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
    def __init__(self, config_path: Path, use_pseudo_ground_truth: bool = False, save_raw: bool = True):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.evaluator = Evaluator(self.config)
        self.use_pseudo_ground_truth = use_pseudo_ground_truth
        self.save_raw = save_raw
        self.raw_results = []  # Store raw results for saving
        
        if use_pseudo_ground_truth:
            self.pseudo_gt_builder = PseudoGroundTruthBuilder(
                confidence_threshold=0.6,
                min_consensus=2
            )

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
        
        # Store raw result if enabled
        if self.save_raw:
            self._save_raw_result(target, method, res)
        
        return res

    def run(self, methods, repeats: int):
        targets = self.config.get("targets", [])
        results = []
        
        for target in tqdm(targets, desc="Targets"):
            name = target.get("name", target.get("url"))
            url = target.get("url")
            
            if self.use_pseudo_ground_truth:
                # Run all methods for this target to build consensus
                target_results = self._run_target_all_methods(target, methods, repeats)
                
                # Build pseudo ground truth from consensus
                pseudo_gt = self._build_pseudo_ground_truth_for_target(target, target_results)
                
                # Update target with pseudo ground truth if available
                if pseudo_gt and pseudo_gt.get('overall_confidence', 0) > 0.6:
                    enhanced_target = target.copy()
                    enhanced_target['pseudo_ground_truth'] = pseudo_gt['consensus_data']
                    enhanced_target['pseudo_confidence'] = pseudo_gt['overall_confidence']
                    
                    # Re-evaluate with pseudo ground truth (single pseudo-GT for all methods)
                    for method in methods:
                        if method not in target_results:
                            continue

                        for r in range(len(target_results[method])):
                            # By default use global pseudo GT
                            eval_target = enhanced_target
                            used_pseudo_meta = {
                                'type': 'global',
                                'scrapers_used': pseudo_gt.get('scrapers_used', []),
                                'coverage': pseudo_gt.get('stats', {}).get('coverage')
                            }

                            # If the method contributed to the consensus, build a leave-one-out pseudo-GT
                            if method in pseudo_gt.get('scrapers_used', []):
                                # Build results_by_method excluding this method
                                results_by_method = {}
                                for m, runs in target_results.items():
                                    if m == method:
                                        continue
                                    if runs and runs[0].get('ok'):
                                        results_by_method[m] = runs[0]

                                if len(results_by_method) >= self.pseudo_gt_builder.min_consensus:
                                    method_pseudo = self.pseudo_gt_builder.build_consensus(results_by_method)
                                    if method_pseudo and method_pseudo.get('overall_confidence', 0) > 0.6:
                                        eval_target = enhanced_target.copy()
                                        eval_target['pseudo_ground_truth'] = method_pseudo['consensus_data']
                                        eval_target['pseudo_confidence'] = method_pseudo['overall_confidence']
                                        used_pseudo_meta = {
                                            'type': 'leave-one-out',
                                            'scrapers_used': method_pseudo.get('scrapers_used', []),
                                            'coverage': method_pseudo.get('stats', {}).get('coverage')
                                        }
                                    else:
                                        # Couldn't build a reliable leave-one-out pseudo-GT.
                                        # To avoid tautological 100% scores, do not evaluate accuracy/completeness.
                                        # Perform a regular evaluation but null out accuracy/completeness and mark tautological.
                                        eval_res = self.evaluator.evaluate_single(target, method, target_results[method][r])
                                        eval_res['pseudo_ground_truth_used'] = False
                                        eval_res['tautological'] = True
                                        # Null out possibly-tautological metrics
                                        eval_res['metrics']['accuracy'] = None
                                        eval_res['metrics']['completeness'] = None
                                        results.append(eval_res)
                                        continue

                            eval_res = self.evaluator.evaluate_single(eval_target, method, target_results[method][r])
                            # Add pseudo ground truth metadata
                            eval_res['pseudo_ground_truth_used'] = True
                            eval_res['pseudo_confidence'] = eval_target.get('pseudo_confidence', pseudo_gt.get('overall_confidence'))
                            eval_res['consensus_metadata'] = used_pseudo_meta
                            results.append(eval_res)
                else:
                    # Fallback to regular evaluation
                    for method in methods:
                        if method in target_results:
                            for run_res in target_results[method]:
                                eval_res = self.evaluator.evaluate_single(target, method, run_res)
                                eval_res['pseudo_ground_truth_used'] = False
                                results.append(eval_res)
            else:
                # Original behavior
                for method in methods:
                    timeout = self.config.get("time_budget", {}).get(method, {}).get("timeout_seconds", 15)
                    for r in range(repeats):
                        run_res = self.run_target_with_method(target, method, timeout)
                        eval_res = self.evaluator.evaluate_single(target, method, run_res)
                        results.append(eval_res)
        
        return results
    
    def _run_target_all_methods(self, target: dict, methods: list, repeats: int):
        """Run all methods for a target and collect results."""
        target_results = {}
        
        for method in methods:
            timeout = self.config.get("time_budget", {}).get(method, {}).get("timeout_seconds", 15)
            method_results = []
            
            for r in range(repeats):
                run_res = self.run_target_with_method(target, method, timeout)
                method_results.append(run_res)
            
            target_results[method] = method_results
        
        return target_results
    
    def _build_pseudo_ground_truth_for_target(self, target: dict, target_results: dict):
        """Build pseudo ground truth for a specific target."""
        url = target.get('url')
        # Take the first run of each method for consensus building
        results_by_method = {}
        for method, runs in target_results.items():
            if runs and runs[0].get('ok'):  # Use first successful run
                results_by_method[method] = runs[0]
        
        if len(results_by_method) < 2:
            return None
        
        # Build consensus
        pseudo_gt = self.pseudo_gt_builder.build_consensus(results_by_method)
        return pseudo_gt
    
    def _save_raw_result(self, target: dict, method: str, result: dict):
        """Save individual raw scraper result."""
        from datetime import datetime
        
        raw_entry = {
            'target': target.get('name', target.get('url')),
            'url': target.get('url'),
            'method': method,
            'timestamp': datetime.now().isoformat(),
            'result': result
        }
        
        self.raw_results.append(raw_entry)
    
    def save_all_raw_results(self, run_id: str = None):
        """Save all collected raw results to a file."""
        from datetime import datetime
        import json
        
        if not self.raw_results:
            return None
        
        # Generate run ID if not provided
        if run_id is None:
            run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save to timestamped file
        raw_file = RAW_RESULTS_DIR / f"raw_results_{run_id}.json"
        
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(self.raw_results, f, ensure_ascii=False, indent=2)
        
        # Also save to latest
        latest_file = RAW_RESULTS_DIR / "raw_results_latest.json"
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(self.raw_results, f, ensure_ascii=False, indent=2)
        
        return raw_file


def main():
    parser = argparse.ArgumentParser(description="Run scraping scenarios and compute metrics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Execute scenarios")
    run_p.add_argument("--config", required=True, help="Path to scenarios yaml")
    run_p.add_argument("--methods", nargs="*", default=[], help="Subset of methods to run")
    run_p.add_argument("--all", action="store_true", help="Run all methods")
    run_p.add_argument("--pseudo-ground-truth", action="store_true", 
                      help="Use pseudo ground truth from multi-scraper consensus")
    run_p.add_argument("--no-raw", action="store_true",
                      help="Disable saving raw scraper results")

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

    save_raw = not getattr(args, 'no_raw', False)
    runner = Runner(config_path, 
                   use_pseudo_ground_truth=getattr(args, 'pseudo_ground_truth', False),
                   save_raw=save_raw)
    results = runner.run(methods, repeats)

    # Persist
    out_json = RESULTS_DIR / "results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Aggregate CSV
    from .evaluator import results_to_csv
    out_csv = RESULTS_DIR / "results.csv"
    results_to_csv(results, out_csv)
    
    # Save raw results
    if save_raw:
        from datetime import datetime
        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_file = runner.save_all_raw_results(run_id)
        if raw_file:
            print(f"Saved: {out_json}, {out_csv}, and {raw_file}")
            print(f"Raw results also saved to: {RAW_RESULTS_DIR / 'raw_results_latest.json'}")
        else:
            print(f"Saved: {out_json} and {out_csv}")
    else:
        print(f"Saved: {out_json} and {out_csv}")


if __name__ == "__main__":
    main()
