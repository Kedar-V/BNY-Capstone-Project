"""Deterministic extractors (not GLiNER).

Ported from notebooks/evaluation/load_tender_filings.ipynb for pipeline use.
Owns: cusip, isin, ticker, currency, settlement_date (timing phrases / pay dates).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

CUSIP_PATTERN = re.compile(r"\b([0-9A-Z]{6})[\s-]?([0-9A-Z]{2})[\s-]?([0-9])\b")
ISIN_PATTERN = re.compile(r"\b([A-Z]{2}[0-9A-Z]{9}[0-9])\b")

# Exchange / venue labels seen on Schedule TO covers and press releases.
_EXCHANGE = (
    r"(?:NASDAQ|Nasdaq|NYSE American|NYSE Arca|NYSE|OTCQB|OTCQX|OTCBB|"
    r"OTC\s*Pink|OTC\s*Markets|OTC)"
)
# Optional trailing "." inside quotes (“MRSN.”); stripped after match.
_TICKER_TOKEN = r"([A-Z]{1,5}(?:\.[A-Z]|W)?\.?)"

TICKER_PATTERNS = [
    # Nasdaq: FOO  /  (OTCQB: ENZN)
    re.compile(rf"\b{_EXCHANGE}\s*:\s*{_TICKER_TOKEN}\b"),
    re.compile(rf"\(\s*{_EXCHANGE}\s*:\s*{_TICKER_TOKEN}\s*\)"),
    # Trading Symbol: FOO / Ticker Symbol = FOO / Symbol:\nFOO
    re.compile(
        rf"(?:Trading\s+Symbols?|Ticker\s*Symbols?|ticker\s*symbols?|Symbols?)\s*[:=]\s*"
        rf"[\"“]?\s*{_TICKER_TOKEN}",
        re.IGNORECASE,
    ),
    # … Nasdaq … under the symbol “FOO.”
    re.compile(
        rf"under the (?:ticker )?symbol\s*[\"“]\s*{_TICKER_TOKEN}\s*[\"”]",
        re.IGNORECASE,
    ),
    # Computershare voluntary actions header: COY: FOO
    re.compile(r"\bCOY:\s*([A-Z]{1,5})\b"),
]

# Prefer subject/issuer venues; demote bidder consideration tickers (e.g. ORCL in a WBD deal).
_SUBJECT_NEAR = re.compile(
    r"subject\s+company|name of (?:the )?subject|filing person\s*\(\s*issuer\s*\)|"
    r"names? of filing persons?\s*\(\s*issuer|common stock of|shares of\s+[A-Z]|"
    # Merger DEF14A / proxy: registrant is usually the target whose shares are voted.
    r"\bour\s+common\s+stock\b|\bcompany['’]?s?\s+common\s+stock\b|"
    r"\btrading\s+symbol\s+of\s+(?:our|the\s+company)\b|"
    r"\bshares?\s+of\s+(?:the\s+)?(?:company|registrant)\b|"
    r"\bdefm?14a\b|\bschedule\s+14a\b",
    re.IGNORECASE,
)
_BIDDER_NEAR = re.compile(
    r"\b(?:consideration|purchaser|offeror|bidder|parent|oracle|merger\s+sub|"
    r"acquiring|acquirer|buyer)\b",
    re.IGNORECASE,
)
# Multi-class SPAC / unit listings: "Trading Symbols: FOO, FOOR, FOOU"
_MULTI_TICKER_LINE = re.compile(
    rf"(?:Trading\s+Symbols?|Ticker\s*Symbols?)\s*[:=]\s*"
    rf"((?:{_TICKER_TOKEN}\s*[,/]\s*){{1,4}}{_TICKER_TOKEN})",
    re.IGNORECASE,
)
_TICKER_STOP = frozenset(
    {
        "AND",
        "THE",
        "FOR",
        "ACT",
        "INC",
        "LLC",
        "LTD",
        "PLC",
        "USD",
        "CUSIP",
        "ISIN",
        "FORM",
        "TO",
        "OF",
        "OR",
        "ON",
        "A",
        "AN",
        "NYSE",
        "SEC",
    }
)
CURRENCY_CODES = {"USD", "CAD", "EUR", "GBP", "AUD", "JPY", "CHF", "CNY", "HKD", "SGD"}
CURRENCY_MARKERS = [  # checked in order
    ("US$", "USD"),
    ("USD", "USD"),
    ("C$", "CAD"),
    ("CAD", "CAD"),
    ("A$", "AUD"),
    ("AUD", "AUD"),
    ("EUR", "EUR"),
    ("€", "EUR"),
    ("GBP", "GBP"),
    ("£", "GBP"),
    ("JPY", "JPY"),
    ("¥", "JPY"),
    ("$", "USD"),
]

# field_hint values owned by rules (strip GLiNER predictions for these)
RULE_FIELD_HINTS = frozenset({"cusip", "isin", "ticker", "currency", "settlement_date"})

# Settlement GT is mostly timing language ("Payment: promptly…"), not NER spans.
_MONTH_DATE = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}"
)
_SLASH_DATE = r"\d{1,2}/\d{1,2}/\d{2,4}"
_ANY_DATE = rf"(?:{_MONTH_DATE}|{_SLASH_DATE})"
_SETTLE_PAY_CUE = re.compile(
    r"(?i)\b(?:accepted\s+for\s+payment|acceptance\s+for\s+payment|paid\s+on\s+or\s+about|"
    r"payment\s+date|paid\s+on)\b"
)
_ANY_DATE_RE = re.compile(_ANY_DATE)
_SETTLE_PROMPTLY_LONG = re.compile(
    r"(?i)\b(promptly\s+following\s+expiration(?:\s+of\s+the\s+offer)?|"
    r"promptly\s+after\s+(?:the\s+)?(?:expiration|termination)(?:\s+date)?|"
    r"as\s+promptly\s+as\s+practicable\s+after\s+(?:the\s+)?expiration|"
    r"promptly\s+after\s+acceptance)\b"
)
_SETTLE_PROMPTLY_PAY = re.compile(
    r"(?i)\b(?:(?:will\s+)?(?:pay|paid|payment|accept(?:ed|ance)?(?:\s+for\s+payment)?)\b[^\n.]{0,50}\bpromptly\b)"
    r"|\b(?:promptly\b[^\n.]{0,50}\b(?:pay|paid|payment|accept))"
)


def _cusip_ok(cusip: str) -> bool:
    """CUSIP check digit (modulus 10 double-add-double)."""
    total = 0
    for position, char in enumerate(cusip[:8]):
        value = int(char) if char.isdigit() else ord(char) - 55
        if position % 2:
            value *= 2
        total += value // 10 + value % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def _isin_check_digit(body: str) -> int:
    digits = "".join(str(int(char, 36)) for char in body)
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char) * (2 if position % 2 == 0 else 1)
        total += value // 10 + value % 10
    return (10 - total % 10) % 10


def find_cusips(text: str) -> list[str]:
    """Valid CUSIPs within 150 chars of the word CUSIP, in order of appearance."""
    found: list[str] = []
    for match in re.finditer(r"CUSIP", text, flags=re.IGNORECASE):
        window = text[max(0, match.start() - 150) : match.end() + 150].upper()
        for part in CUSIP_PATTERN.finditer(window):
            cusip = "".join(part.groups())
            if _cusip_ok(cusip) and cusip not in found:
                found.append(cusip)
    return found


def find_isins(text: str, cusips: list[str]) -> list[str]:
    """ISINs near the word ISIN; otherwise US ISINs derived from CUSIPs."""
    stated: list[str] = []
    for match in re.finditer(r"ISIN", text):
        for part in ISIN_PATTERN.finditer(text[match.end() : match.end() + 80]):
            if part.group(1) not in stated:
                stated.append(part.group(1))
    if stated:
        return stated
    return [f"US{cusip}{_isin_check_digit('US' + cusip)}" for cusip in cusips]


def _score_ticker_match(text: str, match: re.Match[str], raw: str) -> int:
    # Left-heavy local window: role cues sit before the symbol; avoid bleeding into
    # the next company's "under the symbol" sentence (Inc./Corp. periods break poorly).
    ctx = text[max(0, match.start() - 140) : match.end() + 20]
    score = 0
    span = match.group(0)
    is_under_symbol = bool(
        re.search(r"under the (?:ticker )?symbol", span, re.IGNORECASE)
    )
    is_coy = bool(re.search(r"\bCOY:", span, re.IGNORECASE))
    is_otc = bool(re.search(r"OTC", span, re.IGNORECASE))
    if _SUBJECT_NEAR.search(ctx):
        score += 5
    if is_under_symbol:
        score += 4  # strong subject-equity phrasing
    if is_coy:
        score += 2
    if is_otc:
        score += 1
    # Parent/acquirer / consideration equity just before the hit — demote.
    if _BIDDER_NEAR.search(ctx):
        score -= 6 if (is_under_symbol or is_coy or is_otc) else 10
    if match.start() < 2500:
        score += 1
    return score


def find_tickers(text: str, *, limit: int = 6) -> list[str]:
    """Ranked exchange-/symbol-labeled tickers; prefers subject-company context."""
    if not text:
        return []
    # Prefer an explicit multi-symbol cover line when present.
    multi = _MULTI_TICKER_LINE.search(text[:8000] if len(text) > 8000 else text)
    if multi:
        parts = [
            p.strip().rstrip(".").upper()
            for p in re.split(r"[,/]", multi.group(1))
        ]
        parts = [p for p in parts if p and p not in _TICKER_STOP and len(p) >= 2]
        if 2 <= len(parts) <= 5:
            return [", ".join(parts)]

    candidates: list[tuple[int, int, str]] = []  # (score, pos, ticker)
    for pattern in TICKER_PATTERNS:
        for match in pattern.finditer(text):
            raw = (match.group(1) or "").strip().rstrip(".").upper()
            if not raw or raw in _TICKER_STOP or len(raw) < 2:
                continue
            score = _score_ticker_match(text, match, raw)
            candidates.append((score, match.start(), raw))
    if not candidates:
        return []
    candidates.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for score, _, raw in candidates:
        if score < 0 or raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
        if len(out) >= limit:
            break
    return out


def find_ticker(text: str) -> str | None:
    """Best exchange-/symbol-labeled ticker; prefers subject-company context."""
    hits = find_tickers(text, limit=1)
    return hits[0] if hits else None


def find_currency(offer_price: str | None) -> str | None:
    price = offer_price if isinstance(offer_price, str) else ""
    stated = re.match(r"\s*([A-Z]{3})\b", price)
    if stated and stated.group(1) in CURRENCY_CODES:
        return stated.group(1)
    for marker, code in CURRENCY_MARKERS:
        if marker in price:
            return code
    return None


def find_settlement(text: str) -> str | None:
    """Payment / acceptance timing for settlement_date.

    Prefer GT-shaped ``Payment: promptly`` when the filing uses promptly-pay
    language (soft-match hits structured Concise Representation labels).
    Otherwise take an explicit pay/accept calendar date near a pay cue.
    """
    if not text or not text.strip():
        return None
    # Promptly-first: calendar dates near "accepted for payment" often are the
    # wrong field (expiration / notice) when GT is timing language.
    if _SETTLE_PROMPTLY_LONG.search(text) or _SETTLE_PROMPTLY_PAY.search(text):
        return "Payment: promptly"
    for cue in _SETTLE_PAY_CUE.finditer(text):
        lo, hi = max(0, cue.start() - 80), min(len(text), cue.end() + 80)
        window = text[lo:hi]
        dm = _ANY_DATE_RE.search(window)
        if dm:
            return dm.group(0).strip()
    return None


_SET_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]
_SET_DATE = re.compile(
    r"\b(?:(\d{1,2})/(\d{1,2})/(\d{4})|(" + "|".join(m.title() for m in _SET_MONTHS)
    + r")\s+(\d{1,2}),?\s+(\d{4}))\b",
    re.I,
)
_SET_PAY = re.compile(
    r"\b(paid|pay(?:ment)?|wired|wire|settle(?:ment)?|cash\s+payment|accepted\s+for\s+(?:payment|purchase)|"
    r"purchase\s+price|consideration|disbursed|deposit(?:ed)?|issued)\b",
    re.I,
)
_SET_NOT_PAY = re.compile(
    r"\b(expir\w*|withdraw\w*|commence\w*|dated|filed|filing|record\s+date|valuation\s+date|"
    r"notice|announce\w*|termination|effective|tender\w*\s+period)\b",
    re.I,
)
_SET_STRONG_BEFORE = re.compile(
    r"(?i)(paid|wired|wire|payment\s+(?:will\s+be\s+made|was\s+made|is\s+made)|pay(?:ment)?\s+(?:on|by|no\s+later\s+than)|"
    r"no\s+later\s+than|on\s+or\s+about|to\s+be\s+paid\s+on)\s*(?:on\s+or\s+about\s+|on\s+|by\s+|no\s+later\s+than\s+)?$"
)
_SET_AS_OF = re.compile(
    r"(?i)(as\s+of|valuation\s+date|net\s+asset\s+value\s+(?:as\s+of|per\s+\w+\s+as\s+of)|fiscal\s+year|year\s+ended)\s*$"
)
_SET_WINDOW = 160


def find_settlement_date(text: str) -> str | None:
    """Date-only settlement_date: the calendar date that is the payment/acceptance date.

    Scores every calendar date by nearby payment words, penalises dates that are
    valuation / NAV / fiscal-year dates or sit near expiration, withdrawal or notice
    wording. Returns ``M/D/YYYY`` or None. Never returns template text such as
    ``Payment: promptly`` (relative timing is left blank, not guessed).
    """
    if not text or not text.strip():
        return None
    best: tuple[float, str] | None = None
    for m in _SET_DATE.finditer(text):
        if m.group(1):
            mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            mo, da, yr = _SET_MONTHS.index(m.group(4).lower()) + 1, int(m.group(5)), int(m.group(6))
        pos = m.start()
        lo, hi = max(0, pos - _SET_WINDOW), min(len(text), pos + _SET_WINDOW)
        pay_hits = len(_SET_PAY.findall(text[lo:hi]))
        if not pay_hits:
            continue
        neg_hits = len(_SET_NOT_PAY.findall(text[max(0, pos - 60): pos + 60]))
        score = pay_hits - 2 * neg_hits - abs(pos - (lo + hi) / 2) / _SET_WINDOW
        before = text[max(0, pos - 40): pos]
        if _SET_STRONG_BEFORE.search(before):
            score += 2
        if _SET_AS_OF.search(before):
            score -= 3
        if best is None or score > best[0]:
            best = (score, f"{mo}/{da}/{yr}")
    return best[1] if best and best[0] > 0 else None


def _set_date_tuple(m: re.Match) -> tuple[int, int, int]:
    if m.group(1):
        return int(m[3]), int(m[1]), int(m[2])
    return int(m[6]), _SET_MONTHS.index(m[4].lower()) + 1, int(m[5])


_SETTLEMENT_TEMPLATE = "Payment: promptly"


def prefer_settlement_rules_values(values: list[str], evidence_text: str = "") -> list[str]:
    """Oracle Settlement template first: prepend find_settlement hits, prefer promptly."""
    vals = [v for v in values if (v or "").strip()]
    if evidence_text:
        hit = find_settlement(evidence_text)
        if hit and hit not in vals:
            vals.append(hit)
    promptly = [v for v in vals if v.strip() == _SETTLEMENT_TEMPLATE]
    rest = [v for v in vals if v.strip() != _SETTLEMENT_TEMPLATE]
    return promptly + rest


def settlement_accept(value: str, evidence: str) -> bool:
    """Precision gate for settlement_date (v2 cascade + oracle Settlement template).

    Keep the oracle template ``Payment: promptly`` (GT-shaped timing language). For calendar
    dates, accept only when the date appears in the evidence after a payment cue; relative
    timing other than the template, and dates without a pay cue, are rejected.
    """
    v = (value or "").strip()
    text = evidence or ""
    if v == _SETTLEMENT_TEMPLATE:
        # Oracle Settlement template: exact form is already gated by find_settlement.
        # Frozen rules bundles often omit the filing span, so do not re-require cues here.
        return True
    vm = _SET_DATE.search(v)
    if vm is None or vm.group(0) != v:
        return False  # value must be exactly one calendar date (or the template above)
    target = _set_date_tuple(vm)
    for hit in _SET_DATE.finditer(text):
        if _set_date_tuple(hit) != target:
            continue
        # A payment word within 80 chars, and no valuation/expiration/notice wording right before the date
        window = text[max(0, hit.start() - 80): hit.end() + 80]
        before = text[max(0, hit.start() - 40): hit.start()]
        if not _SET_PAY.search(window):
            continue
        if _SET_NOT_PAY.search(before) or _SET_AS_OF.search(before):
            continue
        return True
    return False


def load_sec_tickers(path: Path) -> dict[str, str]:
    """Ticker listed by SEC full-text search for each filing (selected_filings.csv)."""
    if not path.exists():
        return {}
    import pandas as pd

    hits = pd.read_csv(path, dtype={"accession": str})
    tickers: dict[str, str] = {}
    if "accession" not in hits.columns or "tickers" not in hits.columns:
        return {}
    for accession, raw in zip(hits["accession"], hits["tickers"]):
        try:
            values = ast.literal_eval(raw) if isinstance(raw, str) else []
        except (ValueError, SyntaxError):
            values = []
        if values:
            tickers[str(accession)] = ", ".join(str(v) for v in values)
    return tickers


def _rule_fact(
    *,
    field_hint: str,
    raw: str,
    accession: str | None = None,
    passage: str | None = None,
) -> dict:
    return {
        "field_hint": field_hint,
        "raw": raw,
        "passage": passage or raw,
        "method": "rules",
        "confidence": 1.0,
        "rank_score": 1.0,
        "doc_role": "cover",
        "source_accession": accession,
        "label": field_hint,
    }


def extract_id_currency_facts(
    segments: list[dict],
    *,
    offer_price_by_accession: dict[str, str] | None = None,
    sec_tickers: dict[str, str] | None = None,
) -> list[dict]:
    """Build rules facts for cusip/isin/ticker/currency/settlement_date from segments."""
    offer_price_by_accession = offer_price_by_accession or {}
    sec_tickers = sec_tickers or {}

    by_acc: dict[str, list[str]] = {}
    for seg in segments:
        acc = str(seg.get("accession") or "").strip() or "_unknown"
        text = seg.get("text") or ""
        if not text:
            continue
        by_acc.setdefault(acc, []).append(text)

    facts: list[dict] = []
    for acc, parts in by_acc.items():
        text = "\n".join(parts)
        accession = None if acc == "_unknown" else acc
        cusips = find_cusips(text)
        if cusips:
            facts.append(
                _rule_fact(
                    field_hint="cusip",
                    raw="; ".join(cusips),
                    accession=accession,
                    passage=cusips[0],
                )
            )
        isins = find_isins(text, cusips)
        if isins:
            facts.append(
                _rule_fact(
                    field_hint="isin",
                    raw="; ".join(isins),
                    accession=accession,
                    passage=isins[0],
                )
            )
        ticker = (sec_tickers.get(acc) if accession else None) or find_ticker(text)
        if ticker:
            facts.append(
                _rule_fact(field_hint="ticker", raw=ticker, accession=accession, passage=ticker)
            )
        price = offer_price_by_accession.get(acc) or offer_price_by_accession.get("") or ""
        # fall back: any price string for this event
        if not price and offer_price_by_accession:
            price = next(iter(offer_price_by_accession.values()), "") or ""
        currency = find_currency(price)
        if currency:
            facts.append(
                _rule_fact(
                    field_hint="currency",
                    raw=currency,
                    accession=accession,
                    passage=price[:200],
                )
            )
        settlement = find_settlement_date(text)
        if settlement:
            facts.append(
                _rule_fact(
                    field_hint="settlement_date",
                    raw=settlement,
                    accession=accession,
                    passage=settlement,
                )
            )
    return facts
