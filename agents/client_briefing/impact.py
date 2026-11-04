"""Step 2 of the brief: match events to positions and turn per-share terms into the client's own numbers.

Everything is plain arithmetic on extracted terms. The LLM never calculates anything.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config, parsers
from .event_store import Event, EventState


@dataclass
class Position:
    ticker: str
    name: str
    shares: int = 0
    on_loan: int = 0
    watch_only: bool = False


@dataclass
class Impact:
    lines: list[dict] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    not_computed_reason: str | None = None
    offering_cap_exceeded: str | None = None


def fmt_int(n: float) -> str:
    return f"{int(n):,}"


def fmt_money(amount: float, currency: str | None = "USD") -> str:
    symbol = {"USD": "$", "CAD": "C$"}.get(currency or "USD", "$")
    return f"{symbol}{amount:,.0f}" if round(amount, 2) == int(amount) else f"{symbol}{amount:,.2f}"


def fmt_unit_price(amount: float, currency: str | None = "USD") -> str:
    symbol = {"USD": "$", "CAD": "C$"}.get(currency or "USD", "$")
    return f"{symbol}{amount:,.2f}" if round(amount, 2) == amount else f"{symbol}{amount:,.4f}".rstrip("0")


def fmt_date(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def fmt_ratio(x: float) -> str:
    return f"{x:g}"


def bny_cutoff(deadline: date, business_days: int = config.CUTOFF_BUSINESS_DAYS) -> date:
    """Illustrative BNY cut-off: a fixed number of weekdays before the official deadline."""
    d = deadline
    left = business_days
    while left:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def match_positions(positions: list[Position], events: list[Event]) -> list[tuple[Event, Position, str]]:
    """Match by ticker (exact). The EDGAR search results carry tickers for both rights and merger filings."""
    by_ticker = {p.ticker.upper(): p for p in positions}
    out: list[tuple[Event, Position, str]] = []
    for e in events:
        hits = [(t, r) for t, r in e.ticker_roles.items() if t.upper() in by_ticker]
        if hits:
            # A position can only match one security of the deal; the target's listing wins if both are held
            t, role = sorted(hits, key=lambda h: 0 if h[1] in {"target", "issuer"} else 1)[0]
            out.append((e, by_ticker[t.upper()], role))
    return out


def rights_impact(state: EventState, pos: Position) -> Impact:
    impact = Impact()
    ratio = state.facts.get("ratio")
    price = state.facts.get("price")
    record = state.facts.get("record_date")
    if pos.watch_only or not pos.shares:
        impact.not_computed_reason = "On your watchlist; no position to calculate."
        return impact
    rps = ratio.value.get("rights_per_share") if ratio else None
    spr = ratio.value.get("shares_per_right") if ratio else None
    if rps is None:
        impact.not_computed_reason = "The filing does not state how many rights each share receives."
        return impact

    eligible = pos.shares - pos.on_loan
    rights = math.floor(eligible * parsers.exact_fraction(rps))
    held = f"{fmt_int(eligible)} shares" + (f" ({fmt_int(pos.on_loan)} on loan excluded)" if pos.on_loan else "")
    impact.lines.append({"label": "Rights you would receive", "value": fmt_int(rights),
                         "formula": f"{held} × {fmt_ratio(rps)} right{'s' if rps != 1 else ''} per share"})

    def holding_caveats() -> Impact:
        if pos.on_loan:
            impact.caveats.append(f"{fmt_int(pos.on_loan)} of your shares are on loan and may not receive rights; check recall timing with your lending desk.")
        if record and record.value >= state.as_of:
            impact.caveats.append(f"Your entitlement is set by your holding on the record date, {fmt_date(record.value)}.")
        return impact

    if spr is None:
        impact.caveats.append("The filing does not state how many new shares each right buys, so the purchase is not calculated.")
        return holding_caveats()

    frac = parsers.exact_fraction(spr)
    new_shares = math.floor(rights * frac)
    is_unit = state.facts.get("security_class") and state.facts["security_class"].value == "units"
    noun = "units" if is_unit else "shares"

    # An offer can be capped in aggregate: "subscriptions will be accepted for only 12,000 Units".
    # A number bigger than the whole offering must never be shown, even after a reviewer clears the item.
    cap = re.search(r"(?:only|maximum of|limit of|up to|aggregate(?: maximum)?(?: of)?)\s+([\d,]{4,})[- ](?:units?|shares?)", ratio.raw, re.I)
    if cap and new_shares > int(cap[1].replace(",", "")):
        impact.offering_cap_exceeded = f"Calculated {fmt_int(new_shares)} {noun} exceeds the stated offering limit of {cap[1]}."
        impact.lines.append({"label": f"New {noun} you could buy", "value": "Prorated", "formula": f"Offering limited to {cap[1]} {noun} in total"})
        impact.caveats.append(f"The offering is limited to {cap[1]} {noun} in total, so any allocation would be prorated. Cash is not calculated.")
        return holding_caveats()

    if frac.numerator == 1 and frac.denominator > 1:
        per = f"1 new {noun[:-1]} per {frac.denominator} rights"
    else:
        per = f"{fmt_ratio(spr)} new {noun[:-1] if spr == 1 else noun} per right"
    impact.lines.append({"label": f"New {noun} you could buy", "value": f"Up to {fmt_int(new_shares)}",
                         "formula": f"{fmt_int(rights)} rights × {per}, rounded down"})

    amount = price.value.get("amount") if price else None
    if amount is not None:
        currency = price.value.get("currency")
        is_estimate = price.value.get("is_estimate")
        total = new_shares * amount
        label = "Cash to exercise in full" + (" (estimate)" if is_estimate else "")
        impact.lines.append({"label": label, "value": ("≈ " if is_estimate else "") + fmt_money(total, currency),
                             "formula": f"{fmt_int(new_shares)} × {fmt_unit_price(amount, currency)}" + (" estimated price" if is_estimate else "")})
        if is_estimate:
            impact.caveats.append("The final subscription price is set by a formula, so the cash figure will change.")
    elif price:
        impact.caveats.append("The subscription price is a formula with no stated number, so cash is not calculated.")
    else:
        impact.caveats.append("No subscription price is stated yet, so cash is not calculated.")

    security_class = state.facts["security_class"].value if state.facts.get("security_class") else None
    if security_class == "common":
        r = float(parsers.exact_fraction(rps) * frac)
        impact.lines.append({"label": "If you do not exercise", "value": f"Stake about {r / (1 + r):.1%} smaller",
                             "formula": "Assumes every other right is exercised; arithmetic only"})

    impact.caveats.append("Before any offering limit or proration.")
    return holding_caveats()


def merger_impact(state: EventState, pos: Position, role: str) -> Impact:
    impact = Impact()
    if pos.watch_only or not pos.shares:
        impact.not_computed_reason = "On your watchlist; no position to calculate."
        return impact
    if role != "target":
        impact.not_computed_reason = ("The stated consideration is for holders of the company being acquired. "
                                      "Your holding is in another party to the deal, so it is not calculated.")
        return impact
    cash = state.facts.get("cash_per_share")
    ratio = state.facts.get("exchange_ratio")
    if not cash and not ratio:
        impact.not_computed_reason = "The consideration depends on a formula or an election, so it is not calculated. See the filing terms."
        return impact
    if cash:
        impact.lines.append({"label": "Cash you would receive", "value": fmt_money(pos.shares * cash.value),
                             "formula": f"{fmt_int(pos.shares)} shares × {fmt_unit_price(cash.value)} per share"})
    if ratio:
        new_shares = math.floor(pos.shares * ratio.value)
        acquirer = state.event.counterparty or "the acquirer"
        impact.lines.append({"label": "Shares you would receive", "value": fmt_int(new_shares),
                             "formula": f"{fmt_int(pos.shares)} shares × {fmt_ratio(ratio.value)} {_short_name(acquirer)} shares, rounded down"})
    # A dollar amount we could not turn into a figure must not disappear silently
    cash_text = state.text.get("cash_consideration") or ""
    if not cash and re.search(r"\$\s?\d", cash_text) and not re.match(r"\s*(no|none)\b", cash_text, re.I):
        impact.caveats.append("The filing also describes a cash amount that is conditional or formula-based, so it is not included. See the terms.")
    impact.caveats.append("Before tax, withholding and any adjustment in the merger agreement; assumes the deal closes on these terms.")
    if pos.on_loan:
        impact.caveats.append(f"{fmt_int(pos.on_loan)} of your shares are on loan; votes and elections on those shares may need a recall.")
    return impact


def tender_impact(state: EventState, pos: Position) -> Impact:
    """What the holder could tender and, when the filing states a price, the cash if every share is accepted."""
    impact = Impact()
    if pos.watch_only or not pos.shares:
        impact.not_computed_reason = "On your watchlist; no position to calculate."
        return impact
    eligible = pos.shares - pos.on_loan
    held = f"{fmt_int(eligible)} shares" + (f" ({fmt_int(pos.on_loan)} on loan excluded)" if pos.on_loan else "")
    impact.lines.append({"label": "Shares you could tender", "value": fmt_int(eligible), "formula": held})

    fact = state.facts.get("offer_price")
    price = fact.value if fact else None
    kind = price["kind"] if price else None
    if kind in {"fixed", "cash_plus"}:
        impact.lines.append({"label": "Cash if all are accepted", "value": fmt_money(eligible * price["amount"]),
                             "formula": f"{fmt_int(eligible)} shares × {fmt_unit_price(price['amount'])} per share"})
        if kind == "cash_plus":
            impact.caveats.append("Each share also receives a contingent right described in the filing. Its value is not included.")
    elif kind == "range":
        impact.lines.append({"label": "Cash if all are accepted", "value": f"{fmt_money(eligible * price['low'])} to {fmt_money(eligible * price['high'])}",
                             "formula": f"{fmt_int(eligible)} shares × {fmt_unit_price(price['low'])} to {fmt_unit_price(price['high'])} per share"})
        impact.caveats.append("The final price is set within this range by the offer's auction.")
    elif kind == "formula":
        impact.caveats.append("The offer price is a formula, such as net asset value on a later date, so cash is not calculated.")
    elif kind == "noncash":
        impact.caveats.append("The offer does not state a cash price per share, so cash is not calculated. See the terms.")
    else:
        impact.caveats.append("No offer price is stated yet, so cash is not calculated.")

    proration = state.text.get("proration_terms")
    if proration and not re.match(r"\s*(?:no\b|none\b|not\b|n/a)", proration, re.I):
        impact.caveats.append("The offer has a limit, so fewer shares may be accepted than you tender.")
    impact.caveats.append("Before tax and withholding; subject to the offer's conditions.")
    if pos.on_loan:
        impact.caveats.append(f"{fmt_int(pos.on_loan)} of your shares are on loan and must be recalled before they can be tendered; check timing with your lending desk.")
    return impact


def _short_name(name: str) -> str:
    """'Fox Corporation' from 'Fox Corporation'; 'First Hawaiian' from 'First Hawaiian, Inc.'"""
    return name.split(",")[0].strip()


def compute_impact(state: EventState, pos: Position, role: str) -> Impact:
    if state.event.action == "rights_issue":
        return rights_impact(state, pos)
    if state.event.action == "tender_offer":
        return tender_impact(state, pos)
    return merger_impact(state, pos, role)
