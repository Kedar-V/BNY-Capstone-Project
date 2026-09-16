"""Dataset overview summaries and plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .config import FIGURES_DIR


def _ensure_figs() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return FIGURES_DIR


def summarize_dataset(docs: pd.DataFrame, events: pd.DataFrame) -> dict:
    """Return observed overview metrics. Values are computed from loaded tables only."""
    if docs.empty:
        return {"n_documents": 0, "n_events": 0, "note": "empty corpus"}

    date_min = docs["file_date"].min()
    date_max = docs["file_date"].max()
    form_counts = docs["form"].value_counts(dropna=False).rename_axis("form").reset_index(name="n_documents")
    family_counts = (
        docs["form_family"].value_counts(dropna=False).rename_axis("form_family").reset_index(name="n_documents")
    )
    docs_per_event = events["n_documents"].describe() if not events.empty else pd.Series(dtype=float)
    filings_per_event = events["n_filings"].describe() if not events.empty else pd.Series(dtype=float)
    events_with_amend = int(events["has_amendment"].sum()) if not events.empty else 0
    pct_amend = (100.0 * events_with_amend / len(events)) if len(events) else 0.0

    # Filing-level table (unique accession x form)
    filings = (
        docs.groupby(["accession", "form", "file_date", "primary_file_num", "event_id"], dropna=False)
        .size()
        .reset_index(name="n_docs_in_filing")
    )

    overview = {
        "n_documents": int(len(docs)),
        "n_filings": int(docs["accession"].nunique()),
        "n_events": int(len(events)),
        "date_min": None if pd.isna(date_min) else date_min.date().isoformat(),
        "date_max": None if pd.isna(date_max) else date_max.date().isoformat(),
        "events_with_amendments": events_with_amend,
        "pct_events_with_amendments": round(pct_amend, 2),
        "form_counts": form_counts,
        "family_counts": family_counts,
        "docs_per_event_summary": docs_per_event,
        "filings_per_event_summary": filings_per_event,
        "filings_table": filings,
        "source_note": (
            "Document rows are EFTS hit-level records (primary filing docs + indexed exhibits). "
            "Events are grouped by SEC file number (primary_file_num) when present."
        ),
    }
    return overview


def plot_form_distribution(docs: pd.DataFrame, save: bool = True) -> plt.Figure:
    _ensure_figs()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    order = docs["form"].value_counts().index
    sns.countplot(data=docs, y="form", order=order, ax=ax, color="#1f4e79")
    ax.set_title("Document counts by filing type (observed EFTS hits)")
    ax.set_xlabel("Documents")
    ax.set_ylabel("Form")
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "form_distribution.png", dpi=150)
    return fig


def plot_temporal_volume(docs: pd.DataFrame, freq: str = "M", save: bool = True) -> plt.Figure:
    _ensure_figs()
    ts = (
        docs.dropna(subset=["file_date"])
        .assign(period=lambda d: d["file_date"].dt.to_period(freq).dt.to_timestamp())
        .groupby(["period", "form_family"])
        .size()
        .reset_index(name="n")
    )
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for family, g in ts.groupby("form_family"):
        ax.plot(g["period"], g["n"], marker="o", linewidth=1.5, label=family)
    ax.set_title(f"Document volume over time ({freq})")
    ax.set_xlabel("Filing date")
    ax.set_ylabel("Documents")
    ax.legend(title="Form family", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "temporal_volume.png", dpi=150)
    return fig


def overview_tables(docs: pd.DataFrame, events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    overview = summarize_dataset(docs, events)
    summary_df = pd.DataFrame(
        [
            {"metric": "documents", "value": overview["n_documents"]},
            {"metric": "filings (unique accession)", "value": overview["n_filings"]},
            {"metric": "events (by SEC file number)", "value": overview["n_events"]},
            {"metric": "date_min", "value": overview["date_min"]},
            {"metric": "date_max", "value": overview["date_max"]},
            {"metric": "events_with_amendments", "value": overview["events_with_amendments"]},
            {"metric": "pct_events_with_amendments", "value": overview["pct_events_with_amendments"]},
        ]
    )
    return {
        "summary": summary_df,
        "form_counts": overview["form_counts"],
        "family_counts": overview["family_counts"],
    }
