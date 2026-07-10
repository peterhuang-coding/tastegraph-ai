"""
Shared utility functions for xhs_publisher modules.
"""

from __future__ import annotations

from typing import Optional


MAX_TIMING_JITTER_RATIO = 0.7


def normalize_timing_jitter(value: float) -> float:
    """Clamp timing jitter to a safe range."""
    return max(0.0, min(MAX_TIMING_JITTER_RATIO, value))


def is_local_host(host: str) -> bool:
    """Return True when host points to the local machine."""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def resolve_account_name(account_name: str | None) -> str:
    """Resolve explicit or default account name for login cache scoping."""
    if account_name and account_name.strip():
        return account_name.strip()
    try:
        from account_manager import get_default_account  # type: ignore[import-untyped]
        resolved = get_default_account()
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
    except Exception:
        pass
    return "default"