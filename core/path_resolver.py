"""
Stock Work canonical path resolver.

Architecture rule:
    HERMES_HOME
        ->
    STOCK_WORK_ROOT
        ->
    StockPathResolver
        ->
    production / runtime / research / snapshots / archive / quarantine

This module must be the single path-resolution boundary for Stock Work.

It must not:
- reference OpenClaw paths
- reference machine-specific absolute paths
- move files
- delete files
- perform database migration
- modify Cron
"""

from __future__ import annotations

import os
from pathlib import Path


class StockPathResolver:
    """
    Canonical Stock Work filesystem resolver.

    Environment precedence:
        STOCK_WORK_ROOT
        HERMES_HOME/stock-work

    HERMES_HOME is intentionally treated as the Hermes
    profile boundary, not as a hard-coded machine path.
    """

    def __init__(
        self,
        hermes_home: Path | None = None,
        stock_work_root: Path | None = None,
    ) -> None:
        if stock_work_root is not None:
            root = Path(stock_work_root).expanduser()
        else:
            env_root = os.environ.get("STOCK_WORK_ROOT")

            if env_root:
                root = Path(env_root).expanduser()
            else:
                if hermes_home is not None:
                    home = Path(hermes_home).expanduser()
                else:
                    env_home = os.environ.get("HERMES_HOME")

                    if not env_home:
                        raise RuntimeError(
                            "HERMES_HOME or STOCK_WORK_ROOT "
                            "must be defined."
                        )

                    home = Path(env_home).expanduser()

                root = home / "stock-work"

        self.root = root.resolve()

    # ---------------------------------------------------------
    # Root
    # ---------------------------------------------------------

    @property
    def stock_work_root(self) -> Path:
        return self.root

    # ---------------------------------------------------------
    # Data domains
    # ---------------------------------------------------------

    @property
    def data_root(self) -> Path:
        return self.root / "data"

    @property
    def production(self) -> Path:
        return self.data_root / "production"

    @property
    def runtime(self) -> Path:
        return self.data_root / "runtime"

    @property
    def research(self) -> Path:
        return self.data_root / "research"

    @property
    def snapshots(self) -> Path:
        return self.data_root / "snapshots"

    @property
    def archive(self) -> Path:
        return self.data_root / "archive"

    @property
    def quarantine(self) -> Path:
        return self.data_root / "quarantine"

    # ---------------------------------------------------------
    # Canonical database paths
    # ---------------------------------------------------------

    @property
    def market_cache_db(self) -> Path:
        return self.production / "market_cache.db"

    @property
    def simulation_db(self) -> Path:
        return self.runtime / "simulation.db"

    @property
    def cf_cache_db(self) -> Path:
        return self.runtime / "cf_cache.db"

    @property
    def westock_cache_db(self) -> Path:
        return self.runtime / "westock_cache.db"

    @property
    def intraday_cache_db(self) -> Path:
        return self.runtime / "intraday_cache.db"

    @property
    def lhb_cache_db(self) -> Path:
        return self.runtime / "lhb_cache.db"

    @property
    def news_cache_db(self) -> Path:
        return self.runtime / "news_cache.db"

    @property
    def recommendation_pool_db(self) -> Path:
        return self.production / "recommendation_pool.db"

    # ---------------------------------------------------------
    # Generic resolver
    # ---------------------------------------------------------

    def resolve(
        self,
        domain: str,
        filename: str,
    ) -> Path:
        mapping = {
            "production": self.production,
            "runtime": self.runtime,
            "research": self.research,
            "snapshots": self.snapshots,
            "archive": self.archive,
            "quarantine": self.quarantine,
        }

        if domain not in mapping:
            raise ValueError(
                f"Unknown Stock Work domain: {domain!r}"
            )

        if not filename or "/" in filename or "\\" in filename:
            raise ValueError(
                "filename must be a single filename, "
                "not a nested path."
            )

        return mapping[domain] / filename

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def validate(self) -> dict[str, str]:
        result: dict[str, str] = {}

        for name, path in {
            "stock_work_root": self.stock_work_root,
            "production": self.production,
            "runtime": self.runtime,
            "research": self.research,
            "snapshots": self.snapshots,
            "archive": self.archive,
            "quarantine": self.quarantine,
        }.items():
            result[name] = str(path)

        return result


_default: StockPathResolver | None = None


def get_path_resolver() -> StockPathResolver:
    global _default

    if _default is None:
        _default = StockPathResolver()

    return _default
