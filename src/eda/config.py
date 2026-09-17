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
# Current collected corpus = tender track only.
TENDER_FORMS = [
    "SC TO-T",
    "SC TO-T/A",
    "SC TO-I",
    "SC TO-I/A",
    "SC 14D9",
    "SC 14D9/A",
]

# Target public forms for the multi-type MVP datastore (tender / exchange / rights / merger / conversion).
# EFTS labels: SC 14D9 (not 14D-9), SC 13E3 (not 13E-3).
MVP_TARGET_FORMS = [
    # Tender + target recommendation
    "SC TO-T",
    "SC TO-T/A",
    "SC TO-I",
    "SC TO-I/A",
    "SC 14D9",
    "SC 14D9/A",
    # Exchange / merger registration & proxies
    "S-4",
    "S-4/A",
    "DEFM14A",
    "PREM14A",
    "SC 13E3",
    "SC 13E3/A",
    "425",
    # Rights / conversion / prospectus + current reports
    "424B2",
    "424B3",
    "424B4",
    "424B5",
    "S-3",
    "S-3ASR",
    "8-K",
]

FORM_FAMILIES = {
    "SC TO-T": "third_party_tender",
    "SC TO-T/A": "third_party_tender",
    "SC TO-I": "issuer_tender",
    "SC TO-I/A": "issuer_tender",
    "SC 14D9": "target_recommendation",
    "SC 14D9/A": "target_recommendation",
    "S-4": "registration_exchange_merger",
    "S-4/A": "registration_exchange_merger",
    "DEFM14A": "merger_proxy",
    "PREM14A": "merger_proxy",
    "SC 13E3": "going_private",
    "SC 13E3/A": "going_private",
    "425": "business_combination_comms",
    "424B2": "prospectus_supplement",
    "424B3": "prospectus_supplement",
    "424B4": "prospectus_supplement",
    "424B5": "prospectus_supplement",
    "S-3": "shelf_registration",
    "S-3ASR": "shelf_registration",
    "8-K": "current_report",
}

AMENDMENT_FORMS = {
    "SC TO-T/A",
    "SC TO-I/A",
    "SC 14D9/A",
    "S-4/A",
    "SC 13E3/A",
}
INITIAL_FORMS = {
    "SC TO-T",
    "SC TO-I",
    "SC 14D9",
    "S-4",
    "DEFM14A",
    "PREM14A",
    "SC 13E3",
    "424B2",
    "424B3",
    "424B4",
    "424B5",
    "S-3",
    "S-3ASR",
    "8-K",
    "425",
}

# Broad lexical query used only to satisfy EFTS' required `q` parameter.
# Coverage is validated against form filters; this is NOT a semantic filter claim.
EFTS_BROAD_QUERY = "a OR the OR of"

# Semantic filters for high-volume form types (8-K, 424B*) so we keep corporate-action relevance.
EFTS_RIGHTS_QUERY = (
    '"rights offering" OR "subscription rights" OR "rights issue" OR "oversubscription privilege"'
)
EFTS_CONVERSION_QUERY = (
    '"conversion rate" OR "conversion price" OR "mandatory conversion" OR '
    '"convertible notes" OR "convertible senior notes"'
)

# Collection tracks for scripts/build_corpus.py.
# Request base forms only (not "/A"); EFTS returns amendments with the base form.
COLLECTION_TRACKS: dict[str, dict] = {
    "tender": {
        "mvp_event_types": ["tender_offer"],
        "forms": ["SC TO-T", "SC TO-I", "SC 14D9"],
        "q": EFTS_BROAD_QUERY,
    },
    "merger_exchange": {
        "mvp_event_types": ["merger", "exchange_offer"],
        "forms": ["S-4", "DEFM14A", "PREM14A", "SC 13E3", "425"],
        "q": EFTS_BROAD_QUERY,
    },
    "rights": {
        "mvp_event_types": ["rights_issue"],
        "forms": ["424B2", "424B3", "424B5"],
        "q": EFTS_RIGHTS_QUERY,
    },
    "conversion": {
        "mvp_event_types": ["conversion"],
        "forms": ["8-K"],
        "q": EFTS_CONVERSION_QUERY,
    },
}

# BNY-facing MVP corporate-action classes (notification datastore target types).
MVP_CORPORATE_ACTION_TYPES = [
    "tender_offer",
    "exchange_offer",
    "rights_issue",
    "merger",
    "conversion",
]

# SEC requires a descriptive User-Agent with contact information.
SEC_USER_AGENT = "BNY Capstone Research kedartvaidya@gmail.com"
SEC_REQUEST_PAUSE_SEC = 0.25

DEFAULT_START = "2020-01-01"
DEFAULT_END = "2025-12-31"