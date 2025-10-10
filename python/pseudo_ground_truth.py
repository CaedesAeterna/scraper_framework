#!/usr/bin/env python3
"""
Pseudo Ground Truth Builder - Creates reference data from multi-scraper consensus.
Implements cross-validation and confidence scoring without manual ground truth.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import re
import hashlib
from .html_utils import normalize_html_text

logger = logging.getLogger(__name__)


class PseudoGroundTruthBuilder:
    """
    Builds pseudo ground truth from multiple scraper results through consensus.
    Uses statistical confidence and pattern recognition.
    """
    
    def __init__(self, confidence_threshold: float = 0.6, min_consensus: int = 2):
        """
        Initialize pseudo ground truth builder.
        
        Args:
            confidence_threshold: Minimum confidence for accepting consensus value
            min_consensus: Minimum number of scrapers that must agree
        """
        self.confidence_threshold = confidence_threshold
        self.min_consensus = min_consensus
        self.field_patterns = {
            'title': r'^.{1,200}$',  # Reasonable title length
            'price': r'[\d,]+\.?\d*\s*[$€£¥₹]|^\d+\.?\d*$',
            'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            'phone': r'[\+\d][\d\s\-\(\)]{7,20}\d',
            'date': r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|\d{1,2}\s\w{3,}\s\d{4}',
            'url': r'https?://[^\s]+',
            'number': r'^\d+\.?\d*$'
        }
    
    def build_consensus(self, results_by_method: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build consensus pseudo ground truth from multiple scraper results.
        
        Args:
            results_by_method: Dict mapping method name to scraper result
            
        Returns:
            Dict with consensus data, confidence scores, and metadata
        """
        logger.info(f"Building consensus from {len(results_by_method)} scrapers")
        
        # Filter successful results
        successful_results = {
            method: result for method, result in results_by_method.items()
            if result.get('ok', False) and result.get('data')
        }
        
        # Need at least min_consensus successful results
        if len(successful_results) < self.min_consensus:
            logger.warning(f"Insufficient successful results: {len(successful_results)} < {self.min_consensus}")
            return self._empty_consensus()
        
        # Extract field values from all successful scrapers
        field_values = self._collect_field_values(successful_results)
        
        # Build consensus for each field
        consensus_data = {}
        confidence_scores = {}
        field_metadata = {}
        
        # Determine consensus per field
        for field, values in field_values.items():
            consensus_value, confidence, metadata = self._determine_consensus_value(field, values)
            
            # Accept if confidence meets threshold
            if confidence >= self.confidence_threshold:
                consensus_data[field] = consensus_value
                confidence_scores[field] = confidence
                field_metadata[field] = metadata
        
        # Calculate overall consensus quality
        overall_confidence = self._calculate_overall_confidence(confidence_scores)
        
        # Compile final result 
        return {
            'consensus_data': consensus_data,
            'confidence_scores': confidence_scores,
            'field_metadata': field_metadata,
            'overall_confidence': overall_confidence,
            'scrapers_used': list(successful_results.keys()),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'stats': {
                'total_fields': len(field_values),
                'consensus_fields': len(consensus_data),
                'coverage': len(consensus_data) / max(len(field_values), 1)
            }
        }
    
    
    def _collect_field_values(self, successful_results: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Collect all field values from successful scraper results."""
        field_values = defaultdict(list)
        
        for method, result in successful_results.items():
            data = result.get('data', {})
            
            # Get both direct data and extracted fields
            extracted_fields = result.get('raw', {}).get('extracted_fields', {})
            all_fields = {**data, **extracted_fields}
            # Also include normalized page text derived from HTML if present
            html_blob = data.get('html')
            if isinstance(html_blob, str) and html_blob.strip():
                pt = normalize_html_text(html_blob)
                if pt:
                    all_fields['page_text'] = pt
            
            for field, value in all_fields.items():
                if value is not None and str(value).strip():  # Skip empty values
                    field_values[field].append({
                        'method': method,
                        'value': str(value).strip(),
                        'raw_value': value,
                        'source': 'extracted' if field in extracted_fields else 'direct'
                    })
        
        return field_values
    
    def _determine_consensus_value(self, field: str, values: List[Dict[str, Any]]) -> Tuple[str, float, Dict[str, Any]]:
        """
        Determine consensus value for a field using multiple strategies.
        
        Returns:
            (consensus_value, confidence_score, metadata)
        """
        if not values:
            return "", 0.0, {}
        
        # Strategy 1: Simple majority vote
        value_counts = Counter([v['value'] for v in values])
        most_common_value, count = value_counts.most_common(1)[0]
        simple_confidence = count / len(values)
        
        # Strategy 2: Weighted by scraper reliability (if available)
        weighted_confidence = self._calculate_weighted_confidence(values, most_common_value)
        
        # Strategy 3: Pattern-based validation
        pattern_confidence = self._validate_against_patterns(field, most_common_value)
        
        # Strategy 4: Consistency check
        consistency_score = self._check_value_consistency(values)
        
        # Combine strategies
        final_confidence = (
            simple_confidence * 0.4 +
            weighted_confidence * 0.3 +
            pattern_confidence * 0.2 +
            consistency_score * 0.1
        )
        
        metadata = {
            'strategy_scores': {
                'simple': simple_confidence,
                'weighted': weighted_confidence,
                'pattern': pattern_confidence,
                'consistency': consistency_score
            },
            'value_distribution': dict(value_counts),
            'total_votes': len(values),
            'agreeing_scrapers': [v['method'] for v in values if v['value'] == most_common_value]
        }
        
        return most_common_value, final_confidence, metadata
    
    def _calculate_weighted_confidence(self, values: List[Dict[str, Any]], consensus_value: str) -> float:
        """Calculate confidence weighted by scraper historical performance."""
        # For now, equal weights since we don't have historical data
        # In future versions, this could use stored scraper performance metrics
        agreeing_count = sum(1 for v in values if v['value'] == consensus_value)
        return agreeing_count / len(values)
    
    def _validate_against_patterns(self, field: str, value: str) -> float:
        """Validate value against expected patterns for the field type."""
        # Try to auto-detect field type from name
        detected_type = self._detect_field_type(field, value)
        
        if detected_type in self.field_patterns:
            pattern = self.field_patterns[detected_type]
            if re.search(pattern, value, re.IGNORECASE):
                return 1.0
            else:
                return 0.3  # Pattern mismatch, but not complete failure
        
        # No specific pattern, assume valid
        return 0.8
    
    def _detect_field_type(self, field_name: str, value: str) -> str:
        """Detect field type from name and value."""
        field_lower = field_name.lower()
        
        # Common field name patterns
        if any(keyword in field_lower for keyword in ['title', 'name', 'heading']):
            return 'title'
        elif any(keyword in field_lower for keyword in ['price', 'cost', 'amount']):
            return 'price'
        elif any(keyword in field_lower for keyword in ['email', 'mail']):
            return 'email'
        elif any(keyword in field_lower for keyword in ['phone', 'tel', 'mobile']):
            return 'phone'
        elif any(keyword in field_lower for keyword in ['date', 'time', 'when']):
            return 'date'
        elif any(keyword in field_lower for keyword in ['url', 'link', 'href']):
            return 'url'
        elif re.match(r'^\d+\.?\d*$', value):
            return 'number'
        
        return 'text'  # Default
    
    def _check_value_consistency(self, values: List[Dict[str, Any]]) -> float:
        """Check consistency of values (similar values get higher scores)."""
        unique_values = set(v['value'] for v in values)
        
        if len(unique_values) == 1:
            return 1.0  # Perfect consistency
        
        # Check for similar values (minor differences)
        similarity_score = self._calculate_value_similarity(list(unique_values))
        return similarity_score
    
    def _calculate_value_similarity(self, values: List[str]) -> float:
        """Calculate similarity between different values."""
        if len(values) <= 1:
            return 1.0
        
        # Use edit distance for similarity
        total_comparisons = 0
        total_similarity = 0
        
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                similarity = self._string_similarity(values[i], values[j])
                total_similarity += similarity
                total_comparisons += 1
        
        return total_similarity / total_comparisons if total_comparisons > 0 else 0
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings (0-1)."""
        if s1 == s2:
            return 1.0
        
        # Simple Jaccard similarity with character bigrams
        def get_bigrams(s):
            return set(s[i:i+2] for i in range(len(s)-1))
        
        bigrams1 = get_bigrams(s1.lower())
        bigrams2 = get_bigrams(s2.lower())
        
        if not bigrams1 and not bigrams2:
            return 1.0
        
        intersection = len(bigrams1 & bigrams2)
        union = len(bigrams1 | bigrams2)
        
        return intersection / union if union > 0 else 0
    
    def _calculate_overall_confidence(self, confidence_scores: Dict[str, float]) -> float:
        """Calculate overall confidence across all consensus fields."""
        if not confidence_scores:
            return 0.0
        
        return sum(confidence_scores.values()) / len(confidence_scores)
    
    def _empty_consensus(self) -> Dict[str, Any]:
        """Return empty consensus structure."""
        return {
            'consensus_data': {},
            'confidence_scores': {},
            'field_metadata': {},
            'overall_confidence': 0.0,
            'scrapers_used': [],
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'stats': {'total_fields': 0, 'consensus_fields': 0, 'coverage': 0}
        }


# Cache functionality removed. Pseudo-ground-truth is built fresh on every run.


def create_pseudo_ground_truth_from_results(results_by_method: Dict[str, Dict[str, Any]], 
                                          confidence_threshold: float = 0.6) -> Dict[str, Any]:
    """
    Convenience function to create pseudo ground truth from scraper results.
    
    Args:
        results_by_method: Dict mapping method name to scraper result
        confidence_threshold: Minimum confidence for consensus
        
    Returns:
        Pseudo ground truth data
    """
    builder = PseudoGroundTruthBuilder(confidence_threshold=confidence_threshold)
    return builder.build_consensus(results_by_method)