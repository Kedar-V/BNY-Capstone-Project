"""Paths and grouping rules for the shared event store.

Copied from agents/client_briefing/config.py so every agent reads the same extraction runs the same way.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EVAL_DATA = REPO / "notebooks" / "evaluation" / "data"
MERGER_CSV = EVAL_DATA / "merger_2026-01-01_2026-09-30" / "mergers.csv"
MERGER_SELECTED = EVAL_DATA / "merger_2026-01-01_2026-09-30" / "selected_filings.csv"
RIGHTS_CSV = EVAL_DATA / "rights_issue_2026-01-01_2026-09-30_500" / "rights_issues_v2.csv"
RIGHTS_SELECTED = EVAL_DATA / "rights_issue_2026-01-01_2026-09-30_500" / "selected_filings.csv"
TENDER_CSV = REPO / "notebooks" / "evaluation" / "tender_offers.csv"
TENDER_FILE_NUMBERS = REPO / "corporate-actions-demo" / "scripts" / "cache" / "file_numbers.json"

ACTIONS = ("rights_issue", "merger", "tender_offer")

# Consecutive filings by one issuer further apart than this are treated as separate rights offerings.
RIGHTS_EVENT_GAP_DAYS = 120
