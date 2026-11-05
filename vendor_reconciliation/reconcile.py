"""Compare vendor feeds against filing-extracted terms and flag mismatches for human review.

    python vendor_reconciliation/reconcile.py
"""
import argparse
import csv
import difflib
import json
from collections import Counter, defaultdict
from pathlib import Path

from adapters import CommonRecord, adapt
from filing_side import DEFAULT_PATH, FilingEvent, load_events, norm_name

SYN_DIR = Path(__file__).resolve().parent / "synthetic"
PRICE_TOLERANCE = 0.005
SEVERITY = {"price": "high", "expiry": "high", "cusip": "high"}


def load_vendor_records() -> list[CommonRecord]:
    records = []
    with open(SYN_DIR / "vendor_a.csv", newline="", encoding="utf-8") as f:
        records += [adapt("A", row) for row in csv.DictReader(f)]
    with open(SYN_DIR / "vendor_b.jsonl", encoding="utf-8") as f:
        records += [adapt("B", json.loads(line)) for line in f if line.strip()]
    return records


def match(rec: CommonRecord, events: list[FilingEvent], by_name: dict[str, list[FilingEvent]]):
    """Return (event, how) or (None, reason)."""
    key = norm_name(rec.name)
    cands = by_name.get(key)
    if not cands:
        close = difflib.get_close_matches(key, list(by_name), n=1, cutoff=0.9)
        cands = by_name[close[0]] if close else []
    if not cands:
        return None, "no_name_match"
    if len(cands) == 1:
        return cands[0], "name"
    by_date = [e for e in cands if e.announced == rec.announced]
    if len(by_date) == 1:
        return by_date[0], "name+announce_date"
    if rec.cusip:
        by_cusip = [e for e in (by_date or cands) if e.cusip == rec.cusip]
        if len(by_cusip) == 1:
            return by_cusip[0], "name+cusip"
    return None, "ambiguous"


def compare(rec: CommonRecord, e: FilingEvent) -> list[dict]:
    found = []

    def flag(field, filing_value, vendor_value, kind="value_mismatch"):
        found.append(
            dict(
                vendor=rec.vendor, vendor_id=rec.vendor_id, event_id=e.event_id, field=field,
                kind=kind, severity=SEVERITY[field] if kind == "value_mismatch" else "medium",
                filing_value=filing_value, vendor_value=vendor_value,
                evidence_accession=e.accession, evidence_form=e.form,
                evidence_filing_date=e.filing_date, evidence_passage=e.passage.replace("\n", " "),
            )
        )

    if e.price is not None:
        if rec.price is None:
            flag("price", e.price, None, "missing_in_vendor")
        elif abs(rec.price - e.price) > PRICE_TOLERANCE:
            flag("price", e.price, rec.price)
    if e.expiry is not None:
        if rec.expiry is None:
            flag("expiry", e.expiry.isoformat(), None, "missing_in_vendor")
        elif rec.expiry != e.expiry:
            flag("expiry", e.expiry.isoformat(), rec.expiry.isoformat())
    if e.cusip and rec.cusip and e.cusip != rec.cusip:
        flag("cusip", e.cusip, rec.cusip)
    return found


def score(flags: list[dict]) -> dict:
    with open(SYN_DIR / "answer_key.csv", newline="", encoding="utf-8") as f:
        key = list(csv.DictReader(f))
    truth = {(k["vendor"], k["vendor_id"], k["field"]): k["error_type"] for k in key}
    flagged = {(x["vendor"], x["vendor_id"], x["field"]) for x in flags}
    tp = flagged & truth.keys()
    fp = flagged - truth.keys()
    fn = truth.keys() - flagged
    by_type = defaultdict(lambda: [0, 0])
    for k, t in truth.items():
        by_type[t][1] += 1
        by_type[t][0] += k in flagged
    return {
        "injected_errors": len(truth),
        "flagged": len(flagged),
        "true_positives": len(tp),
        "false_positives": len(fp),
        "missed": len(fn),
        "precision": round(len(tp) / len(flagged), 3) if flagged else None,
        "recall": round(len(tp) / len(truth), 3) if truth else None,
        "recall_by_error_type": {t: f"{a}/{b}" for t, (a, b) in sorted(by_type.items())},
        "false_positive_examples": sorted(fp)[:10],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_PATH)
    args = ap.parse_args()

    events = load_events(args.source)
    by_name: dict[str, list[FilingEvent]] = defaultdict(list)
    for e in events:
        by_name[norm_name(e.name)].append(e)

    records = load_vendor_records()
    flags, unmatched, matched = [], Counter(), 0
    for rec in records:
        e, how = match(rec, events, by_name)
        if e is None:
            unmatched[how] += 1
            continue
        matched += 1
        flags += compare(rec, e)

    out = SYN_DIR / "mismatches.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flags[0].keys()))
        w.writeheader()
        w.writerows(flags)

    summary = score(flags)
    summary.update(vendor_records=len(records), matched=matched, unmatched=dict(unmatched))
    (SYN_DIR / "evaluation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    print(f"mismatch tickets written to {out}")


if __name__ == "__main__":
    main()
