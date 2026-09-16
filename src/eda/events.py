"""Event-level analyses."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from .config import FIGURES_DIR


def analyze_events(docs: pd.DataFrame, events: pd.DataFrame) -> dict:
    if events.empty:
        return {"note": "no events"}

    # Time from first filing to each amendment filing within an event
    filing_dates = (
        docs.groupby(["event_id", "accession", "form", "is_amendment"], dropna=False)["file_date"]
        .min()
        .reset_index()
    )
    first_dates = events[["event_id", "first_file_date"]]
    merged = filing_dates.merge(first_dates, on="event_id", how="left")
    merged["days_from_initial"] = (merged["file_date"] - merged["first_file_date"]).dt.days
    amend_lags = merged.loc[merged["is_amendment"] & merged["days_from_initial"].notna(), "days_from_initial"]

    issuer_counts = (
        events["primary_entity"]
        .fillna("(missing entity name)")
        .value_counts()
        .rename_axis("entity")
        .reset_index(name="n_events")
    )
    repeated = issuer_counts.loc[issuer_counts["n_events"] > 1]

    unusual_docs = events.nlargest(15, "n_documents")[
        ["event_id", "primary_entity", "primary_form_family", "n_documents", "n_filings", "n_amendment_filings", "event_span_days"]
    ]
    unusual_amends = events.nlargest(15, "n_amendment_filings")[
        ["event_id", "primary_entity", "primary_form_family", "n_documents", "n_filings", "n_amendment_filings", "event_span_days"]
    ]

    return {
        "docs_per_event": events["n_documents"].describe(),
        "amendments_per_event": events["n_amendment_filings"].describe(),
        "event_span_days": events["event_span_days"].dropna().astype(float).describe(),
        "amendment_lag_days": amend_lags.describe() if len(amend_lags) else pd.Series(dtype=float),
        "issuer_counts": issuer_counts,
        "repeated_issuers": repeated,
        "unusual_document_volume": unusual_docs,
        "unusual_amendment_volume": unusual_amends,
        "amendment_lag_detail": merged.loc[merged["is_amendment"]].copy(),
        "note": (
            "Event duration is observed as last_file_date - first_file_date for documents "
            "sharing a SEC file number. Offer expiration is NOT inferred here."
        ),
    }


def plot_event_distributions(events: pd.DataFrame, save: bool = True) -> plt.Figure:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    sns.histplot(events["n_documents"], bins=30, ax=axes[0], color="#1f4e79")
    axes[0].set_title("Documents / event")
    sns.histplot(events["n_amendment_filings"], bins=20, ax=axes[1], color="#2e7d4f")
    axes[1].set_title("Amendment filings / event")
    span = events["event_span_days"].dropna().astype(float)
    sns.histplot(span[span >= 0], bins=30, ax=axes[2], color="#8b4513")
    axes[2].set_title("Observed event span (days)")
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "event_distributions.png", dpi=150)
    return fig
