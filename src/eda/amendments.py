"""Temporal / amendment-focused analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .fields import FIELD_PATTERNS, scan_text_for_fields
from .documents import html_to_text


def _load_text(path: str | None) -> str:
    if not path:
        return ""
    raw = open(path, "rb").read().decode("utf-8", errors="replace")
    if "<html" in raw[:1000].lower() or raw.lstrip().lower().startswith("<!doctype"):
        return html_to_text(raw)
    return raw


def analyze_amendments(
    docs: pd.DataFrame,
    events: pd.DataFrame,
    content_sample: pd.DataFrame | None = None,
) -> dict:
    """
    Characterize amendment frequency and, where sample text exists, which field
    mentions differ between an event's sampled initial and amendment docs.

    Field-change findings are inferred from presence-flag deltas in the sample only.
    """
    if events.empty:
        return {"note": "no events"}

    amend_events = events[events["has_amendment"]].copy()
    simple = amend_events[amend_events["n_amendment_filings"] == 1].nsmallest(
        10, "n_documents"
    )[
        [
            "event_id",
            "primary_entity",
            "primary_form_family",
            "n_filings",
            "n_amendment_filings",
            "n_documents",
            "event_span_days",
            "first_file_date",
            "last_file_date",
        ]
    ]
    complex_ = amend_events.nlargest(10, "n_amendment_filings")[
        [
            "event_id",
            "primary_entity",
            "primary_form_family",
            "n_filings",
            "n_amendment_filings",
            "n_documents",
            "event_span_days",
            "first_file_date",
            "last_file_date",
        ]
    ]

    # Filing cadence within events
    filing_level = (
        docs.groupby(["event_id", "accession", "form", "is_amendment"], dropna=False)["file_date"]
        .min()
        .reset_index()
        .sort_values(["event_id", "file_date"])
    )
    filing_level["prior_date"] = filing_level.groupby("event_id")["file_date"].shift(1)
    filing_level["days_since_prior_filing"] = (
        filing_level["file_date"] - filing_level["prior_date"]
    ).dt.days

    field_change_summary = pd.DataFrame()
    representative_deltas = pd.DataFrame()
    note = (
        "Amendment counts are observed from form suffixes (/A) and filing dates. "
        "Field-level change analysis requires paired sample texts and is inferred only."
    )

    if content_sample is not None and not content_sample.empty:
        ok = content_sample[content_sample["status"] == "ok"].copy()
        # Attach presence flags
        scanned_rows = []
        for _, row in ok.iterrows():
            text = _load_text(row.get("local_path"))
            flags = scan_text_for_fields(text)
            flags.update(
                {
                    "event_id": row["event_id"],
                    "accession": row["accession"],
                    "form": row["form"],
                    "is_amendment_form": str(row["form"]).endswith("/A"),
                }
            )
            scanned_rows.append(flags)
        scanned = pd.DataFrame(scanned_rows)
        detected_cols = [c for c in scanned.columns if c.endswith("_detected")]

        deltas = []
        for event_id, g in scanned.groupby("event_id"):
            initials = g[~g["is_amendment_form"]]
            amends = g[g["is_amendment_form"]]
            if initials.empty or amends.empty:
                continue
            base = initials.iloc[0]
            for _, amend in amends.iterrows():
                changed = []
                for col in detected_cols:
                    if bool(base[col]) != bool(amend[col]):
                        changed.append(col.replace("_detected", ""))
                deltas.append(
                    {
                        "event_id": event_id,
                        "initial_accession": base["accession"],
                        "amendment_accession": amend["accession"],
                        "fields_with_presence_delta": changed,
                        "n_fields_changed_presence": len(changed),
                        "evidence_type": "inferred_regex_presence_delta",
                    }
                )
        representative_deltas = pd.DataFrame(deltas)
        if not representative_deltas.empty:
            from collections import Counter

            counter: Counter[str] = Counter()
            for fields in representative_deltas["fields_with_presence_delta"]:
                counter.update(fields)
            field_change_summary = (
                pd.DataFrame(
                    [{"field": k, "n_pairs_with_presence_delta": v} for k, v in counter.most_common()]
                )
                if counter
                else pd.DataFrame(columns=["field", "n_pairs_with_presence_delta"])
            )
            note += (
                f" Sample contained {len(representative_deltas)} initial/amendment pairs "
                "with downloadable text."
            )
        else:
            note += " Sample did not contain paired initial+amendment texts for the same event."

    return {
        "n_events_with_amendments": int(events["has_amendment"].sum()),
        "pct_events_with_amendments": round(100.0 * events["has_amendment"].mean(), 2),
        "amendment_filings_distribution": events["n_amendment_filings"].value_counts().sort_index(),
        "simple_amendment_examples": simple,
        "complex_amendment_examples": complex_,
        "filing_cadence": filing_level,
        "field_presence_delta_summary": field_change_summary,
        "field_presence_delta_pairs": representative_deltas,
        "patterns_available_for_change_checks": sorted(FIELD_PATTERNS.keys()),
        "note": note,
    }
