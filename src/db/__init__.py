"""Postgres helpers for the BNY capstone event datastore."""

from __future__ import annotations

from .connection import connect, get_dsn

__all__ = ["connect", "get_dsn", "load_all"]


def __getattr__(name: str):
    if name == "load_all":
        from .load import load_all

        return load_all
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
