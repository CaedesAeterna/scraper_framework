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
import re
from .html_utils import normalize_html_text
import math

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
        # Prepare normalized page text
        page_text = normalize_html_text(html) if isinstance(html, str) else ""

        # Use extracted fields for accuracy if any, otherwise prefer page_text, else fallback to data
        if extracted_fields:
            fields_for_accuracy = extracted_fields
        elif page_text:
            fields_for_accuracy = {"page_text": page_text}
        else:
            fields_for_accuracy = data

        # Accuracy/completeness: if pseudo ground truth is provided, estimate against it
        acc = 0.0
        comp = 0.0

        pseudo_gt = target.get('pseudo_ground_truth') or target.get('pseudo_gt')
        def value_similarity(a: str, b: str) -> float:
            """Return similarity between two values in [0.0, 1.0].
            Handles numeric tolerance, currency stripping, case-insensitive exact match, and token Jaccard.
            """
            if a is None or b is None:
                return 0.0
            sa = str(a).strip()
            sb = str(b).strip()

            # Exact match (case-insensitive)
            if sa.lower() == sb.lower():
                return 1.0

            # Try numeric comparison after stripping common currency symbols and separators
            def normalize_number(s: str):
                s2 = re.sub(r'[,$€£¥₹\s]', '', s)
                try:
                    return float(s2)
                except Exception:
                    return None

            na = normalize_number(sa)
            nb = normalize_number(sb)
            if na is not None and nb is not None:
                # relative closeness
                if na == nb:
                    return 1.0
                diff = abs(na - nb)
                denom = max(abs(na), abs(nb), 1.0)
                sim = max(0.0, 1.0 - diff / denom)
                return sim

            # Token Jaccard similarity for strings
            def tokens(s: str):
                return set(t for t in re.split(r'\W+', s.lower()) if t)
            ta = tokens(sa)
            tb = tokens(sb)
            if not ta and not tb:
                return 0.0

            # If both values are long, use a cosine-like approximation for more continuous scores
            if len(ta) > 8 or len(tb) > 8:
                inter = len(ta & tb)
                if inter == 0:
                    return 0.0
                mag = math.sqrt(max(len(ta), 1) * max(len(tb), 1))
                return inter / mag

            inter = len(ta & tb)
            union = len(ta | tb)
            return inter / union if union > 0 else 0.0

        if pseudo_gt and isinstance(pseudo_gt, dict) and pseudo_gt:
            # fields_for_accuracy contains extracted fields (preferred) or direct data
            extracted = fields_for_accuracy
            # Accuracy: average similarity across pseudo-gt fields
            total_fields = len(pseudo_gt)
            if total_fields > 0:
                # If comparison_results provided (leave-one-out other scrapers), compute
                # accuracy as average pairwise similarity to other scrapers instead of comparing
                # to consensus value (avoids tautological 100% when the method contributed).
                comparison = target.get('comparison_results')
                if comparison and isinstance(comparison, dict) and comparison:
                    # Build set of comparison fields (union of fields from other scrapers)
                    comp_fields = set()
                    for mfields in comparison.values():
                        if isinstance(mfields, dict):
                            comp_fields.update(mfields.keys())

                    if comp_fields:
                        field_sims = []
                        present = 0
                        for field in comp_fields:
                            ev = extracted.get(field)
                            # average similarity of this method's value to other scrapers that have the field
                            sims = []
                            for other_fields in comparison.values():
                                ov = other_fields.get(field) if isinstance(other_fields, dict) else None
                                if ov is None or str(ov).strip() == "":
                                    continue
                                # if evaluated value missing, similarity 0
                                if ev is None or str(ev).strip() == "":
                                    sims.append(0.0)
                                else:
                                    sims.append(value_similarity(ev, ov))
                            if sims:
                                field_sims.append(sum(sims) / len(sims))
                                if ev is not None and str(ev).strip() != "":
                                    present += 1

                        acc = 100.0 * (sum(field_sims) / len(field_sims)) if field_sims else 0.0
                        comp = 100.0 * (present / len(comp_fields)) if comp_fields else 0.0
                    else:
                        # fallback to consensus-based scoring
                        total_sim = 0.0
                        present = 0
                        for k, v in pseudo_gt.items():
                            ev = extracted.get(k)
                            if ev is None or str(ev).strip() == "":
                                continue
                            sim = value_similarity(ev, v)
                            total_sim += sim
                            present += 1
                        acc = 100.0 * (total_sim / total_fields)
                        comp = 100.0 * (present / total_fields)
                else:
                    total_sim = 0.0
                    present = 0
                    for k, v in pseudo_gt.items():
                        ev = extracted.get(k)
                        if ev is None or str(ev).strip() == "":
                            continue
                        sim = value_similarity(ev, v)
                        total_sim += sim
                        present += 1
                    acc = 100.0 * (total_sim / total_fields)
                    comp = 100.0 * (present / total_fields)
        else:
            # Fallback: keep previous behavior (use expected_fields if available)
            acc = Metrics.accuracy(expected_fields, fields_for_accuracy)
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
    # Flatten for CSV and write using stdlib csv to avoid pandas dependency
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        header = [
            "target", "url", "method", "ok", "accuracy", "completeness",
            "freshness", "redundancy", "throughput", "robustness", "observed_at"
        ]
        writer.writerow(header)

        for r in results:
            m = r.get("metrics", {})
            row = [
                r.get("target"),
                r.get("url"),
                r.get("method"),
                r.get("ok"),
                m.get("accuracy"),
                m.get("completeness"),
                m.get("freshness"),
                m.get("redundancy"),
                m.get("throughput"),
                m.get("robustness"),
                r.get("observed_at"),
            ]
            writer.writerow(row)
