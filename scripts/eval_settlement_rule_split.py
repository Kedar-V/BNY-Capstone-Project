"""Score find_settlement_date on date-gold rows split into two halves by accession hash.

Tune on half A, report half B as held-out (and the reverse). Uses cleaned filing text.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.tender import gt_event_ids_from_corpus  # noqa: E402
from src.preprocess import rules_ids  # noqa: E402


def load_rows():
    g = pd.read_csv(ROOT / "notebooks/evaluation/tender_offers_clean.csv", dtype=str, keep_default_na=False)
    dated = g[g.settlement_date.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$")].copy()
    eids = gt_event_ids_from_corpus(set(dated.accession_number), ROOT / "data/processed/documents.parquet")
    rows = []
    for _, r in dated.iterrows():
        e = eids.get(r.accession_number)
        files = list((ROOT / "data/preprocess/tender/events" / e / "clean").glob(f"{r.accession_number}__*.txt")) if e else []
        if not files:
            continue
        text = "\n".join(f.read_text(errors="ignore") for f in files)
        half = int(hashlib.md5(r.accession_number.encode()).hexdigest(), 16) % 2
        rows.append((r.accession_number, half, r.settlement_date, text))
    return rows


def score(rows, fn, half=None):
    sel = [x for x in rows if half is None or x[1] == half]
    ok = sum(1 for _, _, gold, text in sel if fn(text) == gold)
    return ok, len(sel)


if __name__ == "__main__":
    rows = load_rows()
    fn = rules_ids.find_settlement_date
    for h in (0, 1):
        ok, n = score(rows, fn, h)
        print(f"half {h}: {ok}/{n} = {ok / n:.0%}")
    ok, n = score(rows, fn)
    print(f"all: {ok}/{n} = {ok / n:.0%}")
