"""Missingness taxonomy and ground-truth feasibility helpers."""

from __future__ import annotations

import pandas as pd

from .bny_schema import BNY_SCHEMA, RELEVANCE_BY_ACTION


def classify_missingness(schema_coverage: pd.DataFrame, event_type_coverage: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in schema_coverage.iterrows():
        field = r["field"]
        src = r["source_class"]
        cov = r["public_coverage_pct"]
        if src == "bny_internal_only":
            miss_class = "internal_bny_only"
        elif pd.isna(cov):
            miss_class = "parsing_or_sample_gap"
        elif src == "unclear_requires_investigation":
            miss_class = "unclear_or_partially_public"
        elif cov >= 80:
            miss_class = "usually_present_in_public_sample"
        elif cov >= 20:
            miss_class = "sometimes_present_in_public_sample"
        else:
            # Use relevance assumptions across action types
            rels = []
            if not event_type_coverage.empty:
                rels = event_type_coverage.loc[
                    event_type_coverage["field"] == field, "relevance_assumption"
                ].tolist()
            if rels and all(x == "not_relevant" for x in rels):
                miss_class = "not_relevant_for_observed_event_types"
            elif rels and any(x == "optional" for x in rels):
                miss_class = "optional_for_many_events_or_absent"
            else:
                miss_class = "likely_relevant_but_rarely_detected"
        rows.append(
            {
                "field": field,
                "group": r["group"],
                "public_coverage_pct": cov,
                "missingness_class": miss_class,
                "source_class": src,
                "ground_truth_class": r["ground_truth_class"],
                "evidence_type": r["evidence_type"],
            }
        )
    return pd.DataFrame(rows)


def ground_truth_recommendations(schema_coverage: pd.DataFrame) -> pd.DataFrame:
    df = schema_coverage.copy()
    def rank(row):
        gt = row["ground_truth_class"]
        cov = row["public_coverage_pct"]
        if gt == "strong_automatic":
            return "include_in_v1_benchmark"
        if gt == "cannot_evaluate_from_public":
            return "exclude_from_public_benchmark"
        if gt == "weak_heuristic" and not pd.isna(cov) and cov >= 50:
            return "include_as_weak_proxy_only"
        if gt == "requires_manual_annotation" and not pd.isna(cov) and cov >= 40:
            return "prioritize_for_manual_annotation"
        if gt == "requires_manual_annotation":
            return "annotate_later_or_event_type_specific"
        return "investigate"
    df["benchmark_recommendation"] = df.apply(rank, axis=1)
    return df[
        [
            "field",
            "group",
            "public_coverage_pct",
            "ground_truth_class",
            "difficulty",
            "benchmark_recommendation",
            "evidence_type",
        ]
    ].sort_values(["benchmark_recommendation", "group", "field"])
