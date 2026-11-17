"""Measure settlement_date rules against cleaned filing text (not GT quotes).

For every GT row with a calendar-date settlement_date (notebooks/evaluation/tender_offers_clean.csv),
read the cleaned filing text of its event and run:
  current   - src.preprocess.rules_ids.find_settlement (what the pipeline does today)
  candidate - find_settlement_v2 below (proximity scoring over all dates in the filing)
Reports correct / emitted (precision) and correct / gold rows (recall) per variant.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.preprocess.rules_ids import find_settlement, find_settlement_date  # noqa: E402

GT = ROOT / "notebooks/evaluation/tender_offers_clean.csv"
EVENTS = ROOT / "data/preprocess/tender/events"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
DATE_RE = re.compile(
    rf"\b(?:(\d{{1,2}})/(\d{{1,2}})/(\d{{4}})|({'|'.join(m.title() for m in MONTHS)})\s+(\d{{1,2}}),?\s+(\d{{4}}))\b",
    re.I,
)
# Words that make a date a payment/settlement date.
PAY = re.compile(
    r"\b(paid|pay(?:ment)?|wired|wire|settle(?:ment)?|cash\s+payment|accepted\s+for\s+(?:payment|purchase)|"
    r"purchase\s+price|consideration|disbursed|deposit(?:ed)?|issued)\b",
    re.I,
)
# Words that make a date something else.
NOT_PAY = re.compile(
    r"\b(expir\w*|withdraw\w*|commence\w*|dated|filed|filing|record\s+date|valuation\s+date|"
    r"notice|announce\w*|termination|effective|tender\w*\s+period)\b",
    re.I,
)
WINDOW = 160


def all_dates(text: str) -> list[tuple[int, str]]:
    out = []
    for m in DATE_RE.finditer(text):
        if m.group(1):
            mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            mo, da, yr = MONTHS.index(m.group(4).lower()) + 1, int(m.group(5)), int(m.group(6))
        out.append((m.start(), f"{mo}/{da}/{yr}"))
    return out


STRONG_PAY_BEFORE = re.compile(
    r"(?i)(paid|wired|wire|payment\s+(?:will\s+be\s+made|was\s+made|is\s+made)|pay(?:ment)?\s+(?:on|by|no\s+later\s+than)|"
    r"no\s+later\s+than|on\s+or\s+about|to\s+be\s+paid\s+on)\s*(?:on\s+or\s+about\s+|on\s+|by\s+|no\s+later\s+than\s+)?$"
)
AS_OF = re.compile(r"(?i)(as\s+of|valuation\s+date|net\s+asset\s+value\s+(?:as\s+of|per\s+\w+\s+as\s+of)|fiscal\s+year|year\s+ended)\s*$")


def find_settlement_v2(text: str) -> str | None:
    """Best calendar date near a payment cue; penalize valuation/NAV/fiscal-year dates; no templates."""
    best: tuple[float, str] | None = None
    for pos, date in all_dates(text):
        lo, hi = max(0, pos - WINDOW), min(len(text), pos + WINDOW)
        window = text[lo:hi]
        pay_hits = len(PAY.findall(window))
        if not pay_hits:
            continue
        neg_hits = len(NOT_PAY.findall(text[max(0, pos - 60): pos + 60]))
        score = pay_hits - 2 * neg_hits - abs(pos - (lo + hi) / 2) / WINDOW
        before = text[max(0, pos - 40): pos]
        if STRONG_PAY_BEFORE.search(before):
            score += 2
        if AS_OF.search(before):
            score -= 3
        if best is None or score > best[0]:
            best = (score, date)
    return best[1] if best and best[0] > 0 else None


def _same(pred: str | None, gold: str) -> bool:
    if not pred:
        return False
    p = all_dates(pred)
    g = all_dates(gold)
    return bool(p and g and p[0][1] == g[0][1])


def event_text(event_id: str, accession: str) -> str:
    d = EVENTS / event_id / "clean"
    files = sorted(d.glob(f"{accession}__*.txt")) if d.exists() else []
    return "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in files)


def main() -> None:
    from src.evaluation.tender import gt_event_ids_from_corpus

    g = pd.read_csv(GT, dtype=str, keep_default_na=False)
    rows = g[g.settlement_date.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$")].copy()
    acc2eid = gt_event_ids_from_corpus(set(rows.accession_number), ROOT / "data/processed/documents.parquet")
    stats = {"current": Counter(), "candidate": Counter()}
    n_text = 0
    for _, r in rows.iterrows():
        eid = acc2eid.get(r.accession_number)
        if not eid:
            stats["current"]["no_event"] += 1
            continue
        text = event_text(eid, r.accession_number)
        if not text:
            stats["current"]["no_text"] += 1
            continue
        n_text += 1
        for name, fn in (("current", find_settlement), ("candidate", find_settlement_date)):
            pred = fn(text)
            stats[name]["gold"] += 1
            if pred:
                stats[name]["emitted"] += 1
                if _same(pred, r.settlement_date):
                    stats[name]["correct"] += 1
    print(f"date-gold rows: {len(rows)}; with cleaned text: {n_text}")
    for name, c in stats.items():
        em, co, gd = c["emitted"], c["correct"], c["gold"]
        p = co / em if em else 0.0
        rc = co / gd if gd else 0.0
        print(f"{name:10s} emitted={em:3d} correct={co:3d} precision={p:.2f} recall={rc:.2f}  (gold={gd})")


if __name__ == "__main__":
    main()
