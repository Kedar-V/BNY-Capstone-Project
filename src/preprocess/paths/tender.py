"""Tender-offer path: document role discovery and cohort helpers."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

_OTP_DESC = re.compile(r"offer\s+to\s+purchase", re.I)
_LOT_DESC = re.compile(r"letter\s+of\s+transmittal", re.I)
_OTP_TYPE = re.compile(r"ex-?99\.?\(?a\)?\.?\(?1\)?\.?\(?a\)?", re.I)
_LOT_TYPE = re.compile(r"ex-?99\.?\(?a\)?\.?\(?1\)?\.?\(?b\)?", re.I)
_EX99_A1 = re.compile(r"ex-?99\.?\(?a\)?\.?\(?1\)?", re.I)
_COVER_FORMS = {"SC TO-T", "SC TO-T/A", "SC TO-I", "SC TO-I/A"}
_14D9_FORMS = {"SC 14D9", "SC 14D9/A"}


def _s(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def classify_doc_role(row: dict[str, Any] | pd.Series) -> tuple[str | None, str | None]:
    """Return (role, otp_method) from EDGAR metadata only."""
    form = _s(row.get("form"))
    ftype = _s(row.get("file_type"))
    desc = _s(row.get("file_description"))
    is_primary = bool(row.get("is_primary_form_doc"))

    if form in _COVER_FORMS and (is_primary or not bool(row.get("is_exhibit"))):
        return "cover", None
    if form in _14D9_FORMS and (is_primary or not bool(row.get("is_exhibit"))):
        return "sc_14d9", None
    if _OTP_DESC.search(desc):
        return "otp", "file_description"
    if _OTP_TYPE.search(ftype):
        return "otp", "ex99_type"
    if _LOT_DESC.search(desc) or _LOT_TYPE.search(ftype):
        return "lot", "file_description" if _LOT_DESC.search(desc) else "ex99_type"
    return None, None


def pick_otp_inferred(docs: pd.DataFrame) -> pd.Series | None:
    """Largest non-fee EX-99.(A)(1)* HTML exhibit as OTP fallback."""
    if docs.empty:
        return None
    cand = docs.copy()
    ftype = cand["file_type"].fillna("").astype(str)
    fname = cand["filename"].fillna("").astype(str).str.lower()
    desc = cand["file_description"].fillna("").astype(str).str.lower()
    mask = ftype.apply(lambda t: bool(_EX99_A1.search(t))) & ~desc.str.contains("fee", na=False)
    mask &= fname.str.endswith((".htm", ".html"))
    # Prefer A1A-like, exclude explicit LoT
    mask &= ~ftype.apply(lambda t: bool(_LOT_TYPE.search(t)))
    mask &= ~desc.str.contains("letter of transmittal", na=False)
    subset = cand[mask]
    if subset.empty:
        return None
    # Prefer exact A1A type, else largest by sequence proxy (later sequence often main exhibit)
    exact = subset[subset["file_type"].fillna("").astype(str).apply(lambda t: bool(_OTP_TYPE.search(t)))]
    pool = exact if not exact.empty else subset
    if "bytes" in pool.columns and pool["bytes"].notna().any():
        return pool.sort_values("bytes", ascending=False).iloc[0]
    if "sequence" in pool.columns:
        return pool.sort_values("sequence", ascending=False).iloc[0]
    return pool.iloc[0]


def select_priority_docs(event_docs: pd.DataFrame) -> dict[str, Any]:
    """Build inventory doc list + flags for one event."""
    rows = []
    for _, r in event_docs.iterrows():
        role, method = classify_doc_role(r)
        if role:
            rows.append({**r.to_dict(), "_role": role, "_otp_method": method})

    by_role: dict[str, list[dict]] = {"cover": [], "otp": [], "lot": [], "sc_14d9": []}
    for item in rows:
        by_role.setdefault(item["_role"], []).append(item)

    otp_method = None
    otp_docs = by_role.get("otp") or []
    if otp_docs:
        # Prefer description match
        otp_docs_sorted = sorted(
            otp_docs,
            key=lambda d: 0 if d.get("_otp_method") == "file_description" else 1,
        )
        chosen_otp = otp_docs_sorted[0]
        otp_method = chosen_otp.get("_otp_method")
    else:
        inferred = pick_otp_inferred(event_docs)
        if inferred is not None:
            chosen_otp = {**inferred.to_dict(), "_role": "otp", "_otp_method": "inferred"}
            otp_method = "inferred"
            otp_docs = [chosen_otp]
        else:
            chosen_otp = None

    def _one(role_docs: list[dict]) -> dict | None:
        if not role_docs:
            return None
        # Prefer non-amendment, then earliest file_date
        role_docs = sorted(
            role_docs,
            key=lambda d: (bool(d.get("is_amendment")), str(d.get("file_date") or "")),
        )
        return role_docs[0]

    cover = _one(by_role.get("cover") or [])
    lot = _one(by_role.get("lot") or [])
    sc14 = _one(by_role.get("sc_14d9") or [])
    otp = chosen_otp if otp_docs else None

    docs_out = []
    for role, doc in [("cover", cover), ("otp", otp), ("lot", lot), ("sc_14d9", sc14)]:
        if not doc:
            continue
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
                "otp_method": doc.get("_otp_method") if role == "otp" else None,
                "is_amendment": bool(doc.get("is_amendment")),
            }
        )

    has_cover = cover is not None
    has_otp = otp is not None
    has_lot = lot is not None
    has_14d9 = sc14 is not None
    if has_cover and has_otp and has_14d9:
        cohort = "gold"
    elif has_cover and has_14d9 and not has_otp:
        cohort = "needs_otp_resolve"
    else:
        cohort = "incomplete"

    n_amendments = int(event_docs["is_amendment"].fillna(False).sum()) if "is_amendment" in event_docs else 0

    return {
        "has_cover": has_cover,
        "has_otp": has_otp,
        "has_lot": has_lot,
        "has_14d9": has_14d9,
        "otp_method": otp_method if has_otp else ("missing" if cohort != "needs_otp_resolve" else None),
        "cohort": cohort,
        "n_amendments": n_amendments,
        "download_ready": has_cover and has_otp,
        "docs": docs_out,
    }
