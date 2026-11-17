"""Swappable ActionPacks: schema + instructions for the unified extract harness."""

from __future__ import annotations

from .base import ActionPack, ClauseFieldSpec, FieldShot, HybridSpec
from .merger import MERGER_PACK
from .retrieve import retrieve_clause
from .tender import TENDER_PACK

__all__ = [
    "ActionPack",
    "ClauseFieldSpec",
    "FieldShot",
    "HybridSpec",
    "TENDER_PACK",
    "MERGER_PACK",
    "get_pack",
    "retrieve_clause",
]


def get_pack(name: str) -> ActionPack:
    key = (name or "tender").strip().lower()
    if key == "tender":
        return TENDER_PACK
    if key == "merger":
        return MERGER_PACK
    raise KeyError(f"unknown ActionPack {name!r}; available: tender, merger")
