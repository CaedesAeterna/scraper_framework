#!/usr/bin/env python3
"""
Diagnostic script to see what's actually being compared
Run this to understand why everything is 100%
"""
import json
from pathlib import Path

def diagnose_results():
    """Analyze results to find tautological comparisons"""
    
    # Load results
    results_file = Path("results/results.json")
    raw_file = Path("results_raw/raw_results_latest.json")
    
    if not results_file.exists():
        print("❌ No results.json found. Run your scraper first.")
        return
    
    with open(results_file) as f:
        results = json.load(f)
    
    print("="*60)
    print("DIAGNOSTIC REPORT: Why Everything is 100%")
    print("="*60)
    
    # Group by target and method
    by_target = {}
    for r in results:
        target = r.get('target')
        method = r.get('method')
        if target not in by_target:
            by_target[target] = {}
        by_target[target][method] = r
    
    # Analyze each target
    for target_name, methods_data in by_target.items():
        print(f"\n📍 TARGET: {target_name}")
        print("-"*60)
        
        for method, result in methods_data.items():
            acc = result.get('metrics', {}).get('accuracy')
            comp = result.get('metrics', {}).get('completeness')
            eval_type = result.get('evaluation_type', 'unknown')
            pseudo_used = result.get('pseudo_ground_truth_used', False)
            
            print(f"\n  Method: {method}")
            print(f"    Accuracy: {acc}")
            print(f"    Completeness: {comp}")
            print(f"    Evaluation Type: {eval_type}")
            print(f"    Pseudo GT Used: {pseudo_used}")
            
            # Check for problems
            if acc == 100.0:
                print("    ⚠️  PROBLEM: Perfect 100% score (likely tautological)")
                
                # Check if this is leave-one-out
                if eval_type == 'leave-one-out':
                    print("    → Should be comparing to OTHER scrapers only")
                    print("    → Check if comparison_results was properly passed")
                
                elif eval_type == 'global-consensus':
                    print("    → Comparing to global consensus that includes this method")
                    print("    → This method should use leave-one-out instead!")
                
                # Check consensus metadata
                consensus_meta = result.get('consensus_metadata', {})
                if consensus_meta:
                    scrapers_used = consensus_meta.get('scrapers_used', [])
                    print(f"    → Consensus built from: {scrapers_used}")
                    if method in scrapers_used:
                        print(f"    ❌ TAUTOLOGICAL: {method} compared to consensus it contributed to!")
    
    # Check raw results if available
    if raw_file.exists():
        print("\n" + "="*60)
        print("CHECKING RAW SCRAPER OUTPUT")
        print("="*60)
        
        with open(raw_file) as f:
            raw_results = json.load(f)
        
        # Sample first few results
        for i, raw in enumerate(raw_results[:3]):
            method = raw.get('method')
            result = raw.get('result', {})
            data = result.get('data', {})
            raw_inner = result.get('raw', {})
            extracted = raw_inner.get('extracted_fields', {})
            
            print(f"\n  Raw Result #{i+1}: {method}")
            print(f"    Has extracted_fields: {bool(extracted)}")
            print(f"    Extracted fields: {list(extracted.keys()) if extracted else 'None'}")
            print(f"    Data keys: {list(data.keys())}")
            
            if extracted:
                print(f"    Sample extracted values:")
                for k, v in list(extracted.items())[:3]:
                    val_preview = str(v)[:100] if v else 'None'
                    print(f"      {k}: {val_preview}")
    
    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    print("""
    If you see:
    1. ❌ "TAUTOLOGICAL" messages → Leave-one-out evaluation is not working
    2. All methods at 100% → They're comparing to consensus they built
    3. No extracted_fields in raw output → Your scrapers need to populate this
    
    Next steps:
    1. Check if scrapers return extracted_fields in their results
    2. Verify _build_leave_one_out_evaluation is being called
    3. Add debug prints to see what's being compared
    """)

if __name__ == "__main__":
    diagnose_results()
