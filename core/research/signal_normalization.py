#!/usr/bin/env python3
"""
signal_normalization.py — Signal Normalization Layer
=====================================================
Cross-sectional normalization for strategy signals.
"""

from __future__ import annotations

import statistics
from typing import List, Optional


class NormalizationLayer:
    """Cross-sectional signal normalization."""

    def __init__(self, method: str = "percentile"):
        self.method = method

    def normalize(self, signals: List) -> List:
        if not signals:
            return signals
        if self.method == "percentile":
            return self._percentile_normalize(signals)
        elif self.method == "zscore":
            return self._zscore_normalize(signals)
        else:
            return signals

    def _percentile_normalize(self, signals: List) -> List:
        """Rank-based percentile normalization [0, 1]."""
        scores = [s.raw_score for s in signals]
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        normalized = []
        for s in signals:
            idx = sorted_scores.index(s.raw_score)
            norm_score = idx / max(n - 1, 1)
            normalized.append(self._replace_signal(s, norm_score))
        return normalized

    def _zscore_normalize(self, signals: List) -> List:
        """Z-score normalization."""
        scores = [s.raw_score for s in signals]
        mean = statistics.mean(scores)
        stdev = statistics.pstdev(scores) if len(scores) > 1 else 1.0
        stdev = max(stdev, 1e-12)
        normalized = []
        for s in signals:
            norm_score = (s.raw_score - mean) / stdev
            normalized.append(self._replace_signal(s, norm_score))
        return normalized

    @staticmethod
    def _replace_signal(signal, normalized_score: float):
        from dataclasses import replace
        return replace(signal, normalized_score=normalized_score)
