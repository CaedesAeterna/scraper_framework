#!/usr/bin/env python3
"""
English-language core CLI for running scenarios and computing metrics.
CRITICAL FIX: Extract fields from data, not just extracted_fields
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
    """Run a Node-based scraper (puppeteer/playwright) and return JSON result dict."""
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
        self.raw_results = []
        
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
                print(f"\n{'='*70}")
                print(f"Processing target: {name}")
                print(f"{'='*70}")
                
                # Run all methods for this target
                target_results = self._run_target_all_methods(target, methods, repeats)
                
                # Build pseudo ground truth from consensus
                pseudo_gt = self._build_pseudo_ground_truth_for_target(target, target_results)
                
                if pseudo_gt and pseudo_gt.get('overall_confidence', 0) > 0.6:
                    print(f"✓ Built pseudo ground truth (confidence: {pseudo_gt['overall_confidence']:.2f})")
                    print(f"  Scrapers contributing: {pseudo_gt.get('scrapers_used', [])}")
                    print(f"  Consensus fields: {list(pseudo_gt.get('consensus_data', {}).keys())}")
                    
                    # For each method, decide evaluation strategy
                    for method in methods:
                        if method not in target_results:
                            continue

                        for run_idx in range(len(target_results[method])):
                            run_res = target_results[method][run_idx]
                            
                            # Check if this method contributed to pseudo GT
                            if method in pseudo_gt.get('scrapers_used', []):
                                print(f"\n  Evaluating {method} (leave-one-out)...")
                                
                                # Build leave-one-out evaluation
                                loo_target = self._build_leave_one_out_evaluation(
                                    target, method, target_results
                                )
                                
                                if loo_target:
                                    print(f"    ✓ Leave-one-out successful")
                                    print(f"    Comparing against: {list(loo_target.get('comparison_results', {}).keys())}")
                                    
                                    eval_res = self.evaluator.evaluate_single(loo_target, method, run_res)
                                    eval_res['pseudo_ground_truth_used'] = True
                                    eval_res['evaluation_type'] = 'leave-one-out'
                                    eval_res['pseudo_confidence'] = loo_target.get('pseudo_confidence')
                                else:
                                    print(f"    ✗ Leave-one-out failed (insufficient data)")
                                    eval_res = self.evaluator.evaluate_single(target, method, run_res)
                                    eval_res['pseudo_ground_truth_used'] = False
                                    eval_res['evaluation_type'] = 'tautological'
                                    eval_res['metrics']['accuracy'] = None
                                    eval_res['metrics']['completeness'] = None
                            else:
                                print(f"\n  Evaluating {method} (global consensus)...")
                                
                                # Method didn't contribute, use global pseudo GT
                                enhanced_target = target.copy()
                                enhanced_target['pseudo_ground_truth'] = pseudo_gt['consensus_data']
                                enhanced_target['pseudo_confidence'] = pseudo_gt['overall_confidence']
                                
                                eval_res = self.evaluator.evaluate_single(enhanced_target, method, run_res)
                                eval_res['pseudo_ground_truth_used'] = True
                                eval_res['evaluation_type'] = 'global-consensus'
                                eval_res['pseudo_confidence'] = pseudo_gt['overall_confidence']
                                eval_res['consensus_metadata'] = {
                                    'scrapers_used': pseudo_gt.get('scrapers_used', []),
                                    'coverage': pseudo_gt.get('stats', {}).get('coverage')
                                }
                            
                            results.append(eval_res)
                else:
                    print(f"✗ Could not build reliable pseudo ground truth")
                    
                    # No reliable pseudo GT, use standard evaluation
                    for method in methods:
                        if method in target_results:
                            for run_res in target_results[method]:
                                eval_res = self.evaluator.evaluate_single(target, method, run_res)
                                eval_res['pseudo_ground_truth_used'] = False
                                eval_res['evaluation_type'] = 'no-consensus'
                                results.append(eval_res)
            else:
                # Original behavior without pseudo ground truth
                for method in methods:
                    timeout = self.config.get("time_budget", {}).get(method, {}).get("timeout_seconds", 15)
                    for r in range(repeats):
                        run_res = self.run_target_with_method(target, method, timeout)
                        eval_res = self.evaluator.evaluate_single(target, method, run_res)
                        eval_res['pseudo_ground_truth_used'] = False
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
        """Build pseudo ground truth for a specific target from all successful runs."""
        # Use first successful run of each method
        results_by_method = {}
        for method, runs in target_results.items():
            if runs and runs[0].get('ok'):
                results_by_method[method] = runs[0]
        
        if len(results_by_method) < self.pseudo_gt_builder.min_consensus:
            return None
        
        return self.pseudo_gt_builder.build_consensus(results_by_method)
    
    def _build_leave_one_out_evaluation(self, target: dict, excluded_method: str, 
                                       target_results: dict) -> dict:
        """
        Build evaluation target with leave-one-out pseudo GT and comparison results.
        
        CRITICAL: Must extract fields from EACH scraper's data for comparison
        """
        print(f"    [LOO] Building leave-one-out for {excluded_method}...")
        
        # Build consensus excluding this method
        results_by_method = {}
        for method, runs in target_results.items():
            if method == excluded_method:
                continue
            if runs and runs[0].get('ok'):
                results_by_method[method] = runs[0]
        
        print(f"    [LOO] Other successful scrapers: {list(results_by_method.keys())}")
        
        if len(results_by_method) < self.pseudo_gt_builder.min_consensus:
            print(f"    [LOO] Insufficient scrapers: {len(results_by_method)} < {self.pseudo_gt_builder.min_consensus}")
            return None
        
        # Build leave-one-out pseudo GT
        loo_pseudo_gt = self.pseudo_gt_builder.build_consensus(results_by_method)
        
        if not loo_pseudo_gt or loo_pseudo_gt.get('overall_confidence', 0) < 0.6:
            print(f"    [LOO] Low confidence: {loo_pseudo_gt.get('overall_confidence', 0) if loo_pseudo_gt else 0:.2f}")
            return None
        
         # CRITICAL FIX: Extract fields from HTML for each scraper
        comparison_results = {}
        selectors = target.get('selectors', {})

        for method, result in results_by_method.items():
            html = result.get('data', {}).get('html')
            if not html:
                print(f" [LOO] {method}: No HTML found")
                continue

            # Extract fields using auto-extraction or manual selectors
            if selectors:
                extracted = self.evaluator._extract_with_selectors(html, selectors)
            else:
                # AUTO MODE
                extracted = self.evaluator._extract_all_content(html)

            if extracted and any(v for v in extracted.values() if v):
                comparison_results[method] = extracted
                print(f" [LOO] {method}: Extracted {len(extracted)} fields")
                # Debug: show field names
                print(f"       Fields: {list(extracted.keys())[:5]}...")
            else:
                print(f" [LOO] {method}: No fields extracted")

            if not comparison_results:
                print(f"    [LOO] ERROR: No comparison data extracted from other scrapers!")
                return None

            print(f"    [LOO] Total comparison scrapers: {len(comparison_results)}")
        
        # Build evaluation target
        eval_target = target.copy()
        eval_target['pseudo_ground_truth'] = loo_pseudo_gt['consensus_data']
        eval_target['pseudo_confidence'] = loo_pseudo_gt['overall_confidence']
        eval_target['comparison_results'] = comparison_results  # THIS IS THE KEY!
        eval_target['leave_one_out_metadata'] = {
            'excluded_method': excluded_method,
            'scrapers_used': loo_pseudo_gt.get('scrapers_used', []),
            'coverage': loo_pseudo_gt.get('stats', {}).get('coverage')
        }
        
        return eval_target
    
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
        
        if run_id is None:
            run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        raw_file = RAW_RESULTS_DIR / f"raw_results_{run_id}.json"
        
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(self.raw_results, f, ensure_ascii=False, indent=2)
        
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
            print(f"\n{'='*70}")
            print(f"Saved: {out_json}, {out_csv}, and {raw_file}")
            print(f"Raw results also saved to: {RAW_RESULTS_DIR / 'raw_results_latest.json'}")
            print(f"{'='*70}")
        else:
            print(f"Saved: {out_json} and {out_csv}")
    else:
        print(f"Saved: {out_json} and {out_csv}")


if __name__ == "__main__":
    main()
