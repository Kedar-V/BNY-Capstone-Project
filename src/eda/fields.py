"""Heuristic field-availability scans for client-notification attributes.

IMPORTANT
---------
These detectors are regex/heuristic presence checks on downloaded document text.
A match means the *concept appears to be mentioned*, not that a structured ground-truth
value was extracted. Absence means "not detected by these patterns", not proof the
field is missing from the document.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# Each pattern family is intentionally conservative and documented as inferred.
FIELD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "event_type": [
        re.compile(r"\btender\s+offer\b", re.I),
        re.compile(r"\boffer\s+to\s+purchase\b", re.I),
        re.compile(r"\bexchange\s+offer\b", re.I),
        re.compile(r"\bself[- ]tender\b", re.I),
    ],
    "issuer_target_offeror": [
        re.compile(r"\b(subject\s+company|target\s+company|offeror|bidder|purchaser)\b", re.I),
        re.compile(r"\b(issuer|filing\s+person)\b", re.I),
    ],
    "security_identifiers": [
        re.compile(r"\bCUSIP\b", re.I),
        re.compile(r"\bISIN\b", re.I),
        re.compile(r"\bticker\s+symbol\b", re.I),
        re.compile(r"\bCommon\s+Stock\b", re.I),
    ],
    "offer_price_consideration": [
        re.compile(r"\$\s?\d+(?:\.\d+)?\s+per\s+share", re.I),
        re.compile(r"\boffer\s+price\b", re.I),
        re.compile(r"\bconsideration\b", re.I),
        re.compile(r"\bcash\s+consideration\b", re.I),
    ],
    "available_options": [
        re.compile(r"\belection\b", re.I),
        re.compile(r"\bmixed\s+consideration\b", re.I),
        re.compile(r"\bcash\s+election\b", re.I),
        re.compile(r"\bstock\s+election\b", re.I),
        re.compile(r"\bproration\s+factor\b", re.I),
    ],
    "expiration_date": [
        re.compile(r"\bexpir(?:e|es|ation)\b.{0,40}\b(date|time)\b", re.I),
        re.compile(r"\bExpiration\s+Date\b", re.I),
        re.compile(r"\bunless\s+extended\b", re.I),
    ],
    "withdrawal_deadline": [
        re.compile(r"\bwithdraw(?:al|n)?\b.{0,40}\b(right|deadline|until|prior)\b", re.I),
        re.compile(r"\bright\s+to\s+withdraw\b", re.I),
    ],
    "conditions": [
        re.compile(r"\bconditions?\s+to\s+(the\s+)?offer\b", re.I),
        re.compile(r"\bminimum\s+condition\b", re.I),
        re.compile(r"\bfinancing\s+condition\b", re.I),
        re.compile(r"\bregulatory\s+approvals?\b", re.I),
    ],
    "restrictions": [
        re.compile(r"\bjurisdictions?\b", re.I),
        re.compile(r"\bnot\s+being\s+made\b", re.I),
        re.compile(r"\brestricted\s+jurisdict", re.I),
        re.compile(r"\bERISA\b"),
    ],
    "proration_min_tender": [
        re.compile(r"\bproration\b", re.I),
        re.compile(r"\bpro\s*ration\b", re.I),
        re.compile(r"\bminimum\s+tender\b", re.I),
        re.compile(r"\bmajority\s+of\s+the\s+outstanding\b", re.I),
    ],
}


def scan_text_for_fields(text: str) -> dict[str, Any]:
    """Return inferred presence flags and matched pattern counts for one document."""
    out: dict[str, Any] = {"metric_source": "inferred_regex_presence"}
    for field, patterns in FIELD_PATTERNS.items():
        hits = [p.pattern for p in patterns if p.search(text or "")]
        out[f"{field}_detected"] = bool(hits)
        out[f"{field}_n_pattern_hits"] = len(hits)
    return out


def analyze_field_availability(content_sample: pd.DataFrame) -> dict:
    """
    Estimate how often key client-notification fields appear in a document sample.

    Requires a content sample with readable text files on disk (local_path) or an
    attached `text` column. Does not invent values for failed downloads.
    """
    if content_sample is None or content_sample.empty:
        return {
            "note": "No content sample available; field availability not estimated.",
            "coverage": pd.DataFrame(),
        }

    rows = []
    for _, row in content_sample.iterrows():
        if row.get("status") != "ok":
            rows.append(
                {
                    "accession": row.get("accession"),
                    "form": row.get("form"),
                    "status": row.get("status"),
                    "metric_source": "not_analyzed_download_failed_or_empty",
                }
            )
            continue
        text = row.get("text")
        if not text:
            path = row.get("local_path")
            if path:
                raw = open(path, "rb").read().decode("utf-8", errors="replace")
                if "<html" in raw[:1000].lower() or raw.lstrip().lower().startswith("<!doctype"):
                    from .documents import html_to_text

                    text = html_to_text(raw)
                else:
                    text = raw
            else:
                text = ""
        scanned = scan_text_for_fields(text)
        scanned.update(
            {
                "accession": row.get("accession"),
                "form": row.get("form"),
                "event_id": row.get("event_id"),
                "status": row.get("status"),
            }
        )
        rows.append(scanned)

    detail = pd.DataFrame(rows)
    detected_cols = [c for c in detail.columns if c.endswith("_detected")]
    if not detected_cols:
        return {
            "detail": detail,
            "coverage": pd.DataFrame(),
            "note": "No successful document texts to scan.",
        }

    ok = detail[detail["status"] == "ok"]
    coverage = []
    for col in detected_cols:
        field = col.replace("_detected", "")
        coverage.append(
            {
                "field": field,
                "n_docs_scanned": int(len(ok)),
                "n_detected": int(ok[col].sum()),
                "pct_detected": round(100.0 * ok[col].mean(), 2) if len(ok) else 0.0,
                "evidence_type": "inferred_regex_presence",
            }
        )
    coverage_df = pd.DataFrame(coverage).sort_values("pct_detected", ascending=False)
    by_form = (
        ok.groupby("form")[detected_cols].mean().mul(100).round(1)
        if not ok.empty
        else pd.DataFrame()
    )
    return {
        "detail": detail,
        "coverage": coverage_df,
        "coverage_by_form_pct": by_form,
        "note": (
            "Percentages are inferred from regex presence on a stratified document sample. "
            "They are not labeled extraction accuracy and should not be treated as ground truth."
        ),
    }
