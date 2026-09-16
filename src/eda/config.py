"""Paths and constants for tender-offer EDA."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CORPUS_DIR = DATA_DIR / "corpus"
FIGURES_DIR = PROJECT_ROOT / "figures"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"

# Observed EFTS form labels (note: 14D-9 appears as SC 14D9, not SC 14D-9).
TENDER_FORMS = [
    "SC TO-T",
    "SC TO-T/A",
    "SC TO-I",
    "SC TO-I/A",
    "SC 14D9",
    "SC 14D9/A",
]

FORM_FAMILIES = {
    "SC TO-T": "third_party_tender",
    "SC TO-T/A": "third_party_tender",
    "SC TO-I": "issuer_tender",
    "SC TO-I/A": "issuer_tender",
    "SC 14D9": "target_recommendation",
    "SC 14D9/A": "target_recommendation",
}

AMENDMENT_FORMS = {"SC TO-T/A", "SC TO-I/A", "SC 14D9/A"}
INITIAL_FORMS = {"SC TO-T", "SC TO-I", "SC 14D9"}

# SEC requires a descriptive User-Agent with contact information.
SEC_USER_AGENT = "BNY Capstone Research kedartvaidya@gmail.com"
SEC_REQUEST_PAUSE_SEC = 0.25

DEFAULT_START = "2020-01-01"
DEFAULT_END = "2025-12-31"

# Broad lexical query used only to satisfy EFTS' required `q` parameter.
# Coverage is validated against form filters; this is NOT a semantic filter claim.
EFTS_BROAD_QUERY = "a OR the OR of"