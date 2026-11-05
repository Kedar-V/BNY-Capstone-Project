"""Vendor adapter: maps each vendor's field names and formats into one common record."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


@dataclass
class CommonRecord:
    vendor: str
    vendor_id: str
    name: str
    cusip: str | None
    price: float | None
    expiry: date | None
    announced: str | None


def _price_from_text(text: str | None) -> float | None:
    m = re.search(r"([0-9][0-9,]*\.?[0-9]*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _adapt_a(row: dict) -> CommonRecord:
    # Vendor A (CSV): OfferPx "42.5", ExpDate "12-Nov-2026"
    exp = row.get("ExpDate", "").strip()
    return CommonRecord(
        vendor="A",
        vendor_id=row["VendorId"],
        name=row["IssuerName"],
        cusip=row.get("CUSIP", "").strip().upper() or None,
        price=_price_from_text(row.get("OfferPx")),
        expiry=datetime.strptime(exp, "%d-%b-%Y").date() if exp else None,
        announced=row.get("AnnounceDate") or None,
    )


def _adapt_b(obj: dict) -> CommonRecord:
    # Vendor B (JSON lines): consideration "USD 42.50", expiry in UTC "2026-11-13T04:59:00Z"
    terms = obj.get("terms", {})
    expiry = terms.get("expiry")
    local = (
        datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone(ET).date() if expiry else None
    )
    return CommonRecord(
        vendor="B",
        vendor_id=obj["id"],
        name=obj["issuer_legal_name"],
        cusip=(obj.get("identifiers", {}).get("cusip") or "").upper() or None,
        price=_price_from_text(terms.get("consideration")),
        expiry=local,
        announced=obj.get("announced"),
    )


ADAPTERS = {"A": _adapt_a, "B": _adapt_b}


def adapt(vendor: str, raw: dict) -> CommonRecord:
    """One adapter layer; supporting a new vendor means adding its field mapping here."""
    return ADAPTERS[vendor](raw)
