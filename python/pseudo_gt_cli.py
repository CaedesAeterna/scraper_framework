#!/usr/bin/env python3
"""
Pseudo Ground Truth CLI utility for testing and managing pseudo ground truth functionality.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml
from tqdm import tqdm

from .pseudo_ground_truth import PseudoGroundTruthBuilder, PseudoGroundTruthCache, create_pseudo_ground_truth_from_results
from .cli import run_node_scraper, SUPPORTED_METHODS

ROOT = Path(__file__).resolve().parent.parent


def test_pseudo_ground_truth(url: str, methods: list = None, confidence_threshold: float = 0.6):
    """Test pseudo ground truth generation for a single URL."""
    if methods is None:
        methods = ["requests", "puppeteer", "playwright"]  # Fast methods for testing
    
    print(f"Testing pseudo ground truth for: {url}")
    print(f"Methods: {', '.join(methods)}")
    print(f"Confidence threshold: {confidence_threshold}")
    print("-" * 50)
    
    # Run multiple scrapers
    results_by_method = {}
    
    for method in tqdm(methods, desc="Running scrapers"):
        try:
            if method == "requests":
                from .scrapers.requests_bs import scrape as rq_scrape
                result = rq_scrape(url, timeout=10)
            elif method == "scrapy":
                from .scrapers.scrapy_runner import run_scrapy
                result = run_scrapy(url, timeout=10)
            elif method == "selenium":
                from .scrapers.selenium_runner import scrape as se_scrape
                result = se_scrape(url, timeout=15)
            elif method == "puppeteer":
                script = str(ROOT / "js" / "scrapers" / "puppeteer_scraper.js")
                result = run_node_scraper(script, url, timeout=15000)
            elif method == "playwright":
                script = str(ROOT / "js" / "scrapers" / "playwright_scraper.js")
                result = run_node_scraper(script, url, timeout=15000)
            else:
                continue
            
            if result.get('ok'):
                results_by_method[method] = result
                print(f"✓ {method}: Success")
            else:
                print(f"✗ {method}: Failed - {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"✗ {method}: Exception - {str(e)}")
    
    print(f"\nSuccessful scrapers: {len(results_by_method)}")
    
    if len(results_by_method) < 2:
        print("❌ Insufficient successful results for consensus building")
        return None
    
    # Build pseudo ground truth
    print("\n" + "=" * 50)
    print("BUILDING PSEUDO GROUND TRUTH")
    print("=" * 50)
    
    pseudo_gt = create_pseudo_ground_truth_from_results(
        results_by_method, 
        confidence_threshold=confidence_threshold
    )
    
    # Display results
    print(f"Overall confidence: {pseudo_gt['overall_confidence']:.2f}")
    print(f"Scrapers used: {', '.join(pseudo_gt['scrapers_used'])}")
    print(f"Coverage: {pseudo_gt['stats']['coverage']:.2%}")
    print(f"Fields found: {pseudo_gt['stats']['consensus_fields']}/{pseudo_gt['stats']['total_fields']}")
    
    if pseudo_gt['consensus_data']:
        print("\nConsensus Data:")
        for field, value in pseudo_gt['consensus_data'].items():
            confidence = pseudo_gt['confidence_scores'][field]
            print(f"  {field}: '{value}' (confidence: {confidence:.2f})")
    
    if pseudo_gt['overall_confidence'] < confidence_threshold:
        print(f"\n⚠️  Overall confidence ({pseudo_gt['overall_confidence']:.2f}) below threshold ({confidence_threshold})")
    else:
        print(f"\n✅ Pseudo ground truth successfully generated!")
    
    return pseudo_gt


def analyze_consensus_quality(pseudo_gt: dict):
    """Analyze and display consensus quality metrics."""
    if not pseudo_gt:
        print("No pseudo ground truth data to analyze")
        return
    
    print("\n" + "=" * 50)
    print("CONSENSUS QUALITY ANALYSIS")
    print("=" * 50)
    
    print(f"Overall Confidence: {pseudo_gt['overall_confidence']:.3f}")
    print(f"Field Coverage: {pseudo_gt['stats']['coverage']:.1%}")
    print(f"Scrapers Contributing: {len(pseudo_gt['scrapers_used'])}")
    
    # Analyze individual fields
    print("\nPer-Field Analysis:")
    print("-" * 30)
    
    for field, confidence in pseudo_gt['confidence_scores'].items():
        metadata = pseudo_gt['field_metadata'][field]
        value = pseudo_gt['consensus_data'][field]
        
        print(f"\nField: {field}")
        print(f"  Value: '{value}'")
        print(f"  Confidence: {confidence:.3f}")
        print(f"  Voting scrapers: {', '.join(metadata['agreeing_scrapers'])}")
        print(f"  Vote distribution: {metadata['value_distribution']}")
        
        # Strategy breakdown
        strategy_scores = metadata['strategy_scores']
        print(f"  Strategy scores:")
        print(f"    Simple majority: {strategy_scores['simple']:.3f}")
        print(f"    Weighted: {strategy_scores['weighted']:.3f}")
        print(f"    Pattern match: {strategy_scores['pattern']:.3f}")
        print(f"    Consistency: {strategy_scores['consistency']:.3f}")


def cache_management(action: str, cache_dir: Path = None):
    """Manage pseudo ground truth cache."""
    if cache_dir is None:
        cache_dir = ROOT / "results" / "pseudo_gt_cache"
    
    cache = PseudoGroundTruthCache(cache_dir)
    
    if action == "list":
        print(f"Cache directory: {cache_dir}")
        print(f"Cache entries: {len(cache.cache)}")
        
        if cache.cache:
            print("\nCached URL patterns:")
            for pattern, data in cache.cache.items():
                confidence = data.get('overall_confidence', 0)
                timestamp = data.get('timestamp', 'Unknown')
                fields = len(data.get('consensus_data', {}))
                print(f"  {pattern}: {fields} fields, confidence={confidence:.2f}, {timestamp[:19]}")
    
    elif action == "clear":
        initial_count = len(cache.cache)
        cache.clear_expired()
        final_count = len(cache.cache)
        expired_count = initial_count - final_count
        print(f"Cleared {expired_count} expired entries")
        print(f"Remaining entries: {final_count}")
    
    elif action == "purge":
        cache.cache.clear()
        cache._save_cache()
        print("All cache entries purged")


def main():
    parser = argparse.ArgumentParser(description="Pseudo Ground Truth CLI utility")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Test command
    test_parser = subparsers.add_parser("test", help="Test pseudo ground truth for a URL")
    test_parser.add_argument("url", help="URL to test")
    test_parser.add_argument("--methods", nargs="*", default=["requests", "puppeteer", "playwright"],
                           help="Scraping methods to use")
    test_parser.add_argument("--confidence", type=float, default=0.6,
                           help="Confidence threshold")
    test_parser.add_argument("--analyze", action="store_true",
                           help="Show detailed analysis")
    
    # Cache command
    cache_parser = subparsers.add_parser("cache", help="Manage pseudo ground truth cache")
    cache_parser.add_argument("action", choices=["list", "clear", "purge"],
                            help="Cache action")
    cache_parser.add_argument("--cache-dir", type=Path,
                            help="Cache directory path")
    
    args = parser.parse_args()
    
    if args.command == "test":
        pseudo_gt = test_pseudo_ground_truth(
            args.url, 
            args.methods, 
            args.confidence
        )
        
        if pseudo_gt and args.analyze:
            analyze_consensus_quality(pseudo_gt)
    
    elif args.command == "cache":
        cache_management(args.action, args.cache_dir)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()