"""Where an issuer is incorporated, from the SEC company record, and whether an ISIN can be derived from a CUSIP.

A CUSIP that starts with a digit is a North American CUSIP; its ISIN is "US" + CUSIP + check digit, or "CA"
for a Canadian issuer. This holds for foreign issuers too: US-traded shares or notes of a Cayman company carry
a "US" ISIN. A CUSIP that starts with a letter is a CINS; its ISIN comes from the home country's own scheme, so
it cannot be derived and is left unset unless the filing states it.
"""
import json
from pathlib import Path

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}
# SEC codes for Canadian provinces and territories
CANADA = {"A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "B0", "Z4"}

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FOREIGN_ISSUER_FORMS = {"20-F", "40-F", "6-K"}


def issuer_location(cik, client, cache_path=None):
    """Incorporation and filer-status facts for one CIK. Returns None if the SEC record cannot be read.

    `client` is an eda.sec_client.SecClient. With `cache_path`, each CIK is fetched once and kept in a
    small JSON file, so reruns do not call SEC again.
    """
    if cik is None or str(cik).strip() in ("", "nan"):
        return None
    key = str(int(str(cik)))
    cache = {}
    if cache_path and Path(cache_path).exists():
        cache = json.loads(Path(cache_path).read_text())
    if key in cache:
        return cache[key]

    try:
        record = client.get_json(SUBMISSIONS_URL.format(cik=int(key)))
    except Exception:
        return None
    code = (record.get("stateOfIncorporation") or "").upper() or None
    business = (record.get("addresses") or {}).get("business") or {}
    forms = set((record.get("filings") or {}).get("recent", {}).get("form", []))
    if code in US_STATES:
        country = "United States"
    elif code in CANADA:
        country = "Canada"
    else:
        country = record.get("stateOfIncorporationDescription") or None
    location = {
        "inc_code": code,
        "inc_country": country,
        "is_us_incorporated": code in US_STATES,
        "is_canada_incorporated": code in CANADA,
        "foreign_address": business.get("isForeignLocation") == 1,
        "foreign_private_issuer": bool(forms & FOREIGN_ISSUER_FORMS),
    }
    if cache_path:
        cache[key] = location
        Path(cache_path).write_text(json.dumps(cache, indent=0))
    return location


def isin_prefix(cusip, location):
    """'US' or 'CA' when an ISIN may be derived from this CUSIP; None for a CINS (first character a letter)."""
    if not cusip or not cusip[0].isdigit():
        return None
    if location and location.get("is_canada_incorporated"):
        return "CA"
    return "US"
