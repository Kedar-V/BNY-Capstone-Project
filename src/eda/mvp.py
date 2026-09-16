"""Modeling / MVP design recommendations derived from observed EDA tables."""

from __future__ import annotations

import pandas as pd


def _forms_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return [str(x) for x in value.tolist()]
    except Exception:  # noqa: BLE001
        pass
    return [str(value)]


def recommend_mvp_design(
    docs: pd.DataFrame,
    events: pd.DataFrame,
    field_coverage: pd.DataFrame | None = None,
) -> dict:
    """
    Produce split and subset recommendations from observed corpus statistics.

    Does not invent labels. Ground-truth suitability is based on whether a field is
    directly available as structured metadata vs only heuristically mentioned in text.
    """
    if events.empty:
        return {"note": "empty events table"}

    ev = events.copy()
    ev["forms_list"] = ev["forms"].apply(_forms_list)
    ev["has_to_t"] = ev["forms_list"].apply(lambda fs: any(f.startswith("SC TO-T") for f in fs))
    ev["has_to_i"] = ev["forms_list"].apply(lambda fs: any(f.startswith("SC TO-I") for f in fs))
    ev["has_14d9"] = ev["forms_list"].apply(lambda fs: any(f.startswith("SC 14D9") for f in fs))

    # MVP: third-party tender events (including those also carrying 14D9 on same file number)
    mvp_events = ev[
        ev["has_to_t"] & (~ev["event_id"].astype(str).str.startswith("NO_FILE_NUM:"))
    ].copy()

    amendment_eval = mvp_events[mvp_events["has_amendment"]].copy()
    amendment_eval_simple = amendment_eval[
        (amendment_eval["n_amendment_filings"].between(1, 5))
        & (amendment_eval["n_documents"] <= 60)
    ]
    amendment_eval_complex = amendment_eval[
        (amendment_eval["n_amendment_filings"] >= 6) | (amendment_eval["n_documents"] > 60)
    ]

    notif_events = mvp_events[mvp_events["n_primary_docs"] >= 1].copy()
    issuer_stretch = ev[ev["has_to_i"] & ~ev["has_to_t"]].copy()

    n = len(mvp_events)
    split = pd.DataFrame(
        [
            {"split": "train", "target_fraction": 0.70, "approx_events_if_mvp": int(round(0.70 * n))},
            {"split": "validation", "target_fraction": 0.15, "approx_events_if_mvp": int(round(0.15 * n))},
            {"split": "test", "target_fraction": 0.15, "approx_events_if_mvp": int(round(0.15 * n))},
        ]
    )

    structured_gt = pd.DataFrame(
        [
            {"field": "corporate_action_type", "ground_truth_status": "observed_metadata", "notes": "map from SEC form family"},
            {"field": "notification_status", "ground_truth_status": "weak_from_form_suffix", "notes": "initial vs /A; cancel/withdraw needs text"},
            {"field": "filing date / accession", "ground_truth_status": "observed_metadata", "notes": "strong automatic"},
            {"field": "security_description", "ground_truth_status": "partial_metadata", "notes": "entity name proxy; true security desc needs text"},
            {"field": "ticker", "ground_truth_status": "partial_metadata", "notes": "present in ~half of EFTS display names"},
            {"field": "cusip", "ground_truth_status": "requires_annotation_or_extraction", "notes": "high mention rate in sample text"},
            {"field": "isin", "ground_truth_status": "requires_annotation_or_extraction", "notes": "rare in this U.S.-heavy sample"},
            {"field": "election_deadline / response_deadline", "ground_truth_status": "requires_annotation_or_extraction", "notes": "expiration/withdrawal language"},
            {"field": "available_options", "ground_truth_status": "requires_manual_annotation", "notes": "low mention rate; high difficulty"},
            {"field": "position_quantity / eligible_quantity / debit_credit_indicator / processing_status", "ground_truth_status": "cannot_evaluate_from_public", "notes": "BNY internal"},
            {"field": "cash_amount (client proceeds)", "ground_truth_status": "cannot_evaluate_from_public", "notes": "offer price public; client amount = price × position"},
        ]
    )

    if field_coverage is not None and not field_coverage.empty:
        cov = field_coverage.copy()
        if "pct_detected" in cov.columns and "public_coverage_pct" not in cov.columns:
            cov = cov.rename(columns={"pct_detected": "public_coverage_pct"})
        if "field" in cov.columns and "public_coverage_pct" in cov.columns:
            structured_gt = structured_gt.merge(
                cov[["field", "public_coverage_pct"]].rename(
                    columns={"public_coverage_pct": "sample_or_metadata_coverage_pct"}
                ),
                on="field",
                how="left",
            )

    return {
        "split_policy": (
            "Always split by event_id (SEC file number). Never by document. "
            "Keep all amendments with the parent event. "
            "Optionally hold out entire issuers (CIK) for a generalization fold."
        ),
        "split_table": split,
        "mvp_subset_definition": (
            "Events containing SC TO-T / SC TO-T/A (third-party tenders), including 'mixed' "
            "events that also have SC 14D9 on the same SEC file number. "
            "Issuer self-tenders (SC TO-I) are a stretch track due to volume bias toward fund repurchases."
        ),
        "mvp_event_count": int(len(mvp_events)),
        "mvp_with_14d9_count": int(mvp_events["has_14d9"].sum()) if len(mvp_events) else 0,
        "issuer_stretch_event_count": int(len(issuer_stretch)),
        "amendment_eval_simple_count": int(len(amendment_eval_simple)),
        "amendment_eval_complex_count": int(len(amendment_eval_complex)),
        "notification_eval_count": int(len(notif_events)),
        "mvp_events_preview": mvp_events.head(20)[
            ["event_id", "primary_entity", "primary_form_family", "n_filings", "n_amendment_filings", "n_documents", "event_span_days"]
        ],
        "amendment_eval_simple_preview": amendment_eval_simple.head(15)[
            ["event_id", "primary_entity", "n_amendment_filings", "n_documents", "event_span_days"]
        ],
        "amendment_eval_complex_preview": amendment_eval_complex.head(15)[
            ["event_id", "primary_entity", "n_amendment_filings", "n_documents", "event_span_days"]
        ],
        "ground_truth_field_assessment": structured_gt,
        "manual_annotation_priorities": [
            "CUSIP / security description (normalized)",
            "Offer price / consideration (maps toward cash_amount components)",
            "Expiration / election / withdrawal deadlines",
            "Available options + default option",
            "Material amendment field changes (price, deadline, conditions)",
            "notification_type mapping (BNY taxonomy vs SEC form)",
        ],
        "benchmark_field_subset_v1": [
            "corporate_action_type",
            "security_description",
            "cusip",
            "ticker",
            "election_deadline",
            "response_deadline",
            "notification_status",
            "cash_amount",  # as offer-price proxy only; label clearly
        ],
    }
