"""Paths and business rules for the client briefing agent."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

EVAL_DATA = REPO / "notebooks" / "evaluation" / "data"
MERGER_CSV = EVAL_DATA / "merger_2026-01-01_2026-09-30" / "mergers.csv"
MERGER_SELECTED = EVAL_DATA / "merger_2026-01-01_2026-09-30" / "selected_filings.csv"
RIGHTS_CSV = EVAL_DATA / "rights_issue_2026-01-01_2026-09-30_500" / "rights_issues_v2.csv"
RIGHTS_SELECTED = EVAL_DATA / "rights_issue_2026-01-01_2026-09-30_500" / "selected_filings.csv"
TENDER_CSV = REPO / "notebooks" / "evaluation" / "tender_offers.csv"
TENDER_FILE_NUMBERS = REPO / "corporate-actions-demo" / "scripts" / "cache" / "file_numbers.json"

# The switch for what the brief covers. Remove an action here and rebuild: it leaves the brief and the demo's filter.
ENABLED_ACTIONS = ("rights_issue", "merger", "tender_offer")

CLIENTS_JSON = HERE / "clients.json"
GOLD_JSON = HERE / "eval" / "rights_gold_500.json"
NARRATIVE_CACHE = HERE / "narrative_cache.json"
DEMO_OUT = REPO / "corporate-actions-demo" / "src" / "data" / "briefs.json"

# Illustrative rule: BNY's real cut-offs vary by event and market. Shown as an assumption in the brief.
CUTOFF_BUSINESS_DAYS = 3
# A deadline whose BNY cut-off falls within this many days is "Action needed"; later ones are "On the horizon".
ACTION_WINDOW_DAYS = 14
LOOKBACK_DAYS = {"daily": 1, "weekly": 7}
# Events with no key date and no filing for this long drop out of the brief.
STALE_DAYS = 120
# Consecutive filings by one issuer further apart than this are treated as separate rights offerings.
RIGHTS_EVENT_GAP_DAYS = 120

LLM_MAX_ATTEMPTS = 2
LLM_TIMEOUT_SECONDS = 180
LLM_WORKERS = 4
