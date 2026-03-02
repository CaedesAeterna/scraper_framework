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
                        el = soup.select_one(sel["css"])
                        if el is not None:
                            val = el.get_text(" ", strip=True)
                    except Exception:
                        pass
                elif sel.get("xpath") and doc is not None:
                    try:
                        res = doc.xpath(sel["xpath"])
                        if res:
                            first = res[0]
                            if hasattr(first, "text_content"):
                                val = first.text_content().strip()
                            else:
                                val = str(first).strip()
                    except Exception:
                        pass
            if isinstance(val, str):
                val = self._normalize_text(val)
            out[field] = val
        return out

    def _extract_all_content(self, html: str) -> Dict[str, Any]:
        """
        Extract all meaningful content from HTML automatically.
        No selectors needed - extracts common patterns.
        """
        if not html:
            return {}

        soup = BeautifulSoup(html, "lxml")
        extracted = {}

        # 1. Page title (multiple methods)
        title = None
        if soup.title:
            title = soup.title.get_text(strip=True)
        elif soup.find('h1'):
            title = soup.find('h1').get_text(strip=True)
        if title:
            extracted['page_title'] = self._normalize_text(title)

        # 2. Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            extracted['meta_description'] = self._normalize_text(meta_desc['content'])

        # 3. All headings (h1-h3 for comparison)
        headings = []
        for tag in ['h1', 'h2', 'h3']:
            for heading in soup.find_all(tag, limit=5):  # Limit to avoid noise
                text = heading.get_text(strip=True)
                if text and len(text) > 3:
                    headings.append(text)
        if headings:
            extracted['headings'] = ' | '.join(headings[:10])  # First 10

        # 4. Main content paragraphs
        paragraphs = []
        for p in soup.find_all('p', limit=20):
            text = p.get_text(strip=True)
            if text and len(text) > 20:  # Filter out tiny paragraphs
                paragraphs.append(text)
        if paragraphs:
            # First paragraph (often most important)
            extracted['first_paragraph'] = self._normalize_text(paragraphs[0][:500])
            # All paragraph text combined (for similarity comparison)
            extracted['content_text'] = self._normalize_text(' '.join(paragraphs)[:2000])

        # 5. Links (count and sample)
        links = soup.find_all('a', href=True, limit=50)
        extracted['link_count'] = len(links)
        if links:
            # Sample of link texts
            link_texts = [a.get_text(strip=True) for a in links[:10] if a.get_text(strip=True)]
            if link_texts:
                extracted['sample_links'] = ' | '.join(link_texts)

        # 6. Images (count and alt texts)
        images = soup.find_all('img', limit=20)
        extracted['image_count'] = len(images)
        if images:
            alt_texts = [img.get('alt', '').strip() for img in images if img.get('alt')]
            if alt_texts:
                extracted['image_alts'] = ' | '.join(alt_texts[:5])

        # 7. Lists (ul/ol content)
        list_items = []
        for ul in soup.find_all(['ul', 'ol'], limit=10):
            for li in ul.find_all('li', limit=10):
                text = li.get_text(strip=True)
                if text and len(text) > 3:
                    list_items.append(text)
        if list_items:
            extracted['list_items'] = ' | '.join(list_items[:15])

        # 8. Main text content (cleaned body text)
        # Remove script, style, nav, footer, header
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        body = soup.find('body')
        if body:
            body_text = body.get_text(separator=' ', strip=True)
            # Normalize whitespace
            body_text = ' '.join(body_text.split())
            if body_text:
                extracted['body_text'] = self._normalize_text(body_text[:3000])

        # 9. Structured data (JSON-LD, microdata)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        if json_ld_scripts:
            try:
                json_data = json.loads(json_ld_scripts[0].string)
                if isinstance(json_data, dict):
                    # Extract useful fields
                    if '@type' in json_data:
                        extracted['structured_type'] = json_data['@type']
                    if 'name' in json_data:
                        extracted['structured_name'] = str(json_data['name'])
                    if 'headline' in json_data:
                        extracted['structured_headline'] = str(json_data['headline'])
            except:
                pass

        # 10. Word count and character count (for completeness metrics)
        if 'body_text' in extracted:
            words = extracted['body_text'].split()
            extracted['word_count'] = len(words)
            extracted['char_count'] = len(extracted['body_text'])

        # --- NEW: Extracting counts for Redundancy ---
        total_items_count = 0
        unique_items_set = set()

        # Count list items
        for ul in soup.find_all(['ul', 'ol']):
            for li in ul.find_all('li'):
                text = li.get_text(strip=True)
                if text:
                    total_items_count += 1
                    unique_items_set.add(self._normalize_text(text))
        
        # Count links
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            if text:
                total_items_count += 1
                unique_items_set.add(self._normalize_text(text))
                
        extracted['total_items'] = total_items_count
        extracted['unique_items'] = len(unique_items_set)
        
        # --- NEW: Extracting Published Date for Freshness ---
        pub_date = None
        # Try meta tags
        meta_pub = soup.find('meta', attrs={'property': 'article:published_time'}) or \
                   soup.find('meta', attrs={'name': 'date'}) or \
                   soup.find('meta', attrs={'name': 'pubdate'})
        if meta_pub and meta_pub.get('content'):
            pub_date = meta_pub['content']
            
        # Try JSON-LD if not found in meta
        if not pub_date and json_ld_scripts:
            try:
                for script in json_ld_scripts:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if 'datePublished' in data:
                            pub_date = data['datePublished']
                            break
                        elif 'dateModified' in data:
                            pub_date = data['dateModified']
                            break
            except:
                pass
                
        if pub_date:
            extracted['dynamic_published_date'] = pub_date

        return extracted

    def evaluate_single(self, target: Dict[str, Any], method: str, run_res: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a single scraping run against target expectations.

        CRITICAL: If comparison_results exists, MUST use it instead of pseudo_ground_truth
        """
        # Extract raw signals
        ok = bool(run_res.get("ok"))
        data = run_res.get("data", {}) or {}
        error = run_res.get("error")
        timestamps = run_res.get("timestamps", {}) or {}
        observed_at = timestamps.get("observed_at") or now_iso()

        # Get selectors for field extraction
        source_updated_at = target.get("source_updated_at")

        # Extract structured fields from HTML
        extracted_fields = {}
        html = data.get("html")

        if isinstance(html, str) and html.strip():
            selectors = target.get("selectors", {})

            if selectors:
                # Use manual selectors if provided
                extracted_fields = self._extract_with_selectors(html, selectors)
                print(f"[EXTRACTOR] {method}: Using manual selectors: {list(selectors.keys())}")
            else:
                # AUTO MODE: Extract everything automatically
                extracted_fields = self._extract_all_content(html)
                print(f"[EXTRACTOR] {method}: Auto-extracted {len(extracted_fields)} fields")

        # Determine what to use for comparison
        # Priority: extracted_fields > direct data fields (excluding html)
        if extracted_fields:
            fields_to_compare = extracted_fields
        elif data:
            fields_to_compare = {k: v for k, v in data.items() if k != 'html'}
        else:
            fields_to_compare = {}

        # Initialize metrics
        acc = 0.0
        comp = 0.0

        # CRITICAL CHECK: comparison_results takes ABSOLUTE PRIORITY
        comparison_results = target.get('comparison_results')
        pseudo_gt = target.get('pseudo_ground_truth')

        if comparison_results and isinstance(comparison_results, dict) and comparison_results:
            # LEAVE-ONE-OUT: Compare to other scrapers directly
            print(f"[EVALUATOR] {method}: Using comparison_results (leave-one-out)")
            acc, comp = self._evaluate_against_comparison(fields_to_compare, comparison_results)
        elif pseudo_gt and isinstance(pseudo_gt, dict) and pseudo_gt:
            # GLOBAL CONSENSUS: Compare to pseudo ground truth
            print(f"[EVALUATOR] {method}: Using pseudo_ground_truth (global consensus)")
            acc, comp = self._evaluate_against_pseudo_gt(fields_to_compare, pseudo_gt)
        else:
            # FALLBACK: Manual expected fields
            expected_fields = target.get("expected_fields", {})
            if expected_fields:
                print(f"[EVALUATOR] {method}: Using expected_fields (manual)")
                acc, comp = self._evaluate_against_expected(fields_to_compare, expected_fields)
            else:
                print(f"[EVALUATOR] {method}: No evaluation data available")

        # Freshness: try target config first, then dynamic extraction
        dyn_pub_date = extracted_fields.get("dynamic_published_date") if isinstance(extracted_fields, dict) else None
        final_source_updated = source_updated_at or dyn_pub_date
        fresh = Metrics.freshness(final_source_updated, observed_at)

        # Redundancy: use extracted items if available, else fallback to raw data
        ext_total = extracted_fields.get("total_items") if isinstance(extracted_fields, dict) else None
        ext_unique = extracted_fields.get("unique_items") if isinstance(extracted_fields, dict) else None
        
        total_items = ext_total if ext_total is not None else (data.get("total_items") or 0)
        unique_items = ext_unique if ext_unique is not None else (data.get("unique_items") or total_items)
        red = Metrics.redundancy(total_items, unique_items)

        # Throughput
        duration_sec = float(timestamps.get("duration_sec") or 0.0)
        pages_per_sec = 0.0 if duration_sec <= 0 else 1.0 / duration_sec
        thr = Metrics.throughput(pages_per_sec)

        # Robustness
        base_err = 0.0 if ok else 1.0
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


    def _evaluate_against_comparison(
        self, fields: Dict[str, Any], comparison_results: Dict[str, Dict[str, Any]]
    ) -> tuple[float, float]:
        """
        Evaluate fields against other scrapers (leave-one-out).
        
        THIS IS THE KEY METHOD FOR PREVENTING 100% SCORES
        """
        print(f"[COMPARISON] Evaluating against {len(comparison_results)} other scrapers")
        
        # Build union of all fields from comparison scrapers
        all_fields = set()
        for other_method, other_fields in comparison_results.items():
            if isinstance(other_fields, dict):
                all_fields.update(other_fields.keys())
                print(f"[COMPARISON] Scraper '{other_method}' has fields: {list(other_fields.keys())}")
        
        if not all_fields:
            print("[COMPARISON] ERROR: No comparison fields found!")
            return 0.0, 0.0
        
        print(f"[COMPARISON] Total unique fields across scrapers: {len(all_fields)}")
        print(f"[COMPARISON] Current scraper has fields: {list(fields.keys())}")
        
        field_similarities = []
        present_count = 0
        
        for field in all_fields:
            actual_value = fields.get(field)
            
            # Get values from other scrapers for this field
            other_values = []
            for other_method, other_fields in comparison_results.items():
                if not isinstance(other_fields, dict):
                    continue
                other_value = other_fields.get(field)
                if other_value is not None and str(other_value).strip() != "":
                    other_values.append((other_method, other_value))
            
            if not other_values:
                # No other scrapers have this field
                continue
            
            if actual_value is None or str(actual_value).strip() == "":
                # Field missing in current scraper
                print(f"[COMPARISON] Field '{field}': MISSING (0.0 similarity)")
                field_similarities.append(0.0)
            else:
                # Field present - calculate average similarity to other scrapers
                present_count += 1
                
                similarities = []
                for other_method, other_value in other_values:
                    sim = self._value_similarity(actual_value, other_value)
                    similarities.append(sim)
                    print(f"[COMPARISON] Field '{field}': vs {other_method} = {sim:.3f}")
                
                avg_sim = sum(similarities) / len(similarities)
                field_similarities.append(avg_sim)
                print(f"[COMPARISON] Field '{field}': avg similarity = {avg_sim:.3f}")
        
        accuracy = 100.0 * (sum(field_similarities) / len(field_similarities)) if field_similarities else 0.0
        completeness = 100.0 * (present_count / len(all_fields)) if all_fields else 0.0
        
        print(f"[COMPARISON] FINAL - Accuracy: {accuracy:.2f}%, Completeness: {completeness:.2f}%")
        
        return accuracy, completeness

    def _evaluate_against_pseudo_gt(
        self, fields: Dict[str, Any], pseudo_gt: Dict[str, Any]
    ) -> tuple[float, float]:
        """
        Evaluate fields against pseudo ground truth consensus.
        """
        print(f"[PSEUDO-GT] Evaluating against {len(pseudo_gt)} consensus fields")
        
        total_fields = len(pseudo_gt)
        if total_fields == 0:
            return 0.0, 0.0
        
        total_sim = 0.0
        present = 0
        
        for field, expected_value in pseudo_gt.items():
            actual_value = fields.get(field)
            
            if actual_value is None or str(actual_value).strip() == "":
                print(f"[PSEUDO-GT] Field '{field}': MISSING")
                continue
            
            present += 1
            sim = self._value_similarity(actual_value, expected_value)
            total_sim += sim
            print(f"[PSEUDO-GT] Field '{field}': similarity = {sim:.3f}")
        
        accuracy = 100.0 * (total_sim / total_fields)
        completeness = 100.0 * (present / total_fields)
        
        print(f"[PSEUDO-GT] FINAL - Accuracy: {accuracy:.2f}%, Completeness: {completeness:.2f}%")
        
        return accuracy, completeness

    def _evaluate_against_expected(
        self, fields: Dict[str, Any], expected: Dict[str, Any]
    ) -> tuple[float, float]:
        """
        Evaluate against manually provided expected fields.
        """
        total_fields = len(expected)
        if total_fields == 0:
            return 0.0, 0.0
        
        total_sim = 0.0
        present = 0
        
        for field, expected_value in expected.items():
            actual_value = fields.get(field)
            
            if actual_value is None or str(actual_value).strip() == "":
                continue
            
            present += 1
            sim = self._value_similarity(actual_value, expected_value)
            total_sim += sim
        
        accuracy = 100.0 * (total_sim / total_fields)
        completeness = 100.0 * (present / total_fields)
        
        return accuracy, completeness

    def _value_similarity(self, a: Any, b: Any) -> float:
        """
        Calculate similarity between two values in [0.0, 1.0].
        """
        if a is None or b is None:
            return 0.0
        
        sa = str(a).strip()
        sb = str(b).strip()

        # Exact match (case-insensitive)
        if sa.lower() == sb.lower():
            return 1.0

        # Try numeric comparison
        na = self._normalize_number(sa)
        nb = self._normalize_number(sb)
        
        if na is not None and nb is not None:
            if na == nb:
                return 1.0
            diff = abs(na - nb)
            denom = max(abs(na), abs(nb), 1.0)
            sim = max(0.0, 1.0 - diff / denom)
            return sim

        # Token-based similarity for text
        ta = self._tokenize(sa)
        tb = self._tokenize(sb)
        
        if not ta and not tb:
            return 0.0

        # For very long text, use cosine-like measure
        if len(ta) > 8 or len(tb) > 8:
            inter = len(ta & tb)
            if inter == 0:
                return 0.0
            mag = math.sqrt(max(len(ta), 1) * max(len(tb), 1))
            return inter / mag

        # Jaccard similarity
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union if union > 0 else 0.0

    def _normalize_number(self, s: str) -> float:
        """Extract numeric value from string, handling currency symbols."""
        s2 = re.sub(r'[,$€£¥₹\s]', '', s)
        try:
            return float(s2)
        except Exception:
            return None

    def _tokenize(self, s: str) -> set:
        """Split string into normalized tokens."""
        return set(t for t in re.split(r'\W+', s.lower()) if t)


def results_to_csv(results: List[Dict[str, Any]], out_path: Path):
    """Write results to CSV file."""
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
