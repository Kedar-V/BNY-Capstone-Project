"""Client briefing agent: reads a client's holdings and writes their corporate-action brief.

    python -m agents.client_briefing.agent --client demo-pension --as-of 2026-09-30
    python -m agents.client_briefing.agent --build-demo --env-file ../.env

Five steps, each one logged in the brief's trace:
  1. Event store     events known on the brief date, built from the extraction runs
  2. Match holdings  events on securities the client holds or watches, with position-level numbers
  3. Prioritize      action needed > terms changed > new > recently closed > on the horizon
  4. Generate        the LLM writes a summary from the structured record; numbers come from the record
  5. Review          checks route doubtful items to operations; only cleared items reach the client
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime

from . import config
from .event_store import Event, EventState, Fact, load_events
from .impact import Impact, Position, compute_impact, fmt_date, fmt_int, fmt_ratio, fmt_unit_price, match_positions
from .narrate import Narrator
from .prioritize import TIER_LABEL, TIER_ORDER, Decision, decide, sort_key
from .verify import QuoteChecker, check_record

DEMO_AS_OF = ["2026-01-30", "2026-03-27", "2026-08-28", "2026-09-30"]
DEMO_CADENCES = ["weekly", "daily"]

STATUS_LABEL = {"commenced": "Open", "proposed": "Announced, not yet open", "extended": "Open, deadline extended", "amended": "Open, terms amended",
                "completed": "Completed", "terminated": "Terminated", "withdrawn": "Withdrawn", "pending": "Pending", "announced": "Announced"}
ACTION_LABEL = {"rights_issue": "Rights offering", "merger": "Merger", "tender_offer": "Tender offer"}
ACTION_FILTER_LABEL = {"rights_issue": "Rights", "merger": "Mergers", "tender_offer": "Tender offers"}
ACTION_PLURAL = {"rights_issue": "rights offerings", "merger": "mergers", "tender_offer": "tender offers"}
_FACT_LABEL = {"record_date": "Record date", "expiration_date": "Expiration", "election_deadline": "Election deadline",
               "effective_date": "Issuance / closing", "ratio": "Subscription ratio", "price": "Subscription price",
               "oversubscription": "Over-subscription", "transferable": "Rights transferable", "security_class": "Security",
               "vote_date": "Shareholder vote", "cash_per_share": "Cash consideration", "exchange_ratio": "Stock consideration",
               "offer_price": "Offer price", "withdrawal_deadline": "Withdrawal deadline"}
_SOURCE_FIELD = {"ratio": "subscription_ratio", "price": "subscription_price", "oversubscription": "oversubscription_rights",
                 "transferable": "rights_transferable", "security_class": "security_description", "vote_date": "shareholder_vote_date",
                 "cash_per_share": "cash_consideration", "exchange_ratio": "stock_exchange_ratio"}


def load_clients() -> list[dict]:
    return json.loads(config.CLIENTS_JSON.read_text(encoding="utf-8"))


def _positions(client: dict) -> list[Position]:
    held = [Position(p["ticker"], p["name"], p["shares"], p.get("onLoan", 0)) for p in client["positions"]]
    held_tickers = {p.ticker for p in held}
    return held + [Position(w["ticker"], w["name"], watch_only=True) for w in client.get("watchlist", []) if w["ticker"] not in held_tickers]


def _clip(text: str | None, limit: int = 260) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _value_text(key: str, value) -> str:
    if isinstance(value, date):
        return fmt_date(value)
    if key == "ratio":
        parts = []
        if value.get("rights_per_share") is not None:
            parts.append(f"{fmt_ratio(value['rights_per_share'])} right per share")
        if value.get("shares_per_right") is not None:
            parts.append(f"{fmt_ratio(value['shares_per_right'])} new share per right")
        return "; ".join(parts)
    if key == "price":
        if value.get("amount") is None:
            return "Formula"
        return fmt_unit_price(value["amount"], value.get("currency")) + (" (estimate)" if value.get("is_estimate") else "")
    if key == "offer_price":
        if value["kind"] == "fixed":
            return f"{fmt_unit_price(value['amount'])} per share"
        if value["kind"] == "cash_plus":
            return f"{fmt_unit_price(value['amount'])} per share in cash plus a contingent right"
        if value["kind"] == "range":
            return f"{fmt_unit_price(value['low'])} to {fmt_unit_price(value['high'])} per share"
        return "Formula" if value["kind"] == "formula" else "Not a cash price"
    if key == "cash_per_share":
        return f"{fmt_unit_price(value)} per share"
    if key == "exchange_ratio":
        return f"{fmt_ratio(value)} shares per share"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _evidence(state: EventState, checker: QuoteChecker) -> list[dict]:
    out = []
    for key, fact in state.facts.items():
        out.append({"key": key, "label": _FACT_LABEL.get(key, key), "value": _value_text(key, fact.value), "stated": _clip(fact.raw, 400),
                    "quote": _clip(fact.quote, 700), "location": fact.location or "", "form": fact.form, "filed": fact.filed.isoformat(),
                    "url": fact.url, "verified": checker.verified(fact.accession, fact.quote)})
    return out


def _terms(state: EventState) -> list[dict]:
    text = state.text
    if state.event.action == "rights_issue":
        keys = [("Rights ratio", "subscription_ratio"), ("Subscription price", "subscription_price"), ("Record date", "record_date"),
                ("Expiration", "expiration_date"), ("Issuance", "effective_date"), ("Security", "security_description"),
                ("If not exercised", "default_option")]
        out = [{"label": label, "value": _clip(text.get(k))} for label, k in keys if text.get(k)]
        for label, key in [("Over-subscription", "oversubscription"), ("Rights transferable", "transferable")]:
            if key in state.facts:
                out.append({"label": label, "value": "Yes" if state.facts[key].value else "No"})
        return out
    if state.event.action == "tender_offer":
        keys = [("Offer price", "offer_price"), ("Price basis", "offer_price_basis"), ("Price conditions", "offer_price_qualifications"),
                ("Expiration", "expiration_date"), ("Withdrawal deadline", "withdrawal_deadline"), ("Settlement", "settlement_date"),
                ("Limit and proration", "proration_terms"), ("Minimum condition", "minimum_tender_condition"),
                ("Conditions", "tendering_conditions"), ("Security", "security_description"), ("If you do nothing", "default_option")]
        return [{"label": label, "value": _clip(text.get(k))} for label, k in keys if text.get(k)]
    keys = [("Consideration", "consideration_type"), ("Cash", "cash_consideration"), ("Stock", "stock_exchange_ratio"),
            ("Shareholder vote", "shareholder_vote_date"), ("Election deadline", "election_deadline"), ("Closing", "effective_date"),
            ("Security", "security_description"), ("If no election", "default_option")]
    return [{"label": label, "value": _clip(text.get(k))} for label, k in keys if text.get(k)]


def _options(state: EventState) -> str | None:
    return _clip(state.text.get("available_options"), 420)


def _change_sentence(key: str, previous, current) -> str:
    label = _FACT_LABEL.get(key, key)
    if key == "ratio":
        added = {k: v for k, v in current.items() if previous.get(k) is None and v is not None}
        if added and all(previous.get(k) in (None, v) for k, v in current.items()):
            return f"The filing now states {_value_text(key, added)}"
        names = {"rights_per_share": "Rights per share", "shares_per_right": "New shares per right"}
        moved = [f"{names[k]} changed from {fmt_ratio(previous[k])} to {fmt_ratio(v)}" for k, v in current.items()
                 if previous.get(k) is not None and v != previous[k]]
        return "; ".join(moved)
    if (key == "price" and previous.get("amount") is None) or (key == "offer_price" and previous["kind"] in {"formula", "noncash"}):
        return f"{label} is now stated as {_value_text(key, current)}"
    return f"{label} changed from {_value_text(key, previous)} to {_value_text(key, current)}"


def _changes(state: EventState) -> list[dict]:
    return [{"label": _FACT_LABEL.get(c.key, c.key), "from": _value_text(c.key, c.previous), "to": _value_text(c.key, c.current),
             "text": _change_sentence(c.key, c.previous, c.current), "form": c.form, "filed": c.filed.isoformat(), "accession": c.accession}
            for c in state.changes]


def _headline(state: EventState, role: str) -> str:
    e = state.event
    if e.action == "rights_issue":
        return {"proposed": f"{e.issuer} has announced a rights offering that is not yet open",
                "completed": f"{e.issuer} has reported the close of its rights offering",
                "extended": f"{e.issuer} has extended its rights offering",
                "amended": f"{e.issuer} has amended its rights offering"}.get(state.status, f"{e.issuer} is conducting a rights offering")
    if e.action == "tender_offer":
        offer = f"The tender offer by {e.counterparty} for {e.issuer}" if e.counterparty else f"The tender offer by {e.issuer} for its own shares"
        if state.status == "completed":
            return f"{offer} has closed"
        if state.status == "terminated":
            return f"{offer} has been terminated"
        price = state.facts.get("offer_price")
        if price and price.value["kind"] == "noncash":  # paid in other securities, so "buying back" would be wrong
            return f"{e.counterparty} has an exchange offer open for shares of {e.issuer}" if e.counterparty else f"An exchange offer is open for shares of {e.issuer}"
        return f"{e.counterparty} is offering to buy shares of {e.issuer}" if e.counterparty else f"{e.issuer} is offering to buy back its own shares"
    if state.status == "completed":
        return f"The merger of {e.issuer} has completed"
    if state.status == "terminated":
        return f"The merger of {e.issuer} has been terminated"
    return f"{e.issuer} is to be acquired by {e.counterparty}" if e.counterparty else f"{e.issuer} is party to a pending merger"


def _position_sentence(state: EventState, pos: Position, impact: Impact) -> str:
    """The calculated lines as one sentence, for the fixed template and as wording the model can follow."""
    v = {l["label"]: l["value"] for l in impact.lines}
    if state.event.action == "tender_offer":
        tendered = v["Shares you could tender"]
        cash = v.get("Cash if all are accepted")
        return (f"If you tender your {tendered} eligible shares and all are accepted, you would receive {cash}" if cash
                else f"You could tender up to {tendered} eligible shares")
    shares = fmt_int(pos.shares - pos.on_loan) if state.event.action == "rights_issue" else fmt_int(pos.shares)
    if state.event.action == "rights_issue":
        text = f"Your {shares} eligible shares would receive {v['Rights you would receive']} rights"
        new = next((val for label, val in v.items() if label.startswith("New ")), None)
        noun = next((label.split()[1] for label in v if label.startswith("New ")), "shares")
        if new == "Prorated":
            text += f", with new {noun} subject to proration under the offering limit"
        elif new:
            text += f", enough to buy {new.lower()} new {noun}"
        cash = next((val for label, val in v.items() if label.startswith("Cash to exercise")), None)
        if cash:
            text += f" for {cash.replace('≈ ', 'about ')}"
        return text
    parts = []
    if "Cash you would receive" in v:
        parts.append(f"{v['Cash you would receive']} in cash")
    if "Shares you would receive" in v:
        parts.append(f"{v['Shares you would receive']} {state.event.counterparty.split(',')[0] if state.event.counterparty else 'acquirer'} shares")
    return f"Your {shares} shares would receive " + " and ".join(parts)


def _narrative_facts(state: EventState, pos: Position, decision: Decision, impact: Impact, role: str) -> dict:
    """Everything the model may say. Numbers are already formatted, so it only has to copy them."""
    e = state.event
    facts: dict = {"brief_date": fmt_date(state.as_of), "event_type": ACTION_LABEL[e.action], "company": e.issuer,
                   "headline": _headline(state, role), "status": STATUS_LABEL.get(state.status or "", state.status),
                   "priority": TIER_LABEL[decision.tier]}
    if e.counterparty:
        facts["counterparty"] = e.counterparty
    if pos.watch_only:
        facts["position"] = "On watchlist, no position held"
    else:
        facts["position"] = f"{fmt_int(pos.shares)} shares"
        if pos.on_loan:
            facts["on_loan"] = f"{fmt_int(pos.on_loan)} shares on loan"
    if impact.lines:
        # The dilution figure stays in the table, next to the assumption it depends on. A sentence would drop the assumption.
        facts["impact"] = [{"label": l["label"], "value": l["value"]} for l in impact.lines if l["label"] != "If you do not exercise"]
        facts["position_effect"] = _position_sentence(state, pos, impact)
    if e.action == "tender_offer" and state.facts.get("offer_price"):
        facts["offer_price"] = _value_text("offer_price", state.facts["offer_price"].value)
        if state.facts["offer_price"].value["kind"] == "noncash":
            facts["offer_terms_as_stated"] = _clip(state.facts["offer_price"].raw, 160)
        if any(l["label"] == "Cash if all are accepted" for l in impact.lines):
            facts["tender_cash"] = True
    if impact.not_computed_reason:
        facts["impact_note"] = impact.not_computed_reason
        if pos.watch_only:
            facts["position_note"] = "You have no position in this security; it is on your watchlist."
        elif role != "target" and e.action == "merger":
            facts["position_note"] = "Your holding is in another party to the deal, so the stated consideration is not calculated."
    if decision.deadline:
        facts["deadline_label"] = decision.deadline.label
        facts["deadline"] = fmt_date(decision.deadline.fact.value)
        if decision.cutoff and decision.tier == "action":
            facts["bny_cutoff"] = fmt_date(decision.cutoff)
            if decision.cutoff_passed:
                facts["cutoff_passed"] = True
    if state.changes:
        facts["changes"] = [_change_sentence(c.key, c.previous, c.current) for c in state.changes]
    return facts


def _item(state: EventState, pos: Position, role: str, decision: Decision, impact: Impact, checker: QuoteChecker) -> dict:
    e = state.event
    today = state.as_of
    evidence = _evidence(state, checker)
    reasons = check_record(state, impact, decision.tier)
    for ev in evidence:  # a key value whose quote cannot be found in the filing needs a person
        if ev["verified"] is False and ev["key"] in {"expiration_date", "election_deadline", "record_date", "ratio", "price", "offer_price"} and decision.tier == "action":
            reasons.append({"code": "quote_not_found", "detail": f"The quote behind {ev['label'].lower()} was not found in the filing text."})
    item = {
        "id": f"{e.id}:{pos.ticker}",
        "eventId": e.id,
        "action": e.action,
        "actionLabel": ACTION_LABEL[e.action],
        "tier": decision.tier,
        "tierLabel": TIER_LABEL[decision.tier],
        "title": e.title,
        "issuer": e.issuer,
        "counterparty": e.counterparty,
        "ticker": pos.ticker,
        "role": role,
        "status": STATUS_LABEL.get(state.status or "", state.status or "Unknown"),
        "position": {"name": pos.name, "shares": pos.shares, "onLoan": pos.on_loan, "watchOnly": pos.watch_only},
        "impact": {"lines": impact.lines, "caveats": impact.caveats, "reason": impact.not_computed_reason},
        "terms": _terms(state),
        "options": _options(state),
        "changes": _changes(state),
        "evidence": evidence,
        "sources": [{"form": f.form, "filed": f.filed.isoformat(), "url": f.url, "accession": f.accession} for f in state.filings],
        "latestFiled": state.latest.filed.isoformat(),
        "review": {"needed": bool(reasons), "reasons": reasons},
    }
    vote = state.facts.get("vote_date")
    if vote and vote.value < today and state.status not in {"completed", "terminated"}:
        item["stageNote"] = f"Vote held {fmt_date(vote.value)}"
    if decision.deadline:
        item["deadline"] = {"label": decision.deadline.label, "kind": decision.deadline.kind, "date": decision.deadline.fact.value.isoformat(),
                            "display": fmt_date(decision.deadline.fact.value), "daysAway": (decision.deadline.fact.value - today).days,
                            "quote": _clip(decision.deadline.fact.quote, 500), "form": decision.deadline.fact.form, "url": decision.deadline.fact.url}
    if decision.cutoff:
        item["cutoff"] = {"date": decision.cutoff.isoformat(), "display": fmt_date(decision.cutoff), "daysAway": (decision.cutoff - today).days,
                          "passed": decision.cutoff_passed}
    return item


def prepare_brief(client: dict, as_of: date, cadence: str, events: list[Event], checker: QuoteChecker) -> tuple[dict, list[dict]]:
    """Steps 1-3 and 5's record checks. Summaries are attached afterwards so they can be drafted in parallel."""
    lookback = config.LOOKBACK_DAYS[cadence]
    trace: list[dict] = []

    known = [(e, s) for e in events if (s := e.as_of(as_of, lookback))]
    by_action = ", ".join(f"{n} {ACTION_PLURAL[a]}" for a in config.ENABLED_ACTIONS if (n := sum(e.action == a for e, _ in known)))
    n_filings = sum(len(s.filings) for _, s in known)
    trace.append({"step": "Event store", "detail": f"{len(known)} corporate actions known on {fmt_date(as_of)} ({by_action}) "
                                                   f"from {fmt_int(n_filings)} filings. Nothing filed later is used."})

    positions = _positions(client)
    visible = [e for e, _ in known]
    matches = match_positions(positions, visible)
    held = sum(not p.watch_only for p in positions)
    trace.append({"step": "Match holdings", "detail": f"{held} positions and {len(positions) - held} watchlist names matched by ticker: "
                                                      f"{len(matches)} of {len(known)} events touch this client."})

    states = {e.id: s for e, s in known}
    items: list[dict] = []
    facts_list: list[dict] = []
    dropped = 0
    for e, pos, role in matches:
        state = states[e.id]
        decision = decide(state, role, lookback, pos.watch_only)
        if decision is None:
            dropped += 1
            continue
        # Nothing left to calculate once an event has closed
        impact = Impact() if decision.tier == "completed" else compute_impact(state, pos, role)
        item = _item(state, pos, role, decision, impact, checker)
        facts = _narrative_facts(state, pos, decision, impact, role)
        item["_facts"] = facts
        items.append(item)
        facts_list.append(facts)

    items.sort(key=sort_key)
    counts = {t: sum(i["tier"] == t for i in items) for t in TIER_ORDER}
    trace.append({"step": "Prioritize", "detail": f"{counts['action']} action needed, {counts['changed']} terms changed, {counts['new']} new, "
                                                  f"{counts['completed']} recently closed, {counts['upcoming']} on the horizon. "
                                                  f"{dropped} closed or stale event{'' if dropped == 1 else 's'} left out."})
    brief = {"clientId": client["id"], "asOf": as_of.isoformat(), "cadence": cadence, "lookbackDays": lookback, "counts": counts,
             "items": items, "trace": trace}
    return brief, facts_list


def finish_brief(brief: dict, narrator: Narrator) -> dict:
    """Attach the summaries and close the trace."""
    n_llm = n_template = 0
    for item in brief["items"]:
        drafted = narrator.get(item.pop("_facts"))
        item["summary"] = drafted["summary"]
        item["summarySource"] = drafted["source"]
        n_llm += drafted["source"] == "llm"
        n_template += drafted["source"] != "llm"
    brief["trace"].append({"step": "Generate", "detail": f"{n_llm} summaries written by the LLM from the structured record and {n_template} from the fixed template. "
                                                         "Each one was checked: numbers must appear in the record and advice wording is rejected."})
    held = sum(i["review"]["needed"] for i in brief["items"])
    brief["heldForReview"] = held
    brief["trace"].append({"step": "Review & deliver", "detail": f"{len(brief['items']) - held} items cleared for the client; {held} held for operations review."})
    return brief


def build_brief(client: dict, as_of: date, cadence: str, events: list[Event], narrator: Narrator, checker: QuoteChecker) -> dict:
    brief, facts = prepare_brief(client, as_of, cadence, events, checker)
    narrator.prepare(facts)
    return finish_brief(brief, narrator)


# ---------------------------------------------------------------- command line

def _print_brief(client: dict, brief: dict) -> None:
    print(f"\n{client['name']} | {brief['cadence']} brief | as of {brief['asOf']}")
    print("=" * 78)
    for t in brief["trace"]:
        print(f"[{t['step']}] {t['detail']}")
    for item in brief["items"]:
        flag = "  [HELD FOR REVIEW]" if item["review"]["needed"] else ""
        print(f"\n{item['tierLabel'].upper()}{flag}\n{item['title']} ({item['ticker']}) | {item['status']}")
        print(f"  {item['summary']}")
        if item.get("cutoff") and item["tier"] == "action":
            print(f"  BNY cut-off {item['cutoff']['display']} | {item['deadline']['label']} {item['deadline']['display']}")
        for line in item["impact"]["lines"]:
            print(f"  - {line['label']}: {line['value']}  ({line['formula']})")
        if item["impact"]["reason"]:
            print(f"  - {item['impact']['reason']}")
        for r in item["review"]["reasons"]:
            print(f"  ! {r['code']}: {r['detail']}")


def build_demo(events: list[Event], narrator: Narrator, checker: QuoteChecker) -> None:
    clients = load_clients()
    briefs: dict[str, dict] = {}
    pending = []
    all_facts: list[dict] = []
    for client in clients:
        for day in DEMO_AS_OF:
            for cadence in DEMO_CADENCES:
                brief, facts = prepare_brief(client, datetime.strptime(day, "%Y-%m-%d").date(), cadence, events, checker)
                pending.append((f"{client['id']}|{day}|{cadence}", brief))
                all_facts += facts
    narrator.prepare(all_facts)
    narrator.save()
    for key, brief in pending:
        briefs[key] = finish_brief(brief, narrator)
    payload = {
        "generatedOn": date.today().isoformat(),
        "assumptions": {"cutoffBusinessDays": config.CUTOFF_BUSINESS_DAYS, "actionWindowDays": config.ACTION_WINDOW_DAYS},
        "asOfDates": DEMO_AS_OF,
        "cadences": DEMO_CADENCES,
        "actions": [{"id": a, "label": ACTION_FILTER_LABEL[a]} for a in config.ENABLED_ACTIONS],
        "clients": [{k: c[k] for k in ("id", "name", "type", "cadence", "positions", "watchlist")} for c in clients],
        "briefs": briefs,
    }
    config.DEMO_OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {config.DEMO_OUT} ({config.DEMO_OUT.stat().st_size // 1024} KB, {len(briefs)} briefs). Narrator: {narrator.stats}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client", default="demo-pension")
    parser.add_argument("--as-of", default="2026-09-30")
    parser.add_argument("--cadence", choices=list(config.LOOKBACK_DAYS), default="weekly")
    parser.add_argument("--env-file", help="File with API_URL and STACKAI_API_KEY")
    parser.add_argument("--no-llm", action="store_true", help="Use cached summaries and the template only")
    parser.add_argument("--rights-text-dir", default=os.environ.get("BRIEFING_RIGHTS_TEXT_DIR"), help="Filing text folder, to verify quotes")
    parser.add_argument("--build-demo", action="store_true", help="Build every demo brief into the demo's data folder")
    args = parser.parse_args()

    events = load_events()
    narrator = Narrator(args.env_file, use_llm=not args.no_llm)
    checker = QuoteChecker(args.rights_text_dir)
    if args.build_demo:
        build_demo(events, narrator, checker)
        return
    client = next(c for c in load_clients() if c["id"] == args.client)
    brief = build_brief(client, datetime.strptime(args.as_of, "%Y-%m-%d").date(), args.cadence, events, narrator, checker)
    narrator.save()
    _print_brief(client, brief)


if __name__ == "__main__":
    main()
