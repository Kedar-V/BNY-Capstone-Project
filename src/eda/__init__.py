"""Reusable EDA utilities for U.S. tender-offer SEC filings vs BNY notification schema."""

from .config import CORPUS_DIR, FIGURES_DIR, PROCESSED_DIR, RAW_DIR, TENDER_FORMS
from .corpus import build_document_table, build_event_table, load_corpus
from .overview import summarize_dataset
from .events import analyze_events
from .documents import analyze_documents
from .fields import analyze_field_availability
from .amendments import analyze_amendments
from .quality import analyze_data_quality
from .mvp import recommend_mvp_design
from .bny_schema import BNY_SCHEMA
from .schema_coverage import analyze_schema_coverage
from .missingness import classify_missingness, ground_truth_recommendations

__all__ = [
    "BNY_SCHEMA",
    "CORPUS_DIR",
    "FIGURES_DIR",
    "PROCESSED_DIR",
    "RAW_DIR",
    "TENDER_FORMS",
    "load_corpus",
    "build_document_table",
    "build_event_table",
    "summarize_dataset",
    "analyze_events",
    "analyze_documents",
    "analyze_field_availability",
    "analyze_amendments",
    "analyze_data_quality",
    "analyze_schema_coverage",
    "classify_missingness",
    "ground_truth_recommendations",
    "recommend_mvp_design",
]