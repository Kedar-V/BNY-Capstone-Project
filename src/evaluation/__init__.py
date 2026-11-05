"""Pipeline vs ground-truth evaluation."""

from __future__ import annotations

from typing import Any

__all__ = ["GT_VALUE_FIELDS", "evaluate_tender", "field_coverage"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from src.evaluation import tender as _tender

        return getattr(_tender, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
