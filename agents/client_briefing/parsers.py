"""Turn extracted free text into values the agent can calculate with.

Everything here is deliberately conservative: when wording is conditional, formula-based or unclear the
parser returns None, and the brief shows the filing's wording instead of a calculated number.
"""

from __future__ import annotations

import re
from datetime import date
from fractions import Fraction

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
_MONTH_NAMES = "|".join(list(MONTHS) + ["jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"])
_DATE = re.compile(rf"\b(\d{{1,2}})/(\d{{1,2}})/(\d{{4}})\b|\b({_MONTH_NAMES})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", re.I)
_UNSTATED = re.compile(r"not\s+(?:yet\s+)?(?:stated|specified|set|fixed|determined|provided|disclosed)|no\s+calendar|"
                       r"to be determined|placeholder|\bblank\b|\bTBD\b", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "a": 1, "an": 1, "each": 1}


def _to_date(m: re.Match) -> date | None:
    try:
        if m[1]:
            return date(int(m[3]), int(m[1]), int(m[2]))
        return date(int(m[6]), MONTHS[next(k for k in MONTHS if k.startswith(m[4].lower()[:3]))], int(m[5]))
    except ValueError:
        return None


def parse_date(text: str | None) -> date | None:
    """First calendar date in the text, unless the text says the date is not set before giving one."""
    if not text:
        return None
    m = _DATE.search(text)
    if not m:
        return None
    unstated = _UNSTATED.search(text)
    if unstated and unstated.start() < m.start():
        return None
    return _to_date(m)


def parse_effective_date(text: str | None) -> date | None:
    """Closing or delivery date. Stricter: other dates are often mentioned in the same sentence."""
    if not text or _UNSTATED.search(text) or re.search(r"no closing date", text, re.I):
        return None
    for m in _DATE.finditer(text):
        before = text[max(0, m.start() - 40):m.start()].lower()
        if "expir" in before or "record date" in text[m.end():m.end() + 25].lower():
            continue
        return _to_date(m)
    return None


def _num(tok: str) -> float | None:
    tok = tok.lower().replace(",", "")
    return float(tok) if re.match(r"^\d+(\.\d+)?$", tok) else WORDS.get(tok)


def parse_ratio(text: str | None) -> dict | None:
    """Rights per share held and new shares per right. Either can be None when the filing does not state it."""
    if not text:
        return None
    n = r"(?<![/\d.])(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|an?)"
    out: dict[str, float | None] = {"rights_per_share": None, "shares_per_right": None}
    # One clause at a time: a number in one clause must never pair with a noun in the next.
    for clause in re.split(r";\s*|\.\s+", text):
        if _UNSTATED.search(clause):
            continue
        if out["rights_per_share"] is None:
            m = re.search(n + r"\s+(?:[\w-]+\s+){0,3}rights?\s+(?:per|for\s+each|for\s+every)\s+" + n + r"?\s*"
                          r"(?:[\w-]+\s+){0,5}(?:shares?|units?|ads)", clause, re.I)
            if m:
                a, b = _num(m[1]), _num(m[2]) if m[2] else 1.0
                if a and b:
                    out["rights_per_share"] = round(a / b, 6)
        if out["shares_per_right"] is None:
            m = re.search(n[:-1] + r"|each)\s+(?:[\w-]+\s+){0,3}rights?\s+(?:[\w-]+\s+){0,20}?"
                          r"(?:purchases?|subscribe\s+for|subscription\s+for|buy|acquire|to)\s+(?:of\s+)?(?:approximately\s+)?"
                          + n + r"\s+(?:of\s+an?\s+)?(?:[\w-]+\s+){0,3}(?:shares?|units?|ads)", clause, re.I)
            if m:
                a, b = _num(m[1]), _num(m[2])
                if a and b:
                    out["shares_per_right"] = round(b / a, 6)
        if out["shares_per_right"] is None:  # "1.145 new shares ... purchasable per right"
            m = re.search(n + r"\s+(?:[\w-]+\s+){0,4}(?:shares?|units?)\s+(?:[\w-]+\s+){0,5}(?:per|for each)\s+"
                          r"(?:whole\s+)?(?:subscription\s+)?right\b", clause, re.I)
            if m and _num(m[1]):
                out["shares_per_right"] = round(float(_num(m[1])), 6)
        if all(v is None for v in out.values()):  # "One new share may be purchased for each share held": no separate rights
            m = re.search(n + r"\s+new\s+shares?\b.*?\bpurchased\s+for\s+(?:each|every)\s+(?:(\d+)\s+)?shares?\b", clause, re.I)
            if m and _num(m[1]):
                out = {"rights_per_share": round(1 / float(m[2] or 1), 6), "shares_per_right": round(float(_num(m[1])), 6)}
    return out if any(v is not None for v in out.values()) else None


def exact_fraction(x: float) -> Fraction:
    """0.3333 means one third, so it must not lose a share on 6,000 rights. 0.1251 really is 0.1251, not one eighth."""
    decimals = len(repr(x).split(".")[1]) if "." in repr(x) else 0
    if x > 0 and round(1 / x) >= 1 and round(1 / round(1 / x), decimals) == x:
        return Fraction(1, round(1 / x))
    return Fraction(repr(x))


def parse_price(text: str | None) -> dict | None:
    """Subscription price: a fixed amount, a formula with a stated estimate, or a formula with no number."""
    if not text:
        return None
    money = r"(?:US|C)?\$\s?(\d[\d,]*(?:\.\d+)?)"
    if re.search(r"US\$\s?\d", text):  # "C$6.74 or US$4.81": report the US dollar figure
        m = re.search(r"US\$\s?(\d[\d,]*(?:\.\d+)?)", text)
        return {"amount": float(m[1].replace(",", "")), "currency": "USD", "is_estimate": False}
    currency = "CAD" if re.search(r"C\$|\bCAD\b|canadian", text) else "USD" if re.search(r"\$|u\.s\. dollar|usd", text, re.I) else None
    amount: str | None = None
    is_estimate = True
    est = re.search(r"(?:estimat\w*|would have been)[^$]{0,60}" + money, text, re.I)
    start = re.match(r"^\W*" + money, text)
    if est:
        amount = est[1]
    elif start:  # "$6.90 per share, equal to a 3% discount ..." is a set price
        amount, is_estimate = start[1], False
    elif re.search(r"formula|%|lesser of|greater of|average|discount|vwap|not more than|will not exceed", text, re.I):
        amount = None
    elif re.search(money, text):
        amount, is_estimate = re.search(money, text)[1], False
    else:
        return None
    return {"amount": float(amount.replace(",", "")) if amount else None, "currency": currency, "is_estimate": is_estimate}


def parse_bool_yes_no(text: str | None) -> bool | None:
    if text is None:
        return None
    t = str(text).strip().lower()
    if t.startswith(("yes", "true")):
        return True
    if t.startswith(("no", "false")):
        return False
    return None


def parse_rights_status(text: str | None) -> str | None:
    """Most advanced status stated as a fact: 'Announced; expiration extended' is 'extended'."""
    if not text:
        return None
    parts = [p for i, p in enumerate(text.lower().split(";"))
             if i == 0 or not re.search(r"\b(unless|may|if|until|scheduled|expected)\b", p)]
    joined = " ; ".join(parts)
    for k in ["withdrawn", "terminated", "completed", "extended", "amended", "commenced", "proposed"]:
        if re.search(rf"(?<!unless )(?<!may be )(?<!earlier )(?<!not )(?<!not yet )(?<!statement )\b{k}\b(?! registration)", joined):
            return k
    if re.search(r"\b(expired|fully subscribed|results)\b", joined):
        return "completed"
    return "proposed" if "announced" in joined else None


def parse_merger_status(text: str | None) -> str | None:
    if not text:
        return None
    head = text.lower().split(";")[0]
    if re.search(r"\b(terminated|withdrawn|abandoned|cancelled)\b", head):
        return "terminated"
    if re.search(r"\b(completed|consummated|closed)\b", head) and not re.search(r"\bnot\b|\bexpected\b", head):
        return "completed"
    if "announced" in head and "pending" not in head:
        return "announced"
    return "pending"


def parse_cash_per_share(text: str | None) -> float | None:
    """Fixed cash per share. Conditional or elective wording returns None."""
    if not text or re.match(r"\s*(no\b|not\b|none\b|if\b|up to\b)", text, re.I):
        return None
    m = re.match(r"^\s*(?:USD\s*)?(?:US)?\$\s?(\d[\d,]*(?:\.\d+)?)\s+(?:(?:in\s+)?cash|per\s+(?:eligible\s+)?(?:share|common|ordinary))", text, re.I)
    return float(m[1].replace(",", "")) if m else None


def parse_exchange_ratio(text: str | None) -> float | None:
    """Fixed shares received per one share held. Formula-based or conditional wording returns None."""
    if not text or re.match(r"\s*(no\b|not\b|none\b|if\b|up to\b|the\b|for\b)", text, re.I):
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s+(?:[\w.&,’'()/-]+\s+){0,12}?(?:shares?|stock|interests?)\b.*?"
                 r"\b(?:per|for\s+each|for\s+every)\s+(?:1\s+|one\s+)?", text, re.I)
    if not m:
        return None
    return float(m[1])


def parse_tender_status(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "terminat" in t or "withdrawn" in t:
        return "terminated"
    if "completed" in t or "final results" in t:
        return "completed"
    for k in ["extended", "amended", "commenced"]:
        if k in t:
            return k
    return None


_OFFER_NUMBER = r"(?:USD\s*|US)?\$?\s?(\d[\d,]*(?:\.\d+)?)"


def parse_tender_price(text: str | None) -> dict | None:
    """Offer price. Only a plain amount, a price range or cash plus a contingent right gives the client a figure."""
    if not text:
        return None
    t = text.strip()
    number = lambda s: float(s.replace(",", ""))  # noqa: E731
    m = re.fullmatch(_OFFER_NUMBER + r"(?:\s+(?:in\s+)?cash)?(?:\s*,?\s*(?:per\b|net\b|without\b).*)?", t, re.I)
    if m:
        return {"kind": "fixed", "amount": number(m[1])}
    m = re.match(_OFFER_NUMBER + r"\s*(?:to|-|–)\s*" + _OFFER_NUMBER + r"\b", t, re.I)
    if m:
        return {"kind": "range", "low": number(m[1]), "high": number(m[2])}
    m = re.match(_OFFER_NUMBER + r"\s+(?:in\s+)?cash\s+(?:plus|and)\b", t, re.I)
    if m:
        return {"kind": "cash_plus", "amount": number(m[1])}
    if re.search(r"net asset value|\bNAV\b|%|formula", t, re.I):
        return {"kind": "formula"}
    return {"kind": "noncash"}


def tender_security(text: str | None) -> str | None:
    """What the offer buys. The security named first decides: 'options to purchase common stock' are options.

    Words in a fund's name must not count, so 'Preferred Income Fund common shares' and 'Option Income Fund' are shares.
    """
    if not text:
        return None
    t = text.lower()
    if "american depositary" in t:
        return "shares"
    patterns = {"options": r"\boptions\b", "warrants": r"\bwarrants?\b", "notes": r"\bnotes?\b|\bdebentures?\b|\bbonds?\b",
                "preferred": r"\bpreferred\s+(?:stock|shares?)\b|\bdepositary\b", "units": r"\bunits?\b",
                "shares": r"\bcommon\b|\bordinary\b|\bshares?\b|\bstock\b|\binterests?\b"}
    found = {k: m.start() for k, p in patterns.items() if (m := re.search(p, t))}
    return min(found, key=found.get) if found else None


def security_class(text: str | None) -> str | None:
    """The security named first is the one bought ('Class A common stock, offered to holders of Trust units')."""
    if not text:
        return None
    t = text.lower()
    if re.search(r"not specified|not stated", t):
        return None
    patterns = {"ads": r"american depositary|\bads\b", "units": r"\bunits?\b", "preferred": r"preferred",
                "notes": r"\bnotes?\b", "common": r"common|ordinary|shares?"}
    found = {k: m.start() for k, p in patterns.items() if (m := re.search(p, t))}
    return min(found, key=found.get) if found else "other"
