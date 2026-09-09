#!/usr/bin/env python3
"""
Provider manager: central entry point for data providers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class ProviderManager:
    """Central entry point for all data providers."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._providers: Dict[str, Any] = {}
        self._health: Dict[str, Any] = {}

    def register_provider(self, name: str, provider: Any) -> None:
        """Register a provider by name."""
        self._providers[name] = provider
        self._health[name] = {
            "provider": provider,
            "success_count": 0,
            "failure_count": 0,
            "consecutive_failures": 0,
        }

    def get_provider(self, name: str) -> Any:
        """Get provider by name."""
        if name not in self._providers:
            raise KeyError(f"Provider not registered: {name}")
        return self._providers[name]

    def get_health(self, name: str) -> Dict[str, Any]:
        """Get provider health state."""
        return self._health.get(name, {})

    def record_success(self, name: str) -> None:
        """Record successful call."""
        health = self._health.get(name)
        if health is not None:
            health["success_count"] += 1
            health["consecutive_failures"] = 0

    def record_failure(self, name: str, error: str = "") -> None:
        """Record failed call."""
        health = self._health.get(name)
        if health is not None:
            health["failure_count"] += 1
            health["consecutive_failures"] += 1
            health["last_error"] = error
