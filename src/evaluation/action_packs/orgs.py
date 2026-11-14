"""Organization-name normalization shared by pack hooks and the evidence builders.

Dependency-free on purpose: ``src.evaluation.extract.evidence`` and the pack modules
both import it, so it must not import either of them.
"""

from __future__ import annotations

_ORG_JUNK = (
    "incorporated",
    "inc.",
    "inc",
    "corporation",
    "corp.",
    "corp",
    "ltd.",
    "ltd",
    "llc",
    "l.l.c.",
    "co.",
    "company",
    "the ",
)


def norm_org(s: str) -> str:
    s = (s or "").lower()
    for junk in _ORG_JUNK:
        s = s.replace(junk, " ")
    return " ".join(s.split())


def same_org(a: str, b: str) -> bool:
    na, nb = norm_org(a), norm_org(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na
