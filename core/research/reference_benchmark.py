#!/usr/bin/env python3
"""
reference_benchmark.py — Internal PIT Research Universe Reference Benchmark
==========================================================================
Computes universe-relative reference returns from Universe(T) using only
PIT-safe information at decision_time T.

Supported methods:
- UNIVERSE_MEDIAN: equal-weight median of valid stock returns in Universe(T)
- UNIVERSE_TRIMMED_MEAN: trimmed mean of valid stock returns
- UNIVERSE_MEAN: equal-weight mean of valid stock returns

All methods use the same entry/exit semantics as stock targets:
- entry = T+1 open
- exit = T+N close
- simple return = exit / entry - 1

PIT Safety:
- Universe(T) is fully determined at decision_time T
- Future returns are only used for outcome/target, never for universe construction
- No look-ahead bias in reference construction

Naming:
- UNIVERSE_REFERENCE_RETURN (never CSI300_RETURN, never MARKET_INDEX_RETURN)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


@dataclass(frozen=True)
class ReferenceReturnResult:
    """Result of reference benchmark computation for a single decision_time + horizon."""
    decision_time: str
    horizon: int
    reference_method: str
    reference_return: Optional[float]
    reference_valid_count: int
    reference_total_count: int
    reference_valid_ratio: float
    universe_version: str
    dataset_version: str
    price_basis: str
    notes: str = ""


class ReferenceBenchmark:
    """Compute internal reference benchmark returns from Universe(T)."""

    def __init__(
        self,
        universe_fetcher,
        kline_loader,
        price_basis: str = "ADJUSTED_QFQ",
        universe_version: str = "RESEARCH_UNIVERSE_V1",
        dataset_version: str = "v1",
    ):
        """
        Args:
            universe_fetcher: Callable[[str], List[Dict]] that returns Universe(T) as list of stock records.
                Each record must contain at least 'code' or 'symbol'.
            kline_loader: Callable[[str, str, str], List[Dict]] that loads klines for a symbol.
                Signature: kline_loader(symbol, start_date, end_date) -> List[Dict]
                Each kline dict must contain 'date', 'open', 'close'.
            price_basis: Price basis label, e.g. "ADJUSTED_QFQ"
            universe_version: Universe snapshot version identifier
            dataset_version: Dataset version identifier
        """
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.price_basis = price_basis
        self.universe_version = universe_version
        self.dataset_version = dataset_version

    def compute_reference(
        self,
        decision_time: str,
        horizon: int,
        method: str = "UNIVERSE_MEDIAN",
        *,
        trim_ratio: float = 0.1,
        min_coverage_ratio: float = 0.5,
    ) -> ReferenceReturnResult:
        """
        Compute reference return for Universe(T) over a given horizon.

        Args:
            decision_time: Decision date T (ISO format YYYY-MM-DD)
            horizon: Number of trading days (5, 10, or 20)
            method: One of UNIVERSE_MEDIAN, UNIVERSE_TRIMMED_MEAN, UNIVERSE_MEAN
            trim_ratio: Fraction to trim from each tail for trimmed mean (default 10%)
            min_coverage_ratio: Minimum valid ratio to consider reference usable

        Returns:
            ReferenceReturnResult with reference_return and coverage stats

        Notes:
            - If reference_valid_ratio < min_coverage_ratio, reference_return is None
              and notes indicate insufficient coverage.
            - Returns are simple returns: close[T+N] / open[T+1] - 1
            - Only stocks with valid entry and exit prices are included.
        """
        if method not in {"UNIVERSE_MEDIAN", "UNIVERSE_TRIMMED_MEAN", "UNIVERSE_MEAN"}:
            raise ValueError(f"Unsupported reference method: {method}")

        universe = self.universe_fetcher(decision_time)
        if not universe:
            return ReferenceReturnResult(
                decision_time=decision_time,
                horizon=horizon,
                reference_method=method,
                reference_return=None,
                reference_valid_count=0,
                reference_total_count=0,
                reference_valid_ratio=0.0,
                universe_version=self.universe_version,
                dataset_version=self.dataset_version,
                price_basis=self.price_basis,
                notes="EMPTY_UNIVERSE",
            )

        returns: List[float] = []
        for stock in universe:
            symbol = stock.get("code") or stock.get("symbol")
            if not symbol:
                continue

            entry_price, exit_price = self._get_entry_exit_prices(
                symbol, decision_time, horizon
            )
            if entry_price is None or exit_price is None:
                continue
            if entry_price <= 0 or exit_price <= 0:
                continue

            ret = exit_price / entry_price - 1.0
            returns.append(ret)

        total_count = len(universe)
        valid_count = len(returns)
        valid_ratio = valid_count / total_count if total_count > 0 else 0.0

        if valid_count == 0 or valid_ratio < min_coverage_ratio:
            return ReferenceReturnResult(
                decision_time=decision_time,
                horizon=horizon,
                reference_method=method,
                reference_return=None,
                reference_valid_count=valid_count,
                reference_total_count=total_count,
                reference_valid_ratio=valid_ratio,
                universe_version=self.universe_version,
                dataset_version=self.dataset_version,
                price_basis=self.price_basis,
                notes=f"INSUFFICIENT_COVERAGE: valid_ratio={valid_ratio:.2%}",
            )

        # Compute reference statistic
        if method == "UNIVERSE_MEDIAN":
            ref_return = float(statistics.median(returns))
        elif method == "UNIVERSE_MEAN":
            ref_return = float(statistics.mean(returns))
        elif method == "UNIVERSE_TRIMMED_MEAN":
            ref_return = self._trimmed_mean(returns, trim_ratio)
        else:
            # Should not reach here due to validation above
            raise ValueError(f"Unsupported reference method: {method}")

        return ReferenceReturnResult(
            decision_time=decision_time,
            horizon=horizon,
            reference_method=method,
            reference_return=round(ref_return, 8),
            reference_valid_count=valid_count,
            reference_total_count=total_count,
            reference_valid_ratio=valid_ratio,
            universe_version=self.universe_version,
            dataset_version=self.dataset_version,
            price_basis=self.price_basis,
            notes="",
        )

    def compute_leave_one_out(
        self,
        decision_time: str,
        horizon: int,
        target_symbol: str,
        method: str = "UNIVERSE_MEDIAN",
        *,
        trim_ratio: float = 0.1,
        min_coverage_ratio: float = 0.5,
    ) -> ReferenceReturnResult:
        """
        Compute leave-one-out reference return for a specific stock.

        The target stock is excluded from the universe before computing the reference.

        Args:
            decision_time: Decision date T
            horizon: Number of trading days
            target_symbol: Stock symbol to exclude from reference
            method: Reference method
            trim_ratio: Trim ratio for trimmed mean
            min_coverage_ratio: Minimum valid coverage ratio

        Returns:
            ReferenceReturnResult with leave-one-out reference_return
        """
        universe = self.universe_fetcher(decision_time)
        if not universe:
            return ReferenceReturnResult(
                decision_time=decision_time,
                horizon=horizon,
                reference_method=f"LEAVE_ONE_OUT_{method}",
                reference_return=None,
                reference_valid_count=0,
                reference_total_count=0,
                reference_valid_ratio=0.0,
                universe_version=self.universe_version,
                dataset_version=self.dataset_version,
                price_basis=self.price_basis,
                notes="EMPTY_UNIVERSE",
            )

        # Exclude target stock
        filtered_universe = [
            s for s in universe
            if (s.get("code") or s.get("symbol")) != target_symbol
        ]

        returns: List[float] = []
        for stock in filtered_universe:
            symbol = stock.get("code") or stock.get("symbol")
            if not symbol:
                continue

            entry_price, exit_price = self._get_entry_exit_prices(
                symbol, decision_time, horizon
            )
            if entry_price is None or exit_price is None:
                continue
            if entry_price <= 0 or exit_price <= 0:
                continue

            returns.append(exit_price / entry_price - 1.0)

        total_count = len(filtered_universe)
        valid_count = len(returns)
        valid_ratio = valid_count / total_count if total_count > 0 else 0.0

        if valid_count == 0 or valid_ratio < min_coverage_ratio:
            return ReferenceReturnResult(
                decision_time=decision_time,
                horizon=horizon,
                reference_method=f"LEAVE_ONE_OUT_{method}",
                reference_return=None,
                reference_valid_count=valid_count,
                reference_total_count=total_count,
                reference_valid_ratio=valid_ratio,
                universe_version=self.universe_version,
                dataset_version=self.dataset_version,
                price_basis=self.price_basis,
                notes=f"INSUFFICIENT_COVERAGE: valid_ratio={valid_ratio:.2%}",
            )

        if method == "UNIVERSE_MEDIAN":
            ref_return = float(statistics.median(returns))
        elif method == "UNIVERSE_MEAN":
            ref_return = float(statistics.mean(returns))
        elif method == "UNIVERSE_TRIMMED_MEAN":
            ref_return = self._trimmed_mean(returns, trim_ratio)
        else:
            raise ValueError(f"Unsupported reference method: {method}")

        return ReferenceReturnResult(
            decision_time=decision_time,
            horizon=horizon,
            reference_method=f"LEAVE_ONE_OUT_{method}",
            reference_return=round(ref_return, 8),
            reference_valid_count=valid_count,
            reference_total_count=total_count,
            reference_valid_ratio=valid_ratio,
            universe_version=self.universe_version,
            dataset_version=self.dataset_version,
            price_basis=self.price_basis,
            notes="",
        )

    def compare_inclusive_vs_leave_one_out(
        self,
        decision_time: str,
        horizon: int,
        method: str = "UNIVERSE_MEDIAN",
        *,
        trim_ratio: float = 0.1,
        min_coverage_ratio: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Compare inclusive reference vs leave-one-out reference for all stocks in Universe(T).

        Returns:
            Dict with:
                - abs_differences: list of absolute differences
                - max_abs_difference: maximum absolute difference
                - mean_abs_difference: mean absolute difference
                - rank_correlation: Spearman-like rank correlation (if scipy available)
                - correlation: Pearson correlation (if numpy available)
                - sample_size: number of stocks with both values computed
        """
        universe = self.universe_fetcher(decision_time)
        if not universe:
            return {
                "abs_differences": [],
                "max_abs_difference": None,
                "mean_abs_difference": None,
                "rank_correlation": None,
                "correlation": None,
                "sample_size": 0,
            }

        inclusive_values: Dict[str, float] = {}
        loo_values: Dict[str, float] = {}

        # Pre-compute inclusive reference
        inclusive_result = self.compute_reference(
            decision_time, horizon, method,
            trim_ratio=trim_ratio,
            min_coverage_ratio=min_coverage_ratio,
        )
        if inclusive_result.reference_return is None:
            return {
                "abs_differences": [],
                "max_abs_difference": None,
                "mean_abs_difference": None,
                "rank_correlation": None,
                "correlation": None,
                "sample_size": 0,
                "notes": "Inclusive reference unavailable",
            }

        for stock in universe:
            symbol = stock.get("code") or stock.get("symbol")
            if not symbol:
                continue

            # Compute inclusive stock return
            entry_price, exit_price = self._get_entry_exit_prices(
                symbol, decision_time, horizon
            )
            if entry_price is None or exit_price is None or entry_price <= 0 or exit_price <= 0:
                continue
            inclusive_values[symbol] = exit_price / entry_price - 1.0

        # Compute leave-one-out reference for each stock
        for stock in universe:
            symbol = stock.get("code") or stock.get("symbol")
            if not symbol or symbol not in inclusive_values:
                continue

            loo_result = self.compute_leave_one_out(
                decision_time, horizon, symbol, method,
                trim_ratio=trim_ratio,
                min_coverage_ratio=min_coverage_ratio,
            )
            if loo_result.reference_return is not None:
                loo_values[symbol] = loo_result.reference_return

        # Compare
        common_symbols = [s for s in inclusive_values if s in loo_values]
        if not common_symbols:
            return {
                "abs_differences": [],
                "max_abs_difference": None,
                "mean_abs_difference": None,
                "rank_correlation": None,
                "correlation": None,
                "sample_size": 0,
                "notes": "No common stocks with both inclusive and LOO values",
            }

        abs_differences = [abs(inclusive_values[s] - loo_values[s]) for s in common_symbols]
        max_abs_diff = max(abs_differences)
        mean_abs_diff = sum(abs_differences) / len(abs_differences)

        result: Dict[str, Any] = {
            "abs_differences": abs_differences,
            "max_abs_difference": max_abs_diff,
            "mean_abs_difference": mean_abs_diff,
            "sample_size": len(common_symbols),
        }

        # Try to compute correlations if libraries available
        try:
            import numpy as np
            inc_array = [inclusive_values[s] for s in common_symbols]
            loo_array = [loo_values[s] for s in common_symbols]
            if len(set(inc_array)) > 1 and len(set(loo_array)) > 1:
                corr = float(np.corrcoef(inc_array, loo_array)[0, 1])
                result["correlation"] = corr
        except ImportError:
            pass
        except Exception:
            pass

        # Rank correlation
        try:
            from scipy.stats import spearmanr
            inc_array = [inclusive_values[s] for s in common_symbols]
            loo_array = [loo_values[s] for s in common_symbols]
            if len(set(inc_array)) > 1 and len(set(loo_array)) > 1:
                corr, _ = spearmanr(inc_array, loo_array)
                result["rank_correlation"] = float(corr)
        except ImportError:
            pass
        except Exception:
            pass

        return result

    def _get_entry_exit_prices(
        self, symbol: str, decision_time: str, horizon: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get entry and exit prices for a stock.

        Entry: T+1 open (next trading day open)
        Exit: T+N close (Nth trading day close after T)

        Returns:
            Tuple of (entry_price, exit_price). Either can be None if not available.
        """
        if self.kline_loader is None:
            return None, None

        try:
            # Load all available klines for this symbol to ensure T+N is covered
            klines = self.kline_loader(symbol, "", "")
        except Exception:
            return None, None

        if not klines:
            return None, None

        # Find decision_time index
        decision_idx = -1
        for i, k in enumerate(klines):
            if k["date"] == decision_time:
                decision_idx = i
                break

        if decision_idx < 0:
            return None, None

        # Entry: T+1 open
        entry_idx = decision_idx + 1
        if entry_idx >= len(klines):
            return None, None

        entry_price = klines[entry_idx].get("open")
        if entry_price is None or entry_price <= 0:
            return None, None

        # Exit: T+N close
        exit_idx = decision_idx + horizon
        if exit_idx >= len(klines):
            return None, None

        exit_price = klines[exit_idx].get("close")
        if exit_price is None or exit_price <= 0:
            return None, None

        return float(entry_price), float(exit_price)

    @staticmethod
    def _trimmed_mean(values: List[float], trim_ratio: float) -> float:
        """
        Compute trimmed mean.

        Args:
            values: List of numeric values
            trim_ratio: Fraction to trim from each tail (0.0 to 0.5)

        Returns:
            Trimmed mean
        """
        if not values:
            return 0.0
        if trim_ratio <= 0.0:
            return float(statistics.mean(values))
        if trim_ratio >= 0.5:
            return float(statistics.median(values))

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        trim_count = int(n * trim_ratio)
        if trim_count == 0:
            return float(statistics.mean(sorted_vals))

        trimmed = sorted_vals[trim_count : n - trim_count]
        if not trimmed:
            return float(statistics.median(sorted_vals))
        return float(statistics.mean(trimmed))
