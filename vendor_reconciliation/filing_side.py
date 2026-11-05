"""Load the filing-extracted side: one current-state record per tender-offer event."""
import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "notebooks" / "evaluation" / "tender_offers.csv"

_PRICE_PURE = re.compile(r"^\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)\s*(per share|in cash|cash)?\s*$", re.I)
_PRICE_LEAD = re.compile(r"^\s*\$\s?([0-9][0-9,]*\.?[0-9]*)")
_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)


_SUFFIX = re.compile(r"\b(inc|corp|corporation|llc|ltd|company|co|the|lp|fund)\b")


def norm_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", s)).strip()


def parse_price(text: str) -> float | None:
    for pat in (_PRICE_PURE, _PRICE_LEAD):
        m = pat.match(text or "")
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def parse_expiry(text: str) -> tuple[date, time] | None:
    m = _DATE.match(text or "")
    if not m:
        return None
    d = date(int(m[3]), int(m[1]), int(m[2]))
    t = _TIME.search(text)
    if t:
        hour = int(t[1]) % 12 + (12 if t[3].upper() == "PM" else 0)
        return d, time(hour, int(t[2]))
    return d, time(23, 59)


def first_cusip(text: str) -> str | None:
    first = (text or "").split(";")[0].strip().upper()
    return first or None


@dataclass
class FilingEvent:
    event_id: str
    name: str
    cusip: str | None
    price: float | None
    expiry: date | None
    expiry_time: time
    prev_price: float | None
    prev_expiry: date | None
    announced: str
    accession: str
    filing_date: str
    form: str
    passage: str


def _last_two_distinct(values):
    """(latest value, most recent earlier value that differs) from a chronological list."""
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    latest = values[-1]
    earlier = [v for v in values[:-1] if v != latest]
    return latest, (earlier[-1] if earlier else None)


def load_events(path: Path = DEFAULT_PATH) -> list[FilingEvent]:
    """One record per real offer.

    The extraction dataset's event_id is accession-based, so filings of the same offer
    (e.g. a TO-T/A and a 14D-9/A filed the same day) carry different event_ids. Group them by
    issuer + CUSIP + announce date, then take the latest value of each field.
    """
    groups: dict[tuple, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        first_dates: dict[str, str] = {}
        rows_all = list(csv.DictReader(f))
    for row in rows_all:
        eid = row["event_id"]
        first_dates[eid] = min(first_dates.get(eid, row["filing_date"]), row["filing_date"])
    for row in rows_all:
        key = (norm_name(row["subject_company"]), first_cusip(row["cusip"]), first_dates[row["event_id"]])
        groups.setdefault(key, []).append(row)

    events = []
    for (_, cusip, announced), rows in groups.items():
        rows.sort(key=lambda r: (r["filing_date"], r["accession_number"]))
        cur = rows[-1]
        price, prev_price = _last_two_distinct([parse_price(r["offer_price"]) for r in rows])
        exps = [parse_expiry(r["expiration_date"]) for r in rows]
        expiry, prev_expiry = _last_two_distinct([x[0] if x else None for x in exps])
        times = [x[1] for x in exps if x]
        events.append(
            FilingEvent(
                event_id=cur["event_id"],
                name=cur["subject_company"].strip(),
                cusip=cusip,
                price=price,
                expiry=expiry,
                expiry_time=times[-1] if times else time(23, 59),
                prev_price=prev_price,
                prev_expiry=prev_expiry,
                announced=announced,
                accession=cur["accession_number"],
                filing_date=cur["filing_date"],
                form=cur["form"],
                passage=(cur.get("passage") or cur.get("passages") or "")[:300],
            )
        )
    return events
