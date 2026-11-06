"""Paths and business rules for the amendment impact agent."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# Simulated client positions, shared with the client briefing agent
CLIENTS_JSON = REPO / "agents" / "client_briefing" / "clients.json"

OUTPUT_DIR = HERE / "output"  # real amendments from the extraction runs
SYNTHETIC_DIR = HERE / "synthetic"  # synthetic amendments with an answer key
LLM_CACHE = HERE / "llm_cache.json"

# SEC Rule 14e-1(b): a tender offer must stay open at least 10 business days after a price change is announced.
# Holidays are ignored, as in the briefing agent's cut-off rule.
PRICE_CHANGE_MIN_BUSINESS_DAYS = 10

LLM_TIMEOUT_SECONDS = 180
LLM_WORKERS = 4
