#!/usr/bin/env python3
"""
Data provider exceptions.
"""
from __future__ import annotations


class DataProviderError(Exception):
    """Base provider error."""

    def __init__(self, message: str = "", provider: str = "", error_type: str = "unknown") -> None:
        super().__init__(message)
        self.provider = provider
        self.error_type = error_type


class ProviderTimeoutError(DataProviderError):
    """Provider request timeout."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="timeout")


class ProviderRateLimitError(DataProviderError):
    """Provider rate limit exceeded."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="rate_limit")


class ProviderAuthError(DataProviderError):
    """Provider authentication error."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="auth")


class ProviderParseError(DataProviderError):
    """Provider response parse error."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="parse")


class ProviderNetworkError(DataProviderError):
    """Provider network error."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="network")


class ProviderDataQualityError(DataProviderError):
    """Provider data quality validation failed."""

    def __init__(self, message: str = "", provider: str = "") -> None:
        super().__init__(message, provider=provider, error_type="data_quality")
