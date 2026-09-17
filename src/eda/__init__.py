"""Reusable EDA utilities for public corporate-action docs vs BNY notification schema.

MVP event types: tender offers, exchange offers, rights issues, mergers, conversions.

Import from submodules directly, e.g. ``from eda.mvp import BENCHMARK_FIELDS_V1``.
This package ``__init__`` stays lightweight so notebook kernels pick up code changes
without fighting a partially cached import graph.
"""

from .config import (
    CORPUS_DIR,
    FIGURES_DIR,
    MVP_CORPORATE_ACTION_TYPES,
    MVP_TARGET_FORMS,
    PROCESSED_DIR,
    RAW_DIR,
    TENDER_FORMS,
)

__all__ = [
    "BENCHMARK_FIELDS_V1",
    "BNY_SCHEMA",
    "CORPUS_DIR",
    "FIGURES_DIR",
    "MVP_CORPORATE_ACTION_TYPES",
    "MVP_EVENT_TYPES",
    "MVP_TARGET_FORMS",
    "PROCESSED_DIR",
    "RAW_DIR",
    "TENDER_FORMS",
    "load_corpus",
    "build_document_table",
    "build_event_table",
    "build_datastore_field_catalog",
    "corpus_gap_table",
    "taxonomy_overview_table",
    "summarize_dataset",
    "analyze_events",
    "analyze_documents",
    "analyze_field_availability",
    "analyze_amendments",
    "analyze_data_quality",
    "analyze_schema_coverage",
    "classify_missingness",
    "ground_truth_recommendations",
    "mvp_selection_funnel",
    "recommend_mvp_design",
    "tag_mvp_events",
]


def __getattr__(name: str):
    """Lazy attribute access for common symbols (PEP 562)."""
    if name == "BNY_SCHEMA":
        from .bny_schema import BNY_SCHEMA

        return BNY_SCHEMA
    if name in {"MVP_EVENT_TYPES", "corpus_gap_table", "taxonomy_overview_table"}:
        from . import event_taxonomy

        return getattr(event_taxonomy, name)
    if name in {
        "BENCHMARK_FIELDS_V1",
        "build_datastore_field_catalog",
        "mvp_selection_funnel",
        "recommend_mvp_design",
        "tag_mvp_events",
    }:
        from . import mvp

        return getattr(mvp, name)
    if name in {"load_corpus", "build_document_table", "build_event_table"}:
        from . import corpus

        return getattr(corpus, name)
    if name == "summarize_dataset":
        from .overview import summarize_dataset

        return summarize_dataset
    if name == "analyze_events":
        from .events import analyze_events

        return analyze_events
    if name == "analyze_documents":
        from .documents import analyze_documents

        return analyze_documents
    if name == "analyze_field_availability":
        from .fields import analyze_field_availability

        return analyze_field_availability
    if name == "analyze_amendments":
        from .amendments import analyze_amendments

        return analyze_amendments
    if name == "analyze_data_quality":
        from .quality import analyze_data_quality

        return analyze_data_quality
    if name == "analyze_schema_coverage":
        from .schema_coverage import analyze_schema_coverage

        return analyze_schema_coverage
    if name in {"classify_missingness", "ground_truth_recommendations"}:
        from . import missingness

        return getattr(missingness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
