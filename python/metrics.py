from __future__ import annotations

"""
Metric definitions and normalization to 0-100 scale.

Note: Accuracy and Completeness are computed via pseudo ground truth 
in evaluator.py, not here. This file only contains the other metrics.
"""

from datetime import datetime, timezone
from typing import Optional


def _safe_ratio(num: float, den: float) -> float:
    return 0.0 if den == 0 else num / den


def _normalize_min_is_better(value: float, best: float, worst: float) -> float:
    """Map [best..worst] to [100..0]. Values beyond range are clipped.
    Example: redundancy rate where 0 is ideal.
    """
    if worst == best:
        return 100.0
    value = max(min(value, worst), best)
    return 100.0 * (1.0 - (value - best) / (worst - best))


def _normalize_max_is_better(value: float, worst: float, best: float) -> float:
    """Map [worst..best] to [0..100]. Values beyond range are clipped.
    Example: throughput where higher is better.
    """
    if best == worst:
        return 100.0
    value = max(min(value, best), worst)
    return 100.0 * (value - worst) / (best - worst)


class Metrics:
    """
    Static metrics for scraper evaluation.
    
    Note: accuracy() and completeness() have been removed - these are
    computed directly in evaluator.py using pseudo ground truth comparison.
    """
    
    @staticmethod
    def freshness(source_updated_at: Optional[str], observed_at_iso: Optional[str]) -> float:
        """Timeliness: smaller lag is better.
        We map 0 seconds lag to 100, and 7 days or more to 0, linearly.
        """
        if not source_updated_at or not observed_at_iso:
            return 0.0
        
        try:
            src = datetime.fromisoformat(source_updated_at.replace("Z", "+00:00"))
            obs = datetime.fromisoformat(observed_at_iso.replace("Z", "+00:00"))
        except Exception:
            return 0.0
        
        lag_sec = max(0.0, (obs - src).total_seconds())
        seven_days = 7 * 24 * 3600
        return _normalize_min_is_better(lag_sec, best=0.0, worst=float(seven_days))

    @staticmethod
    def redundancy(total_items: int, unique_items: int) -> float:
        """Lower duplicate rate is better: redundancy_rate = 1 - unique/total.
        We map 0.0 (no redundancy) => 100, and 0.5+ => 0 (half or more duplicates).
        """
        if total_items <= 0:
            return 100.0
        redundancy_rate = max(0.0, 1.0 - _safe_ratio(unique_items, total_items))
        return _normalize_min_is_better(redundancy_rate, best=0.0, worst=0.5)

    @staticmethod
    def throughput(pages_per_sec: float) -> float:
        """Higher is better. We cap normalization at [0..10] pages/sec by default."""
        return _normalize_max_is_better(pages_per_sec, worst=0.0, best=10.0)

    @staticmethod
    def robustness(error_rate: float) -> float:
        """Lower error rate across diverse pages => higher robustness.
        0.0 error => 100, 0.5+ => 0.
        """
        return _normalize_min_is_better(error_rate, best=0.0, worst=0.5)
