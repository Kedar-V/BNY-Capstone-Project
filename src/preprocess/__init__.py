"""Modular preprocess pipeline: inventory → Concise Rep → DB."""

from __future__ import annotations

__all__ = ["STAGE_NAMES", "PATH_NAMES"]

STAGE_NAMES = (
    "inventory",
    "download",
    "cleanup",
    "segment",
    "gliner",
    "assemble",
    "load_db",
)

PATH_NAMES = (
    "tender",
    "exchange",
    "rights",
    "merger",
    "conversion",
)
