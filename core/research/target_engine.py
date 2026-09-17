#!/usr/bin/env python3
"""
target_engine.py — Future Excess Return Target Engine
======================================================
Computes future_excess_return targets for research candidates using:
- Stock simple return from NEXT_SESSION_OPEN to T+N close
- Internal reference benchmark return from Universe(T)
- Excess return = stock_return - reference_return

PIT Isolation:
- Target computation is OUTCOME PHASE only
- Cannot be used as prediction feature at decision_time T
- Requires explicit decision_time context

Canonical reference method: UNIVERSE_MEDIAN
Alternative methods: UNIVERSE_TRIMMED_MEAN, UNIVERSE_MEAN, LEAVE_ONE_OUT_*
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime

from core.research.forward_outcome import compute_one, HORIZONS, UNKNOWN
from core.research.reference_benchmark import ReferenceBenchmark, ReferenceReturnResult
from core.research.research_time_context import PITViolationError


# ---------------------------------------------------------------- Target Status
TARGET_STATUS_VALID = "VALID"
TARGET_STATUS_MISSING_HORIZON = "MISSING_HORIZON"
TARGET_STATUS_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
TARGET_STATUS_PRICE_ERROR = "PRICE_ERROR"
TARGET_STATUS_BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"
TARGET_STATUS_PIT_VIOLATION = "PIT_VIOLATION"
TARGET_STATUS_REFERENCE_COVERAGE_INSUFFICIENT = "REFERENCE_COVERAGE_INSUFFICIENT"
TARGET_STATUS_PRICE_CHAIN_ANOMALY = "PRICE_CHAIN_ANOMALY"


# ---------------------------------------------------------------- Target Schema
@dataclass(frozen=True)
class FutureExcessReturnTarget:
    stock_code: str
    decision_time: str
    horizon: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stock_return: Optional[float]
    benchmark_id: str
    benchmark_version: str
    benchmark_return: Optional[float]
    excess_return: Optional[float]
    reference_method: str
    target_status: str
    price_basis: str
    dataset_version: str
    universe_version: str
    target_version: str
    created_at: str = ""
    notes: str = ""


# ---------------------------------------------------------------- Engine
class TargetEngine:
    """
    Future Excess Return Target Engine.

    Computes stock_return, reference_return, and excess_return for each candidate.
    """

    def __init__(
        self,
        universe_fetcher,
        kline_loader,
        db_path: str,
        *,
        benchmark_id: str = "PIT_RESEARCH_UNIVERSE_REFERENCE",
        benchmark_version: str = "v1",
        price_basis: str = "ADJUSTED_QFQ",
        universe_version: str = "RESEARCH_UNIVERSE_V1",
        dataset_version: str = "v1",
        target_version: str = "v1",
        reference_method: str = "UNIVERSE_MEDIAN",
        min_coverage_ratio: float = 0.5,
        enable_price_discontinuity_guard: bool = False,
    ):
        """
        Args:
            universe_fetcher: Callable[[str], List[Dict]] returning Universe(T)
            kline_loader: Callable[[str, str, str], List[Dict]] loading klines
            db_path: Path to market_cache.db (read-only)
            benchmark_id: Benchmark identifier
            benchmark_version: Benchmark version
            price_basis: Price basis label
            universe_version: Universe snapshot version
            dataset_version: Dataset version
            target_version: Target engine version
            reference_method: UNIVERSE_MEDIAN, UNIVERSE_TRIMMED_MEAN, UNIVERSE_MEAN
            min_coverage_ratio: Minimum valid reference coverage ratio
            enable_price_discontinuity_guard: If True, run price chain anomaly detection
        """
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.db_path = db_path
        self.benchmark_id = benchmark_id
        self.benchmark_version = benchmark_version
        self.price_basis = price_basis
        self.universe_version = universe_version
        self.dataset_version = dataset_version
        self.target_version = target_version
        self.reference_method = reference_method
        self.min_coverage_ratio = min_coverage_ratio
        self.enable_price_discontinuity_guard = enable_price_discontinuity_guard

        self._reference_benchmark = ReferenceBenchmark(
            universe_fetcher=universe_fetcher,
            kline_loader=kline_loader,
            price_basis=price_basis,
            universe_version=universe_version,
            dataset_version=dataset_version,
        )

    def compute_target(self, candidate: Dict[str, Any], decision_time: str) -> FutureExcessReturnTarget:
        """
        Compute future_excess_return target for a single candidate.

        Args:
            candidate: Candidate dict with at least:
                - symbol: stock code
                - candidate_date: decision_time T
                - entry_price: T+1 open price
                - entry_date: T+1 date
            decision_time: Decision time T (ISO date)

        Returns:
            FutureExcessReturnTarget
        """
        symbol = candidate.get("symbol") or candidate.get("stock_code")
        candidate_date = candidate.get("candidate_date") or candidate.get("decision_time")
        entry_price = candidate.get("entry_price")
        entry_date = candidate.get("entry_date") or self._next_trading_day(candidate_date)

        if not symbol or not candidate_date:
            return self._invalid_target(
                symbol, candidate_date, 0, "", "",
                TARGET_STATUS_DATA_UNAVAILABLE, "MISSING_CANDIDATE_FIELDS"
            )

        # PIT enforcement
        if candidate_date > decision_time:
            return self._invalid_target(
                symbol, candidate_date, 0, "", "",
                TARGET_STATUS_PIT_VIOLATION,
                f"candidate_date {candidate_date} > decision_time {decision_time}"
            )

        # Load klines for stock
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            con.execute("PRAGMA query_only=ON")
            klines = TargetEngine._load_klines(con, symbol)
        except Exception as e:
            return self._invalid_target(
                symbol, candidate_date, 0, "", "",
                TARGET_STATUS_DATA_UNAVAILABLE, f"DB_ERROR: {e}"
            )
        finally:
            try:
                con.close()
            except Exception:
                pass

        if not klines:
            return self._invalid_target(
                symbol, candidate_date, 0, "", "",
                TARGET_STATUS_DATA_UNAVAILABLE, "NO_KLINES"
            )

        # Find decision_time index
        decision_idx = TargetEngine._find_index(klines, candidate_date)
        if decision_idx < 0:
            return self._invalid_target(
                symbol, candidate_date, 0, "", "",
                TARGET_STATUS_DATA_UNAVAILABLE, "DECISION_DATE_NOT_IN_KLINES"
            )

        # Derive entry_price from T+1 open if not provided
        if entry_price is None:
            entry_idx = decision_idx + 1
            if entry_idx < len(klines):
                entry_price = klines[entry_idx].get("open")
                entry_date = klines[entry_idx].get("date", entry_date)
            else:
                return self._invalid_target(
                    symbol, candidate_date, 0, "", "",
                    TARGET_STATUS_DATA_UNAVAILABLE, "ENTRY_PRICE_MISSING"
                )

        if entry_price is None or entry_price <= 0:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date or "", "",
                TARGET_STATUS_PRICE_ERROR, "INVALID_ENTRY_PRICE"
            )

        # Compute for each horizon
        results = []
        for horizon in HORIZONS:
            target = self._compute_single_horizon(
                symbol, candidate_date, decision_idx, klines, horizon,
                entry_price, entry_date
            )
            results.append(target)

        # Return the first valid target (for single-candidate API)
        # For batch processing, use compute_targets_batch
        valid_targets = [t for t in results if t.target_status == TARGET_STATUS_VALID]
        if valid_targets:
            return valid_targets[0]
        return results[0]

    def compute_targets_batch(
        self, candidates: List[Dict[str, Any]], decision_time: str
    ) -> List[FutureExcessReturnTarget]:
        """
        Compute targets for a batch of candidates sharing the same decision_time.

        Args:
            candidates: List of candidate dicts
            decision_time: Decision time T

        Returns:
            List of FutureExcessReturnTarget
        """
        # Pre-compute reference returns for all horizons
        reference_returns: Dict[int, Optional[float]] = {}
        reference_valid = {}
        for horizon in HORIZONS:
            ref_result = self._reference_benchmark.compute_reference(
                decision_time, horizon, self.reference_method,
                min_coverage_ratio=self.min_coverage_ratio,
            )
            reference_returns[horizon] = ref_result.reference_return
            reference_valid[horizon] = {
                "valid_count": ref_result.reference_valid_count,
                "total_count": ref_result.reference_total_count,
                "valid_ratio": ref_result.reference_valid_ratio,
            }

        # Compute stock returns
        results = []
        for candidate in candidates:
            target = self._compute_single_candidate(
                candidate, decision_time, reference_returns, reference_valid
            )
            results.append(target)

        return results

    def _compute_single_horizon(
        self, symbol, candidate_date, decision_idx, klines, horizon, entry_price, entry_date
    ) -> FutureExcessReturnTarget:
        """Compute target for a single horizon."""
        # Exit: T+N close
        exit_idx = decision_idx + horizon
        exit_date = klines[exit_idx]["date"] if exit_idx < len(klines) else ""
        exit_price = klines[exit_idx]["close"] if exit_idx < len(klines) else None

        # Validate prices
        if exit_price is None or exit_price <= 0 or entry_price <= 0:
            return self._invalid_target(
                symbol, candidate_date, horizon, entry_date, "",
                TARGET_STATUS_MISSING_HORIZON if exit_price is None else TARGET_STATUS_PRICE_ERROR,
                "INVALID_EXIT_PRICE" if exit_price is not None else "EXIT_PRICE_MISSING"
            )

        # Price discontinuity guard
        if self.enable_price_discontinuity_guard:
            anomaly = self._check_price_chain_anomaly(klines, decision_idx, horizon)
            if anomaly:
                return self._invalid_target(
                    symbol, candidate_date, horizon, entry_date, exit_date,
                    TARGET_STATUS_PRICE_CHAIN_ANOMALY, anomaly
                )

        # Stock return
        stock_return = exit_price / entry_price - 1.0

        # Reference return (cached externally for batch)
        ref_return = self._get_reference_return(candidate_date, horizon)

        # Target status
        if ref_return is None:
            target_status = TARGET_STATUS_BENCHMARK_UNAVAILABLE
            excess_return = None
        else:
            target_status = TARGET_STATUS_VALID
            excess_return = stock_return - ref_return

        now = datetime.utcnow().isoformat() + "Z"
        return FutureExcessReturnTarget(
            stock_code=symbol,
            decision_time=candidate_date,
            horizon=horizon,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            stock_return=round(stock_return, 8),
            benchmark_id=self.benchmark_id,
            benchmark_version=self.benchmark_version,
            benchmark_return=round(ref_return, 8) if ref_return is not None else None,
            excess_return=round(excess_return, 8) if excess_return is not None else None,
            reference_method=self.reference_method,
            target_status=target_status,
            price_basis=self.price_basis,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            target_version=self.target_version,
            created_at=now,
        )

    def _compute_single_candidate(
        self, candidate, decision_time, reference_returns, reference_valid
    ) -> FutureExcessReturnTarget:
        """Compute target for a single candidate across all horizons."""
        symbol = candidate.get("symbol") or candidate.get("stock_code")
        candidate_date = candidate.get("candidate_date") or candidate.get("decision_time")
        entry_price = candidate.get("entry_price")
        entry_date = candidate.get("entry_date") or self._next_trading_day(candidate_date)

        if not symbol or not candidate_date or entry_price is None:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date or "", "",
                TARGET_STATUS_DATA_UNAVAILABLE, "MISSING_CANDIDATE_FIELDS"
            )

        if candidate_date > decision_time:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date, "",
                TARGET_STATUS_PIT_VIOLATION,
                f"candidate_date {candidate_date} > decision_time {decision_time}"
            )

        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            con.execute("PRAGMA query_only=ON")
            klines = TargetEngine._load_klines(con, symbol)
        except Exception as e:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date, "",
                TARGET_STATUS_DATA_UNAVAILABLE, f"DB_ERROR: {e}"
            )
        finally:
            try:
                con.close()
            except Exception:
                pass

        if not klines:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date, "",
                TARGET_STATUS_DATA_UNAVAILABLE, "NO_KLINES"
            )

        decision_idx = TargetEngine._find_index(klines, candidate_date)
        if decision_idx < 0:
            return self._invalid_target(
                symbol, candidate_date, 0, entry_date, "",
                TARGET_STATUS_DATA_UNAVAILABLE, "DECISION_DATE_NOT_IN_KLINES"
            )

        # Compute for each horizon
        targets = []
        for horizon in HORIZONS:
            target = self._compute_single_horizon(
                symbol, candidate_date, decision_idx, klines, horizon,
                entry_price, entry_date
            )
            targets.append(target)

        # Return first valid target
        valid_targets = [t for t in targets if t.target_status == TARGET_STATUS_VALID]
        if valid_targets:
            return valid_targets[0]
        return targets[0]

    def _get_reference_return(self, decision_time: str, horizon: int) -> Optional[float]:
        """Get cached reference return for a given decision_time and horizon."""
        # This is a simple cache; for batch processing, pre-compute externally
        if not hasattr(self, "_ref_cache"):
            self._ref_cache: Dict[tuple, Optional[float]] = {}
        key = (decision_time, horizon)
        if key not in self._ref_cache:
            ref_result = self._reference_benchmark.compute_reference(
                decision_time, horizon, self.reference_method,
                min_coverage_ratio=self.min_coverage_ratio,
            )
            self._ref_cache[key] = ref_result.reference_return
        return self._ref_cache[key]

    def _invalid_target(
        self, symbol, decision_time, horizon, entry_date, exit_date, status, notes
    ) -> FutureExcessReturnTarget:
        """Create an invalid/error target."""
        now = datetime.utcnow().isoformat() + "Z"
        return FutureExcessReturnTarget(
            stock_code=symbol or "",
            decision_time=decision_time or "",
            horizon=horizon,
            entry_date=entry_date or "",
            exit_date=exit_date or "",
            entry_price=0.0,
            exit_price=0.0,
            stock_return=None,
            benchmark_id=self.benchmark_id,
            benchmark_version=self.benchmark_version,
            benchmark_return=None,
            excess_return=None,
            reference_method=self.reference_method,
            target_status=status,
            price_basis=self.price_basis,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            target_version=self.target_version,
            created_at=now,
            notes=notes,
        )

    def _check_price_chain_anomaly(
        self, klines: List[Dict], decision_idx: int, horizon: int
    ) -> Optional[str]:
        """
        Check for price chain anomalies in the forward window.

        Returns:
            Anomaly description string if detected, None otherwise
        """
        if len(klines) < 2:
            return None

        # Check 2023-12-05 style boundary discontinuity
        for i in range(max(1, decision_idx), min(len(klines), decision_idx + horizon + 1)):
            prev_close = klines[i - 1].get("close")
            curr_close = klines[i].get("close")
            if prev_close and curr_close and prev_close > 0 and curr_close > 0:
                jump = abs(curr_close / prev_close - 1.0)
                if jump > 0.30:  # >30% intraday jump
                    # Check if it's a known boundary date or suspension
                    # For now, flag as potential anomaly
                    return (
                        f"PRICE_JUMP_ANOMALY: {klines[i]['date']} close jump {jump:.2%} "
                        f"from {klines[i-1]['date']}"
                    )

        # Check OHLC violations
        for i in range(decision_idx, min(len(klines), decision_idx + horizon + 1)):
            k = klines[i]
            high = k.get("high")
            low = k.get("low")
            close = k.get("close")
            open_ = k.get("open")
            if high is not None and low is not None and low > high:
                return f"OHLC_VIOLATION: {k['date']} low {low} > high {high}"
            if close is not None and close > 0:
                if high is not None and close > high:
                    return f"CLOSE_ABOVE_HIGH: {k['date']} close {close} > high {high}"
                if low is not None and close < low:
                    return f"CLOSE_BELOW_LOW: {k['date']} close {close} < low {low}"

        return None

    @staticmethod
    def _load_klines(con, symbol: str) -> List[Dict]:
        """Load klines for a symbol, ordered by date. Deduplicate by date keeping first."""
        base = symbol.split(".")[0] if "." in symbol else symbol
        candidates = [symbol, base]
        for sfx in (".SH", ".SZ", ".BJ"):
            candidates.append(base + sfx)

        seen = set()
        seen_dates = set()
        rows = []
        for code in candidates:
            if code in seen:
                continue
            seen.add(code)
            try:
                cur = con.execute(
                    "SELECT date, open, close, high, low FROM klines WHERE code=? ORDER BY date",
                    (code,),
                )
                for r in cur.fetchall():
                    if r[0] not in seen_dates:
                        seen_dates.add(r[0])
                        rows.append({
                            "date": r[0],
                            "open": r[1],
                            "close": r[2],
                            "high": r[3],
                            "low": r[4],
                        })
            except sqlite3.Error:
                continue
        return rows

    @staticmethod
    def _find_index(klines: List[Dict], date: str) -> int:
        """Find index of date in klines list."""
        for i, k in enumerate(klines):
            if k["date"] == date:
                return i
        return -1

    @staticmethod
    def _next_trading_day(date: str) -> Optional[str]:
        """Placeholder for next trading day calculation."""
        # In production, use a trading calendar
        return None
