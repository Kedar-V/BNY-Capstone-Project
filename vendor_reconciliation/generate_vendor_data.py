"""Generate synthetic vendor feeds from the filing-extracted tender-offer data.

Two vendors, two formats, with labeled injected errors (answer_key.csv) and benign
formatting differences that a good reconciliation must NOT flag.

    python vendor_reconciliation/generate_vendor_data.py --seed 7
"""
import argparse
import csv
import json
import random
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from filing_side import DEFAULT_PATH, FilingEvent, load_events

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    raise SystemExit("Python 3.9+ required")

ET = ZoneInfo("America/New_York")
OUT_DIR = Path(__file__).resolve().parent / "synthetic"

PRICE_TYPO_RATE = 0.05
PRICE_STALE_RATE = 0.05
EXPIRY_SHIFT_RATE = 0.05
EXPIRY_STALE_RATE = 0.05
CUSIP_TYPO_RATE = 0.02
MISSING_RATE = 0.02
COVERAGE = 0.7


def vary_name(name: str, rng: random.Random) -> str:
    """Benign differences vendors introduce; reconciliation should match through these."""
    choice = rng.random()
    if choice < 0.2:
        return name.upper()
    if choice < 0.4:
        return re.sub(r",?\s+(Inc\.?|Corporation|Corp\.?|LLC|Ltd\.?)$", "", name) or name
    if choice < 0.5:
        return name.replace("Corporation", "Corp.")
    return name


def fmt_price_a(p: float) -> str:
    return f"{p:g}"


def fmt_price_b(p: float) -> str:
    s = f"{p:.4f}".rstrip("0")
    if len(s.split(".")[1]) < 2:
        s = f"{p:.2f}"
    return f"USD {s}"


def expiry_utc(d, t: time) -> str:
    local = datetime.combine(d, t, tzinfo=ET)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def corrupt(e: FilingEvent, rng: random.Random):
    """Return the vendor's (possibly wrong) values plus the list of injected errors."""
    price, expiry, cusip = e.price, e.expiry, e.cusip
    injected = []

    if price is not None:
        r = rng.random()
        if r < PRICE_TYPO_RATE:
            price = round(price * rng.choice([1.05, 0.95, 1.1, 10]), 4)
            injected.append(("price", "price_wrong_value", e.price, price))
        elif r < PRICE_TYPO_RATE + PRICE_STALE_RATE:
            if e.prev_price and abs(e.prev_price - price) > 0.005:
                price = e.prev_price
                injected.append(("price", "price_stale_amendment", e.price, price))
        elif r < PRICE_TYPO_RATE + PRICE_STALE_RATE + MISSING_RATE:
            injected.append(("price", "price_missing", e.price, None))
            price = None

    if expiry is not None:
        r = rng.random()
        if r < EXPIRY_SHIFT_RATE:
            expiry = expiry + timedelta(days=rng.choice([-7, -3, -1, 1, 3, 7]))
            injected.append(("expiry", "expiry_wrong_date", e.expiry.isoformat(), expiry.isoformat()))
        elif r < EXPIRY_SHIFT_RATE + EXPIRY_STALE_RATE:
            if e.prev_expiry and e.prev_expiry != expiry:
                expiry = e.prev_expiry
                injected.append(("expiry", "expiry_stale_extension", e.expiry.isoformat(), expiry.isoformat()))
        elif r < EXPIRY_SHIFT_RATE + EXPIRY_STALE_RATE + MISSING_RATE:
            injected.append(("expiry", "expiry_missing", e.expiry.isoformat(), None))
            expiry = None

    if cusip and len(cusip) >= 4 and rng.random() < CUSIP_TYPO_RATE:
        i = rng.randrange(len(cusip) - 1)
        swapped = list(cusip)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        if "".join(swapped) != cusip:
            cusip = "".join(swapped)
            injected.append(("cusip", "cusip_transposed", e.cusip, cusip))

    return price, expiry, cusip, injected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    events = [e for e in load_events(args.source) if e.price is not None or e.expiry is not None]
    OUT_DIR.mkdir(exist_ok=True)

    rows_a, rows_b, key = [], [], []
    for vendor in ("A", "B"):
        covered = [e for e in events if rng.random() < COVERAGE]
        for n, e in enumerate(covered, 1):
            vid = f"{vendor}-{n:05d}"
            price, expiry, cusip, injected = corrupt(e, rng)
            name = vary_name(e.name, rng)
            for field, kind, truth, vendor_value in injected:
                key.append(
                    dict(vendor=vendor, vendor_id=vid, event_id=e.event_id, field=field,
                         error_type=kind, filing_value=truth, vendor_value=vendor_value)
                )
            if vendor == "A":
                rows_a.append(
                    dict(
                        VendorId=vid, IssuerName=name, CUSIP=cusip or "",
                        OfferPx=fmt_price_a(price) if price is not None else "",
                        ExpDate=expiry.strftime("%d-%b-%Y") if expiry else "",
                        AnnounceDate=e.announced,
                    )
                )
            else:
                rows_b.append(
                    {
                        "id": vid,
                        "issuer_legal_name": name,
                        "identifiers": {"cusip": cusip},
                        "terms": {
                            "consideration": fmt_price_b(price) if price is not None else None,
                            "expiry": expiry_utc(expiry, e.expiry_time) if expiry else None,
                        },
                        "announced": e.announced,
                    }
                )

    with open(OUT_DIR / "vendor_a.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_a[0].keys()))
        w.writeheader()
        w.writerows(rows_a)
    with open(OUT_DIR / "vendor_b.jsonl", "w", encoding="utf-8") as f:
        for r in rows_b:
            f.write(json.dumps(r) + "\n")
    with open(OUT_DIR / "answer_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0].keys()))
        w.writeheader()
        w.writerows(key)

    print(f"events with price or expiry: {len(events)}")
    print(f"vendor A: {len(rows_a)} records, vendor B: {len(rows_b)} records")
    print(f"injected errors: {len(key)}")
    kinds = {}
    for k in key:
        kinds[k["error_type"]] = kinds.get(k["error_type"], 0) + 1
    for kind, n in sorted(kinds.items()):
        print(f"  {kind}: {n}")
    print(f"written to {OUT_DIR}")


if __name__ == "__main__":
    main()
