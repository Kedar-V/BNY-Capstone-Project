"""Data-quality checks and leakage warnings."""

from __future__ import annotations

import pandas as pd


def analyze_data_quality(docs: pd.DataFrame, events: pd.DataFrame) -> dict:
    if docs.empty:
        return {"note": "empty corpus"}

    missing_meta = pd.DataFrame(
        {
            "field": [
                "accession",
                "filename",
                "form",
                "file_date",
                "primary_cik",
                "entity_name",
                "primary_file_num",
                "tickers",
            ],
            "n_missing_or_empty": [
                int(docs["accession"].isna().sum()),
                int(docs["filename"].isna().sum()),
                int(docs["form"].isna().sum()),
                int(docs["file_date"].isna().sum()),
                int(docs["primary_cik"].isna().sum()),
                int(docs["entity_name"].isna().sum()),
                int(docs["primary_file_num"].isna().sum()),
                int(
                    docs["tickers"].apply(
                        lambda x: x is None or (isinstance(x, (list, tuple)) and len(x) == 0)
                    ).sum()
                )
                if "tickers" in docs
                else len(docs),
            ],
        }
    )
    missing_meta["pct"] = (100 * missing_meta["n_missing_or_empty"] / len(docs)).round(2)

    # Inconsistent names for same CIK
    name_variance = (
        docs.dropna(subset=["primary_cik", "entity_name"])
        .groupby("primary_cik")["entity_name"]
        .nunique()
        .reset_index(name="n_distinct_names")
        .query("n_distinct_names > 1")
        .sort_values("n_distinct_names", ascending=False)
    )

    # Duplicate filing rows: same accession+filename
    dup_docs = (
        docs.groupby(["accession", "filename"], dropna=False)
        .size()
        .reset_index(name="n")
        .query("n > 1")
    )

    # Events lacking file numbers (fallback keys) — weaker event linkage
    weak_events = events[events["event_id"].astype(str).str.startswith("NO_FILE_NUM:")]

    # Potential leakage: multi-document events if split at document level
    multi_doc_events = events[events["n_documents"] > 1]
    leakage = pd.DataFrame(
        [
            {
                "risk": "document_level_random_split",
                "affected_events": int(len(multi_doc_events)),
                "affected_documents": int(multi_doc_events["n_documents"].sum()),
                "recommendation": "Split by event_id (SEC file number), not by document/accession.",
            },
            {
                "risk": "issuer_repeated_across_splits",
                "affected_events": int((events["primary_cik"].value_counts() > 1).sum())
                if events["primary_cik"].notna().any()
                else 0,
                "affected_documents": None,
                "recommendation": "Consider issuer/CIK-aware splits for generalization tests.",
            },
            {
                "risk": "weak_event_key_without_file_num",
                "affected_events": int(len(weak_events)),
                "affected_documents": int(
                    docs[docs["event_id"].astype(str).str.startswith("NO_FILE_NUM:")].shape[0]
                ),
                "recommendation": "Manually review fallback event keys before amendment evaluation.",
            },
        ]
    )

    return {
        "missing_metadata": missing_meta,
        "cik_name_inconsistencies": name_variance.head(30),
        "duplicate_accession_filename": dup_docs,
        "events_without_file_number": weak_events[
            ["event_id", "primary_entity", "n_documents", "n_filings", "forms"]
        ].head(30)
        if not weak_events.empty
        else weak_events,
        "leakage_risks": leakage,
        "broken_links_note": (
            "Broken document URLs are measured only for downloaded samples "
            "(see content sample status counts). Full-corpus link checks were not executed."
        ),
        "parsing_failures_note": (
            "Parsing failures are recorded in content sample statuses "
            "(download_or_parse_failed / empty / empty_after_parse)."
        ),
    }
