"""Shared event store: one event per corporate action, built from the team's extraction runs and readable as of any date.

Copied from agents/client_briefing/event_store.py so other agents can reuse it. Inputs are the LLM extraction
outputs: the rights run (rights_issues_v2.csv), the merger run (mergers.csv) and the tender run behind the demo
(tender_offers.csv). A filing only counts once it has been filed, so a view dated in the past cannot use later facts.

Changes from the briefing copy: the rule for merging a later filing's value into the earlier one is a public function
(merge_value), so versioning.py replays filings with exactly the same rule, and tender offers keep
conditions_restrictions.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd

from . import config, parsers


def _clean(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return None if not s or s.lower() in {"nan", "none", "null"} else s


def _literal(v: Any) -> Any:
    """Passages and ticker lists are stored as JSON in one run and as Python literals in the other."""
    if not isinstance(v, str) or not v.strip():
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(v)
        except Exception:  # noqa: BLE001
            continue
    return None


def _passages(raw: Any) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for key, items in (_literal(raw) or {}).items():
        quotes = [{"quote": _clean(it.get("quote")), "location": _clean(it.get("location")) or ""}
                  for it in sorted(items or [], key=lambda x: -(x.get("relevance_score") or 0)) if _clean(it.get("quote"))]
        if quotes:
            out[key] = quotes
    return out


def norm_name(name: str | None) -> str:
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(inc|incorporated|corp|corporation|llc|ltd|limited|co|company|holdings|holding|plc|lp|the|group|trust|fund)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _same_party(a: str | None, b: str | None) -> bool:
    x, y = norm_name(a), norm_name(b)
    if not x or not y:
        return False
    return x == y or x in y or y in x


@dataclass
class Filing:
    accession: str
    action: str
    form: str
    filed: date
    registrant: str
    cik: str
    tickers: list[str]
    file_nums: list[str]
    url: str
    fields: dict[str, str]
    passages: dict[str, list[dict]]


@dataclass
class Fact:
    """A value the brief relies on, with the filing and passage that support it."""

    key: str
    value: Any
    raw: str
    quote: str | None
    location: str | None
    accession: str
    form: str
    filed: date
    url: str


@dataclass
class Change:
    key: str
    previous: Any
    current: Any
    accession: str
    form: str
    filed: date


@dataclass
class EventState:
    """What was known about an event on one date."""

    event: "Event"
    as_of: date
    filings: list[Filing]
    status: str | None
    facts: dict[str, Fact]
    text: dict[str, str]
    changes: list[Change]

    @property
    def latest(self) -> Filing:
        return self.filings[-1]

    @property
    def first_filed(self) -> date:
        return self.filings[0].filed


# Parsed fields per action: key -> (source field, parser)
_RIGHTS_PARSED: dict[str, tuple[str, Callable]] = {
    "record_date": ("record_date", parsers.parse_date),
    "expiration_date": ("expiration_date", parsers.parse_date),
    "election_deadline": ("election_deadline", parsers.parse_date),
    "effective_date": ("effective_date", parsers.parse_effective_date),
    "ratio": ("subscription_ratio", parsers.parse_ratio),
    "price": ("subscription_price", parsers.parse_price),
    "oversubscription": ("oversubscription_rights", parsers.parse_bool_yes_no),
    "transferable": ("rights_transferable", parsers.parse_bool_yes_no),
    "security_class": ("security_description", parsers.security_class),
}
_MERGER_PARSED: dict[str, tuple[str, Callable]] = {
    "vote_date": ("shareholder_vote_date", parsers.parse_date),
    "election_deadline": ("election_deadline", parsers.parse_date),
    "effective_date": ("effective_date", parsers.parse_effective_date),
    "cash_per_share": ("cash_consideration", parsers.parse_cash_per_share),
    "exchange_ratio": ("stock_exchange_ratio", parsers.parse_exchange_ratio),
}
_TENDER_PARSED: dict[str, tuple[str, Callable]] = {
    "expiration_date": ("expiration_date", parsers.parse_date),
    "withdrawal_deadline": ("withdrawal_deadline", parsers.parse_date),
    "offer_price": ("offer_price", parsers.parse_tender_price),
}
_PARSED = {"rights_issue": _RIGHTS_PARSED, "merger": _MERGER_PARSED, "tender_offer": _TENDER_PARSED}
_STATUS = {"rights_issue": parsers.parse_rights_status, "merger": parsers.parse_merger_status, "tender_offer": parsers.parse_tender_status}
# Changes to these are worth telling a client about
_MATERIAL = {
    "rights_issue": ["expiration_date", "record_date", "election_deadline", "ratio", "price"],
    "merger": ["vote_date", "election_deadline", "cash_per_share", "exchange_ratio"],
    "tender_offer": ["expiration_date", "offer_price"],
}


# Public names for other agents
PARSED, STATUS, MATERIAL = _PARSED, _STATUS, _MATERIAL


def _offer_has_number(price: dict) -> bool:
    return price.get("amount") is not None or price.get("low") is not None


_SKIP = object()


def merge_value(key: str, prev: Any, value: Any) -> Any:
    """What a later filing's parsed value means for a field that already has `prev`.

    Returns the merged value, or _SKIP when the later value must not replace the earlier one.
    """
    if key == "ratio" and prev:  # a filing may state only one side of the ratio; keep the other
        return {k: value[k] if value[k] is not None else prev[k] for k in prev}
    if key == "price" and prev and value.get("amount") is None and prev.get("amount") is not None:
        return _SKIP  # a later "formula only" mention does not erase a stated price or estimate
    if key == "offer_price" and prev:
        if _offer_has_number(prev) and not _offer_has_number(value):
            return _SKIP  # same rule for a tender offer
        if prev.get("amount") is not None and prev.get("amount") == value.get("amount"):
            return prev  # "$25.00" and "$25.00 in cash plus a right" in two filings are the same offer
    return value


@dataclass
class Event:
    id: str
    action: str
    title: str
    issuer: str
    counterparty: str | None
    filings: list[Filing]
    # ticker -> role of that security in the deal: "issuer" for rights, "target"/"acquirer"/"party" for mergers
    ticker_roles: dict[str, str] = field(default_factory=dict)

    def tickers(self) -> set[str]:
        return set(self.ticker_roles)

    def as_of(self, day: date, lookback_days: int = 7) -> EventState | None:
        seen = [f for f in self.filings if f.filed <= day]
        if not seen:
            return None
        parsed_fields = _PARSED[self.action]
        facts: dict[str, Fact] = {}
        history: dict[str, list[tuple[Any, Filing]]] = {}
        for key, (source, parse) in parsed_fields.items():
            for f in seen:  # oldest first, so a later filing replaces an earlier value
                value = parse(f.fields.get(source))
                if value is None:
                    continue
                history.setdefault(key, [])
                prev = history[key][-1][0] if history[key] else None
                value = merge_value(key, prev, value)
                if value is _SKIP:
                    continue
                if prev != value:
                    history[key].append((value, f))
                quotes = f.passages.get(source) or []
                facts[key] = Fact(key, value, f.fields[source], quotes[0]["quote"] if quotes else None,
                                  quotes[0]["location"] if quotes else None, f.accession, f.form, f.filed, f.url)

        changes: list[Change] = []
        for key in _MATERIAL[self.action]:
            versions = history.get(key, [])
            for (prev, _), (cur, f) in zip(versions, versions[1:]):
                if (day - f.filed).days < lookback_days:
                    changes.append(Change(key, prev, cur, f.accession, f.form, f.filed))

        text: dict[str, str] = {}
        for f in seen:
            text.update(f.fields)
        parse_status = _STATUS[self.action]
        status = next((s for f in reversed(seen) if (s := parse_status(f.fields.get("event_status")))), None)
        return EventState(self, day, seen, status, facts, text, changes)


# ---------------------------------------------------------------- loading

def _filing_dates(v: str) -> date:
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _selected_lookup(path) -> dict[str, dict]:
    """Tickers and SEC file numbers come from the EDGAR search results saved by the team loader."""
    df = pd.read_csv(path, low_memory=False)
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        cur = out.setdefault(r["accession"], {"tickers": [], "file_nums": []})
        for t in _literal(r.get("tickers")) or []:
            if t not in cur["tickers"]:
                cur["tickers"].append(t)
        for n in _literal(r.get("file_nums")) or []:
            if n not in cur["file_nums"]:
                cur["file_nums"].append(n)
    return out


def load_rights_events() -> list[Event]:
    df = pd.read_csv(config.RIGHTS_CSV, low_memory=False)
    lookup = _selected_lookup(config.RIGHTS_SELECTED)
    keep = ["record_date", "subscription_ratio", "subscription_price", "expiration_date", "oversubscription_rights",
            "rights_transferable", "event_status", "security_description", "effective_date", "available_options",
            "default_option", "election_deadline"]
    by_issuer: dict[str, list[Filing]] = {}
    for _, r in df.iterrows():
        acc = r["accession_number"]
        extra = lookup.get(acc, {"tickers": [], "file_nums": []})
        by_issuer.setdefault(str(r["registrant_cik"]), []).append(Filing(
            acc, "rights_issue", r["form"], _filing_dates(r["filing_date"]), _clean(r["registrant_name"]) or "",
            str(r["registrant_cik"]), extra["tickers"], extra["file_nums"], r["filing_index_url"],
            {k: v for k in keep if (v := _clean(r.get(k)))}, _passages(r.get("passages"))))

    events: list[Event] = []
    for cik, filings in by_issuer.items():
        filings.sort(key=lambda f: (f.filed, f.accession))
        groups: list[list[Filing]] = [[filings[0]]]
        for f in filings[1:]:
            if (f.filed - groups[-1][-1].filed).days > config.RIGHTS_EVENT_GAP_DAYS:
                groups.append([f])
            else:
                groups[-1].append(f)
        for i, group in enumerate(groups):
            issuer = group[0].registrant
            roles = {t: "issuer" for f in group for t in f.tickers}
            events.append(Event(f"rights-{cik}-{i}", "rights_issue", f"{_pretty(issuer)} rights offering", _pretty(issuer), None, group, roles))
    return events


def _pretty(name: str) -> str:
    """'BLACKROCK MUNIASSETS FUND, INC.' reads better in a client brief as 'BlackRock MuniAssets Fund, Inc.'"""
    if name != name.upper():
        return name
    small = {"of", "and", "the"}
    keep = {"INC.": "Inc.", "INC": "Inc.", "LLC": "LLC", "LTD": "Ltd.", "LTD.": "Ltd.", "CORP": "Corp.", "CORP.": "Corp.",
            "BLACKROCK": "BlackRock", "MUNIASSETS": "MuniAssets", "RIVERNORTH": "RiverNorth", "TCW": "TCW", "LGL": "LGL",
            "PBT": "PBT"}
    words = []
    for w in name.split():
        bare = w.rstrip(",")
        words.append(keep.get(bare, bare.lower() if bare.lower() in small else bare.capitalize()) + ("," if w.endswith(",") else ""))
    return " ".join(words)


_COMMON = re.compile(r"\b(common|ordinary|class a)\b", re.I)
_NOT_COMMON = re.compile(r"\b(preferred|warrants?|rights?|units?|options?|awards?|notes?|debentures?)\b", re.I)


def _primary_merger_row(rows: pd.DataFrame) -> pd.Series:
    """One filing can list several instruments. Holders of common stock are the case the brief calculates."""
    def score(r: pd.Series) -> int:
        sec = _clean(r.get("security_description")) or ""
        s = 0
        if _COMMON.search(sec):
            s += 3
        if _NOT_COMMON.search(sec.split(",")[0]):
            s -= 2
        if parsers.parse_cash_per_share(_clean(r.get("cash_consideration"))) is not None:
            s += 1
        if parsers.parse_exchange_ratio(_clean(r.get("stock_exchange_ratio"))) is not None:
            s += 1
        return s
    best = max(range(len(rows)), key=lambda i: score(rows.iloc[i]))
    return rows.iloc[best]


def load_merger_events() -> list[Event]:
    df = pd.read_csv(config.MERGER_CSV, low_memory=False)
    lookup = _selected_lookup(config.MERGER_SELECTED)
    keep = ["acquirer", "target", "consideration_type", "cash_consideration", "stock_exchange_ratio", "shareholder_vote_date",
            "closing_conditions", "event_status", "mandatory_voluntary_indicator", "security_description", "effective_date",
            "available_options", "default_option", "election_deadline"]
    filings: list[Filing] = []
    for acc, rows in df.groupby("accession_number", sort=False):
        r = _primary_merger_row(rows)
        extra = lookup.get(acc, {"tickers": [], "file_nums": []})
        tickers = list(extra["tickers"])
        for t in re.split(r"[,;]\s*", _clean(r.get("ticker")) or ""):
            if t and t not in tickers:
                tickers.append(t)
        filings.append(Filing(acc, "merger", r["form"], _filing_dates(r["filing_date"]), _clean(r["registrant_name"]) or "",
                              str(r["registrant_cik"]), tickers, extra["file_nums"], r["filing_index_url"],
                              {k: v for k in keep if (v := _clean(r.get(k)))}, _passages(r.get("passages"))))
    filings.sort(key=lambda f: (f.filed, f.accession))

    # Same deal = same deal-specific SEC file number (333-, 005-), or the same acquirer and target as extracted.
    parent = {f.accession: f.accession for f in filings}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen_key: dict[str, str] = {}
    for f in filings:
        keys = [n for n in f.file_nums if n[:3] in {"333", "005"}]
        tgt, acq = norm_name(f.fields.get("target")), norm_name(f.fields.get("acquirer"))
        if tgt and acq:
            keys.append(f"pair:{tgt}|{acq}")
        # Acquirer names vary between filings ("StablecoinX Inc., through its subsidiary ..."): the target's own
        # filings under its own ticker are still the same deal.
        if tgt and _same_party(f.registrant, f.fields.get("target")):
            keys += [f"target:{tgt}|{t}" for t in f.tickers]
        for k in keys:
            if k in seen_key:
                parent[find(f.accession)] = find(seen_key[k])
            else:
                seen_key[k] = f.accession

    groups: dict[str, list[Filing]] = {}
    for f in filings:
        groups.setdefault(find(f.accession), []).append(f)

    events: list[Event] = []
    for anchor, group in groups.items():
        target = next((f.fields["target"] for f in reversed(group) if f.fields.get("target")), group[0].registrant)
        acquirer = next((f.fields["acquirer"] for f in reversed(group) if f.fields.get("acquirer")), None)
        roles: dict[str, str] = {}
        for f in group:
            role = "target" if _same_party(f.registrant, target) else "acquirer" if _same_party(f.registrant, acquirer) else "party"
            for t in f.tickers:
                if roles.get(t) in {None, "party"}:
                    roles[t] = role
        title = f"{_short(acquirer)} / {_short(target)} merger" if acquirer else f"{_short(target)} merger"
        events.append(Event(f"merger-{anchor}", "merger", title, clean_party(target), clean_party(acquirer) or None, group, roles))
    return events


def clean_party(name: str | None) -> str:
    """The extraction often describes the party: 'Fertitta Gaming Holdco, LLC, the acquiring parent; its subsidiary ...'"""
    s = re.split(r"\s*(?:;|\(|,\s+(?:the|an?|through|its|which|acting|together)\b|\s+through\s+|\s+acting\s+|\s+an indirect\b|\s+a wholly\b)", name or "")[0]
    bare = s.strip().rstrip(",.")
    return _pretty(bare) + ("." if re.search(r"\b(?:Inc|Corp|Ltd|Co|L\.P|S\.p\.A|S\.A|N\.V|P\.L\.C)$", bare) else "")


def _short(name: str | None, limit: int = 40) -> str:
    s = clean_party(name)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


_NEW_OFFER_FORMS = {"SC TO-I", "SC TO-T"}
_STATUS_RANK = {"terminated": 2, "completed": 1}


def _primary_tender_row(rows: pd.DataFrame) -> pd.Series:
    """One filing can list several securities. Shares are what a custody position holds, so they come first."""
    def score(r: pd.Series) -> int:
        s = 3 if parsers.tender_security(_clean(r.get("security_description"))) == "shares" else 0
        price = parsers.parse_tender_price(_clean(r.get("offer_price")))
        s += 1 if price and _offer_has_number(price) else 0
        s += 1 if parsers.parse_date(_clean(r.get("expiration_date"))) else 0
        return s
    best = max(range(len(rows)), key=lambda i: score(rows.iloc[i]))
    return rows.iloc[best]


def load_tender_events() -> list[Event]:
    df = pd.read_csv(config.TENDER_CSV, dtype=str)
    file_numbers: dict[str, str] = json.loads(config.TENDER_FILE_NUMBERS.read_text(encoding="utf-8"))
    keep = ["subject_company", "bidder", "parent", "security_description", "event_status", "offer_price", "offer_price_basis",
            "offer_price_qualifications", "expiration_date", "withdrawal_deadline", "settlement_date", "minimum_tender_condition",
            "proration_terms", "tendering_conditions", "available_options", "default_option", "conditions_restrictions"]
    by_number: dict[str, list[Filing]] = {}
    for acc, rows in df.groupby("accession_number", sort=False):
        r = _primary_tender_row(rows)
        # The first ticker listed is the main security: "ZCAR, ZCARW" is the stock and then its warrants
        ticker = re.split(r"[,;]\s*", _clean(r.get("ticker")) or "")[0]
        number = file_numbers.get(acc)
        by_number.setdefault(number or acc, []).append(Filing(
            acc, "tender_offer", r["form"], _filing_dates(r["filing_date"]), _clean(r["registrant_name"]) or "", str(r["registrant_cik"]),
            [ticker] if ticker else [], [number] if number else [], r["filing_index_url"],
            {k: v for k in keep if (v := _clean(r.get(k)))}, _passages(r.get("passage"))))

    events: list[Event] = []
    for number, filings in by_number.items():
        # Same-day filings can disagree on status: the most final one must be read last
        filings.sort(key=lambda f: (f.filed, _STATUS_RANK.get(parsers.parse_tender_status(f.fields.get("event_status")) or "", 0), f.accession))
        groups: list[list[Filing]] = [[filings[0]]]
        for f in filings[1:]:
            expiries = [d for x in groups[-1] if (d := parsers.parse_date(x.fields.get("expiration_date")))]
            # A new Schedule TO after the last offer expired is a new offer under the same file number
            if f.form in _NEW_OFFER_FORMS and expiries and expiries[-1] < f.filed:
                groups.append([f])
            else:
                groups[-1].append(f)
        for i, group in enumerate(groups):
            subject = next((f.fields["subject_company"] for f in reversed(group) if f.fields.get("subject_company")), group[0].registrant)
            bidder = next((f.fields.get("parent") or f.fields.get("bidder") for f in reversed(group) if f.fields.get("parent") or f.fields.get("bidder")), None)
            if any(f.form.startswith("SC TO-I") for f in group) or _same_party(subject, bidder):
                bidder = None  # the company is buying back its own securities
            # An offer for notes, preferred stock or options does not touch a holder of the common stock
            covers_shares = any(parsers.tender_security(f.fields.get("security_description")) == "shares" for f in group)
            roles = {t: "target" for f in group for t in f.tickers} if covers_shares else {}
            title = f"{_short(bidder)} / {_short(subject)} tender offer" if bidder else f"{_short(subject)} tender offer"
            events.append(Event(f"tender-{number}-{i}", "tender_offer", title, clean_party(subject), clean_party(bidder) or None, group, roles))
    return events


_LOADERS = {"rights_issue": load_rights_events, "merger": load_merger_events, "tender_offer": load_tender_events}


def load_events(actions: tuple[str, ...] = config.ACTIONS) -> list[Event]:
    return [e for action in actions for e in _LOADERS[action]()]
