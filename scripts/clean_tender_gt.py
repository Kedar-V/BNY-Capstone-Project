"""Rule-based cleanup of the tender GT until it is regenerated.

Reads  notebooks/evaluation/tender_offers.csv            (unchanged)
Writes notebooks/evaluation/tender_offers_clean.csv

Only the fields with true GT problems are touched (see outputs/tender_eval/tender_gt_problem_examples.csv):

settlement_date      -> date-only (M/D/YYYY, payment date preferred) ; original kept in `settlement_date_raw`;
                        labeled parts split into settlement_acceptance / settlement_payment / settlement_other.
withdrawal_deadline  -> leading deadline only ; the conditional-withdrawal clause moves to `withdrawal_conditions`.

Every change is recorded per row in `gt_clean_notes`. Nothing is inferred beyond what the cell already says.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "notebooks/evaluation/tender_offers.csv"
OUT = ROOT / "notebooks/evaluation/tender_offers_clean.csv"

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_NAME = re.compile(rf"\b({'|'.join(MONTHS)})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
ABSENT = {"", "n/a", "none", "-"}

NEW_COLUMNS = [
    "settlement_date_raw", "settlement_acceptance", "settlement_payment", "settlement_other",
    "withdrawal_conditions", "gt_clean_notes",
]


def absent(v: str) -> bool:
    return v.strip().lower() in ABSENT


def first_date(text: str) -> str | None:
    """First calendar date in text, normalized to M/D/YYYY (no leading zeros)."""
    hits = []
    for m in _NUM.finditer(text):
        hits.append((m.start(), int(m[1]), int(m[2]), int(m[3])))
    for m in _NAME.finditer(text):
        hits.append((m.start(), MONTHS.index(m[1].lower()) + 1, int(m[2]), int(m[3])))
    if not hits:
        return None
    _, mo, da, yr = min(hits)
    return f"{mo}/{da}/{yr}"


def split_parts(value: str) -> list[tuple[str, str]]:
    """'Acceptance: x | Payment: y' -> [('Acceptance','x'), ('Payment','y')]; unlabeled -> ('', text)."""
    out = []
    for part in value.split("|"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"([A-Za-z][A-Za-z ]{1,40}):\s*(.*)$", part)
        out.append((m.group(1).strip(), m.group(2).strip()) if m else ("", part))
    return out


def clean_settlement(row: dict[str, str], notes: list[str]) -> None:
    raw = row["settlement_date"]
    row["settlement_date_raw"] = raw
    for k in ("settlement_acceptance", "settlement_payment", "settlement_other"):
        row[k] = ""
    if absent(raw):
        return
    acc, pay, other = [], [], []
    for label, text in split_parts(raw):
        low = label.lower()
        item = f"{label}: {text}" if label and low not in {"acceptance", "payment"} else text
        if "accept" in low and "payment" not in low.replace("acceptance for payment", ""):
            acc.append(item)
        elif "accept" in low and "payment" in low:  # "Acceptance and payment", "Acceptance for payment"
            acc.append(item)
            if "and payment" in low:
                pay.append(item)
        elif "payment" in low or low in {"expected payment"}:
            pay.append(item)
        elif label == "":
            # unlabeled single value: treat as payment timing (the prompt's field is "acceptance for payment and payment")
            pay.append(item)
        else:
            other.append(item)
    row["settlement_acceptance"] = " | ".join(acc)
    row["settlement_payment"] = " | ".join(pay)
    row["settlement_other"] = " | ".join(other)

    date = None
    for bucket in (pay, acc, other):
        for item in bucket:
            date = first_date(item)
            if date:
                break
        if date:
            break
    if date:
        row["settlement_date"] = date
        notes.append(f"settlement_date: reduced to date {date} (first date in payment, else acceptance part); full text in settlement_date_raw")
    else:
        row["settlement_date"] = ""
        notes.append("settlement_date: blank (filing gives only relative timing); text kept in settlement_date_raw/settlement_payment")


def clean_withdrawal(row: dict[str, str], notes: list[str]) -> None:
    v = row["withdrawal_deadline"]
    row["withdrawal_conditions"] = ""
    if absent(v) or len(v) <= 60:
        return
    m = re.search(r"\s*\|\s*|;\s+", v)
    head, rest = (v[: m.start()], v[m.end():]) if m else (v, "")
    head, rest = head.strip(), rest.strip()
    if not first_date(head):
        notes.append("withdrawal_deadline: no leading date; left unchanged (relative wording)")
        return
    if rest:
        row["withdrawal_deadline"] = head
        row["withdrawal_conditions"] = rest
        notes.append("withdrawal_deadline: kept leading deadline; conditional clause moved to withdrawal_conditions")


def main() -> None:
    with SRC.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = list(reader.fieldnames or [])
    out_cols = cols + [c for c in NEW_COLUMNS if c not in cols]
    changed = {"settlement": 0, "withdrawal": 0}
    for row in rows:
        notes: list[str] = []
        before_s, before_w = row["settlement_date"], row["withdrawal_deadline"]
        clean_settlement(row, notes)
        clean_withdrawal(row, notes)
        changed["settlement"] += row["settlement_date"] != before_s
        changed["withdrawal"] += row["withdrawal_deadline"] != before_w
        row["gt_clean_notes"] = " ; ".join(notes)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows); changed {changed}")


if __name__ == "__main__":
    sys.exit(main())
