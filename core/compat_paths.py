"""
Stock Work compatibility path layer.

Purpose:
    Preserve legacy import/API expectations while routing
    all path resolution through StockPathResolver.

This module must not:
- contain machine-specific absolute paths
- reference ~/.hermes directly
- move/delete files
- perform database migration
"""

from __future__ import annotations

from .path_resolver import get_path_resolver


resolver = get_path_resolver()


# ------------------------------------------------------------
# Canonical DB aliases
# ------------------------------------------------------------

MARKET_DB = resolver.market_cache_db

SIMULATION_DB = resolver.simulation_db

CF_CACHE_DB = resolver.cf_cache_db

WESTOCK_CACHE_DB = resolver.westock_cache_db

INTRADAY_CACHE_DB = resolver.intraday_cache_db

LHB_CACHE_DB = resolver.lhb_cache_db

NEWS_CACHE_DB = resolver.news_cache_db

RECOMMENDATION_POOL_DB = resolver.recommendation_pool_db

RECOMMENDATION_OUTCOMES_DB = resolver.recommendation_outcomes_db

REAL_PORTFOLIO_HISTORY_DB = resolver.runtime / "real_portfolio_history.db"


# ------------------------------------------------------------
# Explicit aliases for legacy naming variants
# ------------------------------------------------------------

MARKET_CACHE_DB = resolver.market_cache_db

SIMULATION_DB_PATH = resolver.simulation_db

WESTOCK_DB = resolver.westock_cache_db

INTRADAY_DB = resolver.intraday_cache_db

LHB_DB = resolver.lhb_cache_db

NEWS_DB = resolver.news_cache_db

RECOMMENDATION_DB = resolver.recommendation_pool_db


def get_db_path(name: str):
    """
    Generic compatibility resolver.

    This function is intentionally narrow.
    It maps known logical DB names to canonical paths.
    """

    mapping = {
        "market": resolver.market_cache_db,
        "market_cache": resolver.market_cache_db,
        "market_cache.db": resolver.market_cache_db,

        "simulation": resolver.simulation_db,
        "simulation.db": resolver.simulation_db,
        "simulation_test": resolver.simulation_test_db,
        "simulation_test.db": resolver.simulation_test_db,

        "cf_cache": resolver.cf_cache_db,
        "cf_cache.db": resolver.cf_cache_db,

        "westock": resolver.westock_cache_db,
        "westock_cache": resolver.westock_cache_db,
        "westock_cache.db": resolver.westock_cache_db,

        "intraday": resolver.intraday_cache_db,
        "intraday_cache": resolver.intraday_cache_db,
        "intraday_cache.db": resolver.intraday_cache_db,

        "lhb": resolver.lhb_cache_db,
        "lhb_cache": resolver.lhb_cache_db,
        "lhb_cache.db": resolver.lhb_cache_db,

        "news": resolver.news_cache_db,
        "news_cache": resolver.news_cache_db,
        "news_cache.db": resolver.news_cache_db,

        "recommendation_pool": (
            resolver.recommendation_pool_db
        ),
        "recommendation_pool.db": (
            resolver.recommendation_pool_db
        ),

        "real_portfolio_history": (
            resolver.runtime / "real_portfolio_history.db"
        ),
        "real_portfolio_history.db": (
            resolver.runtime / "real_portfolio_history.db"
        ),
    }

    key = str(name).strip().lower()

    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown Stock DB logical name: {name!r}"
        ) from exc


__all__ = [
    "resolver",
    "MARKET_DB",
    "MARKET_CACHE_DB",
    "SIMULATION_DB",
    "SIMULATION_DB_PATH",
    "CF_CACHE_DB",
    "WESTOCK_CACHE_DB",
    "WESTOCK_DB",
    "INTRADAY_CACHE_DB",
    "INTRADAY_DB",
    "LHB_CACHE_DB",
    "LHB_DB",
    "NEWS_CACHE_DB",
    "NEWS_DB",
    "RECOMMENDATION_POOL_DB",
    "RECOMMENDATION_DB",
    "REAL_PORTFOLIO_HISTORY_DB",
    "get_db_path",
]
