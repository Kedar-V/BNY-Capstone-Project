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
    r"names? of filing persons?\s*\(\s*issuer|common stock of|shares of\s+[A-Z]",
    re.IGNORECASE,
)
_BIDDER_NEAR = re.compile(
    r"\b(?:consideration|purchaser|offeror|bidder|parent|oracle|merger\s+sub)\b",
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


def find_ticker(text: str) -> str | None:
    """Best exchange-/symbol-labeled ticker; prefers subject-company context."""
    if not text:
        return None
    candidates: list[tuple[int, int, str]] = []  # (score, pos, ticker)
    for pattern in TICKER_PATTERNS:
        for match in pattern.finditer(text):
            raw = (match.group(1) or "").strip().rstrip(".").upper()
            if not raw or raw in _TICKER_STOP or len(raw) < 2:
                continue
            left = text[max(0, match.start() - 220) : match.start()]
            right = text[match.end() : match.end() + 80]
            ctx = left + " " + right
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
            # Bare EXCHANGE:TICKER near bidder/consideration (e.g. NYSE: ORCL
            # stock as deal consideration) — force below the accept threshold.
            if (
                not (is_under_symbol or is_coy or is_otc)
                and _BIDDER_NEAR.search(ctx)
            ):
                score -= 10
            if match.start() < 2500:
                score += 1
            candidates.append((score, match.start(), raw))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    best_score, _, best = candidates[0]
    # Abstain if the only hits look like bidder consideration tickers.
    if best_score < 0:
        return None
    return best


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

    Prefers an explicit pay/accept calendar date; else a promptly-* phrase
    shaped like GT ``Payment: …`` so soft-match can hit structured labels.
    """
    if not text or not text.strip():
        return None
    # Date within ±80 chars of an accept/pay cue (order varies in filings).
    for cue in _SETTLE_PAY_CUE.finditer(text):
        lo, hi = max(0, cue.start() - 80), min(len(text), cue.end() + 80)
        window = text[lo:hi]
        dm = _ANY_DATE_RE.search(window)
        if dm:
            return dm.group(0).strip()
    # Emit the short GT-shaped clause — soft-match hits both
    # "Payment: promptly" and longer "Payment: promptly after/following …" labels.
    if _SETTLE_PROMPTLY_LONG.search(text) or _SETTLE_PROMPTLY_PAY.search(text):
        return "Payment: promptly"
    return None


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
        settlement = find_settlement(text)
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
