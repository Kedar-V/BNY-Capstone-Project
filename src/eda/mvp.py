"""Modeling / MVP design for multi-type corporate-action notification datastore.

Target BNY event classes:
  tender_offer | exchange_offer | rights_issue | merger | conversion
"""

from __future__ import annotations

import pandas as pd

from .bny_schema import BNY_SCHEMA
from .event_taxonomy import (
    MVP_EVENT_TYPES,
    corpus_gap_table,
    taxonomy_overview_table,
)

# Core fields for the first extraction → notification benchmark (works across types).
BENCHMARK_FIELDS_V1 = [
    "corporate_action_type",
    "security_description",
    "cusip",
    "ticker",
    "election_deadline",
    "response_deadline",
    "notification_status",
    "available_options",
    "conversion_ratio",
    "cash_amount",  # consideration / offer / subscription price proxy — not client proceeds
]


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


def tag_mvp_events(events: pd.DataFrame) -> pd.DataFrame:
    """
    Tag events for the current (tender-centric) corpus.

    Until non-tender forms are collected:
      - in_mvp_core / preferred apply to third-party tenders (+ 14D9)
      - exchange_offer candidates must be detected later via text / S-4 collection
      - rights / merger / conversion remain corpus gaps
    """
    if events.empty:
        return events.copy()

    ev = events.copy()
    ev["forms_list"] = ev["forms"].apply(_forms_list)
    ev["has_to_t"] = ev["forms_list"].apply(lambda fs: any(str(f).startswith("SC TO-T") for f in fs))
    ev["has_to_i"] = ev["forms_list"].apply(lambda fs: any(str(f).startswith("SC TO-I") for f in fs))
    ev["has_14d9"] = ev["forms_list"].apply(lambda fs: any(str(f).startswith("SC 14D9") for f in fs))
    ev["has_file_num"] = ~ev["event_id"].astype(str).str.startswith("NO_FILE_NUM:")

    # Provisional type assignment from forms only (no invented labels).
    def _provisional_type(row) -> str:
        if row["has_to_t"] or row["has_to_i"]:
            return "tender_offer"  # may later reclassify some as exchange_offer via text
        return "unknown"

    ev["mvp_event_type_provisional"] = ev.apply(_provisional_type, axis=1)
    ev["in_mvp_core"] = ev["has_to_t"] & ev["has_file_num"]
    ev["in_mvp_preferred"] = ev["in_mvp_core"] & ev["has_14d9"]
    ev["in_mvp_stretch"] = ev["has_to_i"] & ~ev["has_to_t"] & ev["has_file_num"]

    ev["amendment_eval_band"] = "out_of_mvp"
    core = ev["in_mvp_core"] & ev["has_amendment"]
    simple = core & ev["n_amendment_filings"].between(1, 5) & (ev["n_documents"] <= 60)
    complex_ = core & ((ev["n_amendment_filings"] >= 6) | (ev["n_documents"] > 60))
    ev.loc[simple, "amendment_eval_band"] = "simple"
    ev.loc[complex_, "amendment_eval_band"] = "complex"
    ev.loc[core & ~(simple | complex_), "amendment_eval_band"] = "other_mvp"

    return ev


def mvp_selection_funnel(events: pd.DataFrame) -> pd.DataFrame:
    """Event counts at each gate for the current tender MVP datastore."""
    ev = tag_mvp_events(events) if "in_mvp_core" not in events.columns else events
    stages = [
        ("all_events_in_corpus", len(ev)),
        ("has_sec_file_num", int(ev["has_file_num"].sum())),
        ("tender_mvp_core_to_t", int(ev["in_mvp_core"].sum())),
        ("tender_preferred_to_t_plus_14d9", int(ev["in_mvp_preferred"].sum())),
        (
            "tender_preferred_with_amendments",
            int((ev["in_mvp_preferred"] & ev["has_amendment"]).sum()),
        ),
        ("issuer_tender_stretch_to_i_only", int(ev["in_mvp_stretch"].sum())),
    ]
    return pd.DataFrame(stages, columns=["stage", "n_events"])


def build_datastore_field_catalog(schema_coverage: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Map each BNY schema field to its role in the MVP event datastore / notification draft.

    Roles:
      extract_from_public  — store value extracted from SEC docs
      derive_from_public    — store derived/normalized label from public signals
      annotate_then_store   — needs manual GT before reliable extraction eval
      bny_placeholder       — keep column for demo parity; fill with null/synthetic
      exclude_or_investigate — unclear relevance or hybrid public×internal
    """
    cov_map: dict[str, dict] = {}
    if schema_coverage is not None and not schema_coverage.empty:
        for _, row in schema_coverage.iterrows():
            cov_map[row["field"]] = row.to_dict()

    rows = []
    for field in BNY_SCHEMA:
        cov = cov_map.get(field.name, {})
        coverage = cov.get("public_coverage_pct")

        if field.source_class == "bny_internal_only":
            role = "bny_placeholder"
            notification_ready = "placeholder_only"
        elif field.source_class == "unclear_requires_investigation":
            role = "exclude_or_investigate"
            notification_ready = "no_client_amount_without_position"
        elif field.ground_truth == "strong_automatic":
            role = "derive_from_public" if field.explicit_or_derived == "derived" else "extract_from_public"
            notification_ready = "yes_metadata"
        elif field.ground_truth == "weak_heuristic":
            role = "derive_from_public" if field.explicit_or_derived == "derived" else "extract_from_public"
            notification_ready = "yes_with_caveat"
        elif field.ground_truth == "requires_manual_annotation":
            role = "annotate_then_store"
            notification_ready = "after_annotation"
        else:
            role = "exclude_or_investigate"
            notification_ready = "no"

        # Which MVP event types typically need this field
        type_relevance = []
        from .event_taxonomy import RELEVANCE_BY_MVP_TYPE

        for tkey, relmap in RELEVANCE_BY_MVP_TYPE.items():
            rel = relmap.get(field.name, "relevant")
            if rel != "not_relevant":
                type_relevance.append(tkey)

        rows.append(
            {
                "field": field.name,
                "group": field.group,
                "source_class": field.source_class,
                "explicit_or_derived": field.explicit_or_derived,
                "ground_truth_class": field.ground_truth,
                "difficulty": field.default_difficulty,
                "public_coverage_pct": coverage,
                "datastore_role": role,
                "in_v1_benchmark": field.name in BENCHMARK_FIELDS_V1,
                "notification_ready": notification_ready,
                "relevant_mvp_types": ",".join(type_relevance),
                "relevance_note": field.relevance_note,
            }
        )
    return pd.DataFrame(rows)


def recommend_mvp_design(
    docs: pd.DataFrame,
    events: pd.DataFrame,
    field_coverage: pd.DataFrame | None = None,
) -> dict:
    """Produce split, taxonomy-gap, and datastore recommendations from observed stats."""
    if events.empty:
        return {"note": "empty events table"}

    ev = tag_mvp_events(events)
    mvp_events = ev[ev["in_mvp_core"]].copy()
    preferred = ev[ev["in_mvp_preferred"]].copy()
    amendment_eval_simple = ev[ev["amendment_eval_band"] == "simple"].copy()
    amendment_eval_complex = ev[ev["amendment_eval_band"] == "complex"].copy()
    notif_events = mvp_events[mvp_events["n_primary_docs"] >= 1].copy()
    issuer_stretch = ev[ev["in_mvp_stretch"]].copy()
    funnel = mvp_selection_funnel(ev)
    catalog = build_datastore_field_catalog(field_coverage)

    collected_forms = set(docs["form"].dropna().astype(str).unique()) if not docs.empty else set()
    gaps = corpus_gap_table(collected_forms)
    taxonomy = taxonomy_overview_table()

    n = len(mvp_events)
    split = pd.DataFrame(
        [
            {"split": "train", "target_fraction": 0.70, "approx_events_if_tender_mvp": int(round(0.70 * n))},
            {"split": "validation", "target_fraction": 0.15, "approx_events_if_tender_mvp": int(round(0.15 * n))},
            {"split": "test", "target_fraction": 0.15, "approx_events_if_tender_mvp": int(round(0.15 * n))},
        ]
    )

    preview_cols = [
        "event_id",
        "primary_entity",
        "primary_form_family",
        "mvp_event_type_provisional",
        "n_filings",
        "n_amendment_filings",
        "n_documents",
        "event_span_days",
        "has_14d9",
        "in_mvp_preferred",
        "amendment_eval_band",
    ]

    build_order = pd.DataFrame(
        [
            {
                "phase": 1,
                "mvp_event_type": "tender_offer",
                "action": "Build event datastore + extraction + notification draft on SC TO-T + 14D9",
                "corpus_ready": True,
            },
            {
                "phase": 2,
                "mvp_event_type": "exchange_offer",
                "action": "Reclassify exchange language inside TO; add S-4 collection",
                "corpus_ready": False,
            },
            {
                "phase": 3,
                "mvp_event_type": "merger",
                "action": "Collect DEFM14A / S-4 / SC 13E-3; election-options benchmark",
                "corpus_ready": False,
            },
            {
                "phase": 4,
                "mvp_event_type": "rights_issue",
                "action": "Collect 424B* / S-3 rights offerings; record/ex/subscription fields",
                "corpus_ready": False,
            },
            {
                "phase": 5,
                "mvp_event_type": "conversion",
                "action": "Collect 8-K / prospectus conversion notices; ratio/price benchmark",
                "corpus_ready": False,
            },
        ]
    )

    return {
        "target_event_types": [t.key for t in MVP_EVENT_TYPES],
        "split_policy": (
            "Always split by event_id (SEC file number / future event key). Never by document. "
            "Keep all amendments with the parent event. "
            "Optionally hold out entire issuers (CIK) for a generalization fold."
        ),
        "split_table": split,
        "mvp_subset_definition": (
            "Target classes: tender offers, exchange offers, rights issues, mergers, conversions. "
            "v1 executable subset: third-party tenders (SC TO-T[/A]) preferably with SC 14D9. "
            "Issuer TO-I is stretch. Exchange/rights/merger/conversion need corpus expansion."
        ),
        "mvp_pipeline": (
            "public SEC docs (by event type) → versioned event datastore → field extraction + citations "
            "→ BNY-shaped notification draft → amendment deltas → escalate gaps / internal placeholders"
        ),
        "mvp_event_count": int(len(mvp_events)),
        "mvp_preferred_count": int(len(preferred)),
        "mvp_with_14d9_count": int(mvp_events["has_14d9"].sum()) if len(mvp_events) else 0,
        "issuer_stretch_event_count": int(len(issuer_stretch)),
        "amendment_eval_simple_count": int(len(amendment_eval_simple)),
        "amendment_eval_complex_count": int(len(amendment_eval_complex)),
        "notification_eval_count": int(len(notif_events)),
        "funnel": funnel,
        "taxonomy_overview": taxonomy,
        "corpus_gaps": gaps,
        "build_order": build_order,
        "tagged_events": ev,
        "mvp_events": mvp_events,
        "mvp_preferred_events": preferred,
        "datastore_field_catalog": catalog,
        "mvp_events_preview": mvp_events.head(20)[[c for c in preview_cols if c in mvp_events.columns]],
        "amendment_eval_simple_preview": amendment_eval_simple.head(15)[
            [c for c in preview_cols if c in amendment_eval_simple.columns]
        ],
        "amendment_eval_complex_preview": amendment_eval_complex.head(15)[
            [c for c in preview_cols if c in amendment_eval_complex.columns]
        ],
        "ground_truth_field_assessment": catalog[
            [
                "field",
                "ground_truth_class",
                "datastore_role",
                "public_coverage_pct",
                "in_v1_benchmark",
                "notification_ready",
                "relevant_mvp_types",
                "relevance_note",
            ]
        ],
        "manual_annotation_priorities": [
            "CUSIP / security description (normalized)",
            "Offer / exchange / subscription consideration",
            "Expiration / election / withdrawal deadlines",
            "Available options + default option (esp. mergers & rights)",
            "Exchange / conversion ratios and prices",
            "Material amendment field changes",
            "notification_type mapping (BNY taxonomy vs SEC form)",
            "Event-type labels for exchange vs cash tender inside Schedule TO",
        ],
        "benchmark_field_subset_v1": list(BENCHMARK_FIELDS_V1),
    }
