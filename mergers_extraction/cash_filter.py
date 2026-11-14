"""Cash consideration: the fine-tuned GLiNER's candidate amounts, filtered so that only a per-share merger price
can be the answer. Abstains when no candidate passes, which is what a stock-only deal needs.

Dropped: aggregate amounts ("$1,350,000,000", "$500 million"), par values ("$0.001"), and amounts whose wording
is about something else (trust account, redemption, exercise or trading price, fees, valuation).
Kept only with merger-price wording nearby ("per share", "right to receive", "in cash", "merger consideration").
Rules written from training filings only.
"""
from __future__ import annotations

import re

import common
import gliner_candidates

AGGREGATE = re.compile(r"\b(?:thousand|million|billion|trillion)\b|\bmm\b|\bbn\b", re.I)
OTHER_PRICE = re.compile(r"par\s+value|trust\s+account|redemption|redeem|exercise\s+price|strike|closing\s+(?:sale\s+)?price|"
                         r"trading\s+price|market\s+price|volume[- ]weighted|vwap|\bfee\b|fees|expenses|valued?\s+at|"
                         r"enterprise\s+value|equity\s+value|aggregate|in\s+the\s+aggregate|loan|note|debenture|warrant|"
                         r"dividend|distribution|termination|break-?up|premium\s+of|52-week|high\s+of|low\s+of|offering\s+price|"
                         r"conversion\s+price|purchase\s+price\s+of|to\s+purchase|sale\s+price|last\s+reported|"
                         r"divid(?:ing|ed)\b[^$]{0,60}$|\bby\s+\(?\$|preferred|series\s+[a-z](?:-\d)?\b",
                         re.I)
MERGER_PRICE = re.compile(r"per\s+(?:share|ads|unit|ordinary\s+share)|right\s+to\s+receive|in\s+cash|merger\s+consideration|"
                          r"cash\s+consideration|offer\s+price|for\s+each\s+(?:share|outstanding)", re.I)


def keep(candidate: dict) -> bool:
    value = candidate["value"]
    if AGGREGATE.search(value):
        return False
    numbers = common.numbers(value)
    if not numbers or not 0.05 <= numbers[0] < 10000:
        return False
    ctx = candidate["context"]
    near = ctx[max(0, 200 - 90):200 + len(value) + 90]  # about 90 characters either side of the amount
    if OTHER_PRICE.search(near) or AGGREGATE.search(ctx[200 + len(value):200 + len(value) + 12]):
        return False
    return bool(MERGER_PRICE.search(near))


def predict_all(accs: list[str], model: str) -> dict:
    out = {}
    for acc, cands in gliner_candidates.load(accs, model).items():
        cash = sorted((c for c in cands if c["field"] == "cash_consideration" and keep(c)), key=lambda c: -c["score"])
        if cash:
            best = cash[0]
            amount = common.numbers(best["value"])[0]
            symbol = re.match(r"\s*((?:US|C|A)?\$|€|£)", best["value"])
            out[acc] = {"cash_consideration": (f"{symbol.group(1) if symbol else '$'}{amount:,.2f} per share",
                                               re.sub(r"\s+", " ", best["context"]))}
        else:
            out[acc] = {"cash_consideration": ("", "")}
    return out
