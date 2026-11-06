"""Synthetic amendments with a known answer, built from real events in the extraction runs.

Each case takes a real event's first filing and adds one made-up amendment filed two days later, with a planted change
(or a planted non-change) and the tier and review codes the agent should give it. Real filings after the first are
left out, so the answer depends only on the planted amendment.

    python -m agents.amendment_impact.synthetic --seed 7 --per-type 15

Writes synthetic/cases.jsonl (the amendments) and synthetic/answer_key.csv. This tests the agent's logic, not
extraction accuracy: the planted wording is ours, written in the formats the extraction runs produce.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import replace
from datetime import date, timedelta
from typing import Callable

from events.store import Event, Filing, load_events
from events.versioning import TEXT_FIELDS, TRACKED, replay

from . import config
from .checks import add_business_days

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
STATUS_TEXT = {
    "tender_offer": {"terminated": "Terminated", "completed": "Final results announced"},
    "merger": {"terminated": "Terminated; merger agreement terminated", "completed": "Completed"},
    "rights_issue": {"terminated": "Withdrawn", "completed": "Completed"},
}
# The deadline each action's extension and moved-earlier cases change
DEADLINE = {"tender_offer": "expiration_date", "merger": "vote_date", "rights_issue": "expiration_date"}
# The consideration each action's price change moves
PRICE = {"tender_offer": "offer_price", "merger": "cash_per_share", "rights_issue": "price"}
INFO_DATE = {"tender_offer": "settlement_date", "merger": "effective_date", "rights_issue": "effective_date"}
AMENDED_FORM = {"tender_offer": None, "merger": "DEFA14A", "rights_issue": "424B3"}


def numeric(d: date, time: bool) -> str:
    return f"{d.month}/{d.day}/{d.year}" + (" 5:00 PM New York City time" if time else "")


def words(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}, at 5:00 p.m., New York City time"


def price_text(action: str, amount: float, reworded: bool = False) -> str:
    if action == "tender_offer":
        return f"${amount:.2f} per Share, net to the seller in cash, without interest" if reworded else f"{amount:.2f}"
    if action == "merger":
        return f"${amount:.2f} per share in cash, without interest" if reworded else f"${amount:.2f} in cash per share"
    return f"${amount:.2f} per Common Share subscribed" if reworded else f"${amount:.2f} per share"


def _price_amount(action: str, value) -> float | None:
    if action == "merger":
        return value
    if isinstance(value, dict) and value.get("amount") is not None and (action != "tender_offer" or value.get("kind") == "fixed"):
        return value["amount"]
    return None


class Builder:
    """Makes one synthetic amendment for an event, or returns None when the event cannot carry that change."""

    def __init__(self, event: Event) -> None:
        self.event, self.action = event, event.action
        self.first = event.filings[0]
        self.base = replay(replace(event, filings=[self.first]))[0]
        self.filed = self.first.filed + timedelta(days=2)

    def source(self, key: str) -> str:
        return TRACKED[self.action][key][0]

    def filing(self, fields: dict, quotes: dict[str, str], filed: date | None = None, n: int = 0) -> Filing:
        f = self.first
        form = AMENDED_FORM[self.action] or ((f.form.split("/")[0] + "/A") if f.form.startswith("SC TO") else "SC TO-T/A")
        return Filing(f"SYN-{self.event.id}-{n}", self.action, form, filed or self.filed, f.registrant, f.cik, f.tickers,
                      f.file_nums, f.url, fields, {k: [{"quote": q, "location": None}] for k, q in quotes.items()})

    def deadline(self) -> date | None:
        d = self.base.after.get(DEADLINE[self.action])
        return d if d and d > self.filed + timedelta(days=21) else None

    # ---------------------------------------------------------------- mutations: (fields, quotes, filed)
    def deadline_extended(self):
        d = self.deadline()
        if not d:
            return None
        new = d + timedelta(days=14)
        src, time = self.source(DEADLINE[self.action]), self.action != "merger"
        return {src: numeric(new, time)}, {src: f"The deadline has been extended to {words(new)}."}, None

    def deadline_moved_earlier(self):
        d = self.deadline()
        if not d:
            return None
        new = d - timedelta(days=5)
        src = self.source(DEADLINE[self.action])
        return {src: numeric(new, self.action != "merger")}, {src: f"The deadline is now {words(new)}."}, None

    def deadline_no_quote(self):
        out = self.deadline_extended()
        return (out[0], {}, None) if out else None

    def price_changed(self):
        """Price raised and, for a tender offer, the offer extended so it stays open 10 business days."""
        amount = _price_amount(self.action, self.base.after.get(PRICE[self.action]))
        if amount is None:
            return None
        new = round(amount + 1.0 if self.action != "rights_issue" else max(0.01, amount - 0.25), 2)
        src = self.source(PRICE[self.action])
        fields, quotes = {src: price_text(self.action, new)}, {src: f"The price has been changed to ${new:.2f} per share."}
        if self.action == "tender_offer":
            d = self.base.after.get("expiration_date")
            if not d:
                return None
            later = max(d, add_business_days(self.filed, 15))
            if later != d:
                fields["expiration_date"] = numeric(later, True)
                quotes["expiration_date"] = f"The Offer will now expire on {words(later)}."
        return fields, quotes, None

    def price_short_window(self):
        """Tender offer price raised with fewer than 10 business days left (Rule 14e-1(b))."""
        if self.action != "tender_offer":
            return None
        amount = _price_amount(self.action, self.base.after.get("offer_price"))
        d = self.base.after.get("expiration_date")
        if amount is None or not d:
            return None
        filed = d - timedelta(days=6)
        if filed <= self.first.filed:
            return None
        src = self.source("offer_price")
        return {src: price_text(self.action, amount + 1.0)}, {src: f"The price has been increased to ${amount + 1.0:.2f} per Share."}, filed

    def ratio_changed(self):
        if self.action != "merger" or self.base.after.get("exchange_ratio") is None:
            return None
        new = round(self.base.after["exchange_ratio"] + 0.05, 4)
        src = self.source("exchange_ratio")
        return ({src: f"{new:g} shares of acquirer common stock for each share of target common stock"},
                {src: f"Each share will be converted into the right to receive {new:g} shares."}, None)

    def terminated(self):
        if self.base.status_after in {"terminated", "withdrawn", "completed"}:
            return None
        text = STATUS_TEXT[self.action]["terminated"]
        return {"event_status": text}, {"event_status": f"The offer has been {text.split(';')[0].lower()}."}, None

    def completed(self):
        if self.base.status_after in {"terminated", "withdrawn", "completed"}:
            return None
        text = STATUS_TEXT[self.action]["completed"]
        return {"event_status": text}, {"event_status": "The transaction has been completed."}, None

    def date_set(self):
        """A settlement, closing or issuance date is stated for the first time."""
        key = INFO_DATE[self.action]
        if self.base.after.get(key):
            return None
        new = self.filed + timedelta(days=30)
        src = self.source(key)
        return {src: numeric(new, False)}, {src: f"Payment and delivery are expected on {words(new)}."}, None

    def no_change(self):
        """Restates the terms already known, word for word."""
        fields = {src: self.first.fields[src] for key, (src, _) in TRACKED[self.action].items()
                  if key in self.base.after and src in self.first.fields}
        if not fields:
            return None
        return fields, {k: self.first.fields[k] for k in fields}, None

    def same_value_reworded(self):
        """The deadline and price written another way: no change."""
        fields, quotes = {}, {}
        d = self.base.after.get(DEADLINE[self.action])
        if d:
            fields[self.source(DEADLINE[self.action])] = words(d)
        price = self.base.after.get(PRICE[self.action])
        amount = _price_amount(self.action, price)
        if amount is not None:
            text = price_text(self.action, amount, reworded=True)
            if isinstance(price, dict) and price.get("is_estimate"):
                # An estimated formula price stays an estimate; stating it as fixed would be a real change
                text = f"Estimated Subscription Price: ${amount:.2f} per Common Share; the final price may differ"
            fields[self.source(PRICE[self.action])] = text
        if not fields:
            return None
        return fields, {k: v for k, v in fields.items()}, None

    def _text_field(self) -> str | None:
        options = [n for n in TEXT_FIELDS[self.action] if len(self.base.text_after.get(n, "").split()) >= 8]
        return options[0] if options else None

    def text_reworded(self):
        """Same descriptive wording with case, punctuation and item order changed."""
        name = self._text_field()
        if not name:
            return None
        items = [x.strip() for x in self.base.text_after[name].split("|")]
        new = "; ".join(reversed(items)).upper().replace(",", "") + "."
        return {name: new}, {name: new}, None

    def text_changed(self):
        """Descriptive wording replaced with a materially different term."""
        name = self._text_field()
        if not name:
            return None
        new = ("Holders may now elect to receive shares of a newly issued series of preferred stock instead of cash, "
               "and the financing condition has been removed.")
        return {name: new}, {name: new}, None


# type -> (mutation, expected tier with rules only, expected tier with the LLM, expected review codes)
CASE_TYPES: dict[str, tuple[Callable, str, str, list[str]]] = {
    "deadline_extended": (Builder.deadline_extended, "action", "action", []),
    "deadline_moved_earlier": (Builder.deadline_moved_earlier, "action", "action", ["deadline_moved_earlier"]),
    "deadline_no_quote": (Builder.deadline_no_quote, "action", "action", ["no_evidence"]),
    "price_changed": (Builder.price_changed, "action", "action", []),
    "price_short_window": (Builder.price_short_window, "action", "action", ["price_change_window"]),
    "ratio_changed": (Builder.ratio_changed, "action", "action", []),
    "terminated": (Builder.terminated, "action", "action", []),
    "completed": (Builder.completed, "informational", "informational", []),
    "date_set": (Builder.date_set, "informational", "informational", []),
    "no_change": (Builder.no_change, "log_only", "log_only", []),
    "same_value_reworded": (Builder.same_value_reworded, "log_only", "log_only", []),
    "text_reworded": (Builder.text_reworded, "log_only", "log_only", []),
    "text_changed": (Builder.text_changed, "needs_review", "action", ["text_not_assessed"]),
}


def build_cases(events: list[Event], per_type: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    for action in ["tender_offer", "merger", "rights_issue"]:
        pool = [e for e in events if e.action == action]
        rng.shuffle(pool)
        builders = [Builder(e) for e in pool]
        for ctype, (mutate, tier_rules, tier_llm, codes) in CASE_TYPES.items():
            made = 0
            for b in builders:
                if made == per_type:
                    break
                out = mutate(b)
                if out is None:
                    continue
                fields, quotes, filed = out
                syn = b.filing(fields, quotes, filed, n=len(cases))
                cases.append({"case_id": f"C{len(cases) + 1:04d}", "type": ctype, "action": action, "event_id": b.event.id,
                              "base_accession": b.first.accession, "filing": syn, "expected_tier": tier_rules,
                              "expected_tier_llm": tier_llm, "expected_review": codes})
                made += 1
    return cases


def case_event(events_by_id: dict[str, Event], case: dict) -> Event:
    e = events_by_id[case["event_id"]]
    return replace(e, filings=[e.filings[0], case["filing"]])


def _filing_json(f: Filing) -> dict:
    return {"accession": f.accession, "form": f.form, "filed": f.filed.isoformat(), "fields": f.fields, "passages": f.passages}


def save(cases: list[dict], out_dir=config.SYNTHETIC_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "cases.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "filing": _filing_json(c["filing"])}, ensure_ascii=False) + "\n")
    with open(out_dir / "answer_key.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "type", "action", "event_id", "expected_tier", "expected_tier_llm", "expected_review"])
        for c in cases:
            w.writerow([c["case_id"], c["type"], c["action"], c["event_id"], c["expected_tier"], c["expected_tier_llm"],
                        "; ".join(c["expected_review"])])


def load(events: list[Event], path=config.SYNTHETIC_DIR / "cases.jsonl") -> list[dict]:
    """Read saved cases back, attaching each planted filing to its event's first filing."""
    by_id = {e.id: e for e in events}
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        base = by_id[c["event_id"]].filings[0]
        f = c["filing"]
        c["filing"] = Filing(f["accession"], c["action"], f["form"], date.fromisoformat(f["filed"]), base.registrant, base.cik,
                             base.tickers, base.file_nums, base.url, f["fields"], f["passages"])
        cases.append(c)
    return cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--per-type", type=int, default=15, help="cases per case type and action, where enough events allow")
    args = ap.parse_args()
    cases = build_cases(load_events(), args.per_type, args.seed)
    save(cases)
    counts: dict[str, dict[str, int]] = {}
    for c in cases:
        counts.setdefault(c["type"], {}).setdefault(c["action"], 0)
        counts[c["type"]][c["action"]] += 1
    print(f"{len(cases)} synthetic amendments written to {config.SYNTHETIC_DIR}")
    for t, by in counts.items():
        print(f"  {t:<24}" + "  ".join(f"{a}={n}" for a, n in by.items()))


if __name__ == "__main__":
    main()
