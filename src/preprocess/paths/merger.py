"""Merger path: pick primary proxy/S-4/8-K HTML for download (no OTP)."""

from __future__ import annotations

from typing import Any

import pandas as pd

_MERGER_FORMS = {
    "DEFM14A",
    "PREM14A",
    "DEFA14A",
    "PREA14A",
    "S-4",
    "S-4/A",
    "425",
    "8-K",
    "8-K/A",
    "SC 13E3",
    "SC 13E3/A",
}


def _s(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def select_priority_docs(event_docs: pd.DataFrame) -> dict[str, Any]:
    """Select primary merger filing HTML (+ large exhibits if present)."""
    if event_docs.empty:
        return {
            "has_cover": False,
            "has_otp": False,
            "has_lot": False,
            "has_14d9": False,
            "otp_method": None,
            "cohort": "incomplete",
            "n_amendments": 0,
            "download_ready": False,
            "docs": [],
        }

    cand = event_docs.copy()
    form = cand["form"].fillna("").astype(str).str.upper()
    fname = cand["filename"].fillna("").astype(str).str.lower()
    mask = form.isin(_MERGER_FORMS) & fname.str.endswith((".htm", ".html", ".txt"))
    subset = cand[mask]
    if subset.empty:
        subset = cand[fname.str.endswith((".htm", ".html"))]

    docs_out: list[dict[str, Any]] = []
    if not subset.empty:
        # Prefer primary form doc, then largest (bytes), then non-amendment
        sort_cols = []
        if "is_primary_form_doc" in subset.columns:
            sort_cols.append(("is_primary_form_doc", False))
        if "bytes" in subset.columns:
            sort_cols.append(("bytes", False))
        if "is_amendment" in subset.columns:
            sort_cols.append(("is_amendment", True))
        if sort_cols:
            by = [c for c, _ in sort_cols]
            asc = [a for _, a in sort_cols]
            subset = subset.sort_values(by, ascending=asc)
        # Keep primary + up to 2 extras (exhibits)
        picked = subset.head(3)
        for i, (_, doc) in enumerate(picked.iterrows()):
            role = "primary" if i == 0 else "exhibit"
            docs_out.append(
                {
                    "role": role,
                    "hit_id": doc.get("hit_id"),
                    "accession": doc.get("accession"),
                    "filename": doc.get("filename"),
                    "form": doc.get("form"),
                    "file_type": doc.get("file_type"),
                    "file_description": doc.get("file_description"),
                    "file_date": str(doc.get("file_date") or ""),
                    "primary_cik": doc.get("primary_cik"),
                    "otp_method": None,
                    "is_amendment": bool(doc.get("is_amendment")),
                }
            )

    has_primary = bool(docs_out)
    n_amendments = (
        int(event_docs["is_amendment"].fillna(False).sum())
        if "is_amendment" in event_docs
        else 0
    )
    return {
        "has_cover": has_primary,
        "has_otp": False,
        "has_lot": False,
        "has_14d9": False,
        "otp_method": None,
        "cohort": "gold" if has_primary else "incomplete",
        "n_amendments": n_amendments,
        "download_ready": has_primary,
        "docs": docs_out,
    }
