from __future__ import annotations
"""
Evaluation engine: executes scraping runs, collects raw signals, and computes 0-100 scores.
English comments.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import json
import pandas as pd
from bs4 import BeautifulSoup
from lxml import html as LH

from .metrics import Metrics


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evaluator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _normalize_text(self, s: str) -> str:
        tn = (self.config.get("parsing", {}) or {}).get("text_normalization", {})
        if s is None:
            return s
        if tn.get("strip", True):
            s = s.strip()
        if tn.get("lower", False):
            s = s.lower()
        return s

    def _extract_with_selectors(self, html: str, selectors: Dict[str, Any]) -> Dict[str, Any]:
        """Extract fields from HTML using CSS or XPath selectors.
        Returns a flat dict of field -> first match text.
        """
        out: Dict[str, Any] = {}
        if not html or not selectors:
            return out
        soup = BeautifulSoup(html, "lxml")
        try:
            doc = LH.fromstring(html)
        except Exception:
            doc = None
        for field, sel in selectors.items():
            val = None
            if isinstance(sel, dict):
                if sel.get("css"):
                    try:
                        el = soup.select_one(sel["css"])  # type: ignore[arg-type]
                        if el is not None:
                            val = el.get_text(" ", strip=True)
                    except Exception:
                        pass
                elif sel.get("xpath") and doc is not None:
                    try:
                        res = doc.xpath(sel["xpath"])  # type: ignore[arg-type]
                        if res:
                            first = res[0]
                            if hasattr(first, "text_content"):
                                val = first.text_content().strip()
                            else:
                                # string/attribute result
                                val = str(first).strip()
                    except Exception:
                        pass
            if isinstance(val, str):
                val = self._normalize_text(val)
            out[field] = val
        return out

    def evaluate_single(self, target: Dict[str, Any], method: str, run_res: Dict[str, Any]) -> Dict[str, Any]:
        # Raw signals
        ok = bool(run_res.get("ok"))
        data = run_res.get("data", {}) or {}
        error = run_res.get("error")
        timestamps = run_res.get("timestamps", {}) or {}
        observed_at = timestamps.get("observed_at") or now_iso()

        expected_fields = (target.get("expected_fields") or {}).copy()
        
        # Check for pseudo ground truth
        pseudo_gt = target.get("pseudo_ground_truth")
        if pseudo_gt and not expected_fields:
            expected_fields = pseudo_gt.copy()
        selectors = (target.get("selectors") or {}).copy()
        source_updated_at = target.get("source_updated_at")

        # Extract fields from HTML using selectors if available
        extracted_fields = {}
        html = data.get("html")
        if isinstance(html, str) and selectors:
            extracted_fields = self._extract_with_selectors(html, selectors)
        # Use extracted fields for accuracy if any, otherwise fallback to provided data
        fields_for_accuracy = extracted_fields if extracted_fields else data

        # Accuracy: per-field match (only expected keys are compared)
        acc = Metrics.accuracy(expected_fields, fields_for_accuracy)

        # Completeness: if an expected items_count is given, compare counts; else binary success
        expected_items = expected_fields.get("items_count")
        got_items = data.get("items_count")
        comp = Metrics.completeness(expected_items, got_items)

        # Freshness
        fresh = Metrics.freshness(source_updated_at, observed_at)

        # Redundancy: requires total vs unique; try infer from arrays
        total_items = data.get("total_items") or 0
        unique_items = data.get("unique_items") or total_items
        red = Metrics.redundancy(total_items, unique_items)

        # Throughput: map from duration
        duration_sec = float(timestamps.get("duration_sec") or 0.0)
        pages_per_sec = 0.0 if duration_sec <= 0 else 1.0 / duration_sec
        thr = Metrics.throughput(pages_per_sec)

        # Robustness: 0 if ok else 1, and adjust for declared complexity
        base_err = 0.0 if ok else 1.0
        # average over multiple runs would be aggregated later; here single run
        rob = Metrics.robustness(base_err)

        return {
            "target": target.get("name", target.get("url")),
            "url": target.get("url"),
            "method": method,
            "ok": ok,
            "error": error,
            "observed_at": observed_at,
            "metrics": {
                "accuracy": acc,
                "completeness": comp,
                "freshness": fresh,
                "redundancy": red,
                "throughput": thr,
                "robustness": rob,
            },
            "raw": {
                "data": data,
                "extracted_fields": extracted_fields,
                "timestamps": timestamps,
            },
        }


def results_to_csv(results: List[Dict[str, Any]], out_path: Path):
    # Flatten for CSV
    rows = []
    for r in results:
        m = r.get("metrics", {})
        rows.append({
            "target": r.get("target"),
            "url": r.get("url"),
            "method": r.get("method"),
            "ok": r.get("ok"),
            "accuracy": m.get("accuracy"),
            "completeness": m.get("completeness"),
            "freshness": m.get("freshness"),
            "redundancy": m.get("redundancy"),
            "throughput": m.get("throughput"),
            "robustness": m.get("robustness"),
            "observed_at": r.get("observed_at"),
        })
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
