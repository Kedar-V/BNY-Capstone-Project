"""Step 3 of the brief: decide which events make the brief and in what order. Rules only, no model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from . import config
from .event_store import EventState, Fact
from .impact import bny_cutoff

TIER_ORDER = {"action": 0, "changed": 1, "new": 2, "completed": 3, "upcoming": 4}
TIER_LABEL = {"action": "Action needed", "changed": "Terms changed", "new": "New event", "completed": "Recently closed",
              "upcoming": "On the horizon"}
CLOSED = {"completed", "terminated", "withdrawn"}


@dataclass
class KeyDate:
    kind: str  # subscription | election | vote
    label: str
    fact: Fact


@dataclass
class Decision:
    tier: str
    deadline: KeyDate | None
    cutoff: date | None
    cutoff_passed: bool
    within_lookback: bool


def rights_deadline(state: EventState) -> Fact | None:
    """The most recently filed of the two deadline fields: an extension may only update one of them."""
    options = [x for x in (state.facts.get("election_deadline"), state.facts.get("expiration_date")) if x]
    return max(options, key=lambda x: x.filed) if options else None


def offer_deadline(state: EventState) -> Fact | None:
    """The date an offer's acceptance period ends. Mergers have no such period."""
    if state.event.action == "rights_issue":
        return rights_deadline(state)
    return state.facts.get("expiration_date") if state.event.action == "tender_offer" else None


def implausible_deadline(state: EventState) -> bool:
    """A deadline long before the first filing is a source typo, not an expired offer."""
    fact = rights_deadline(state) if state.event.action == "rights_issue" else None
    return bool(fact and fact.value < state.first_filed - timedelta(days=45))


def next_deadline(state: EventState, role: str) -> KeyDate | None:
    """The next date the holder has to act by, if the filing gives one."""
    today = state.as_of
    f = state.facts
    if state.event.action == "rights_issue":
        fact = rights_deadline(state)
        return KeyDate("subscription", "Subscription deadline", fact) if fact and fact.value >= today else None
    if state.event.action == "tender_offer":
        fact = f.get("expiration_date")
        return KeyDate("tender", "Offer expires", fact) if fact and fact.value >= today else None
    options = []
    if f.get("election_deadline") and f["election_deadline"].value >= today:
        options.append(KeyDate("election", "Election deadline", f["election_deadline"]))
    if role == "target" and f.get("vote_date") and f["vote_date"].value >= today:
        options.append(KeyDate("vote", "Shareholder vote", f["vote_date"]))
    return min(options, key=lambda k: k.fact.value) if options else None


def _is_open(state: EventState) -> bool:
    """A proposed rights offering cannot be exercised yet."""
    return not (state.event.action == "rights_issue" and state.status == "proposed")


def decide(state: EventState, role: str, lookback_days: int, watch_only: bool = False) -> Decision | None:
    today = state.as_of
    in_window = (today - state.latest.filed).days < lookback_days
    deadline = next_deadline(state, role)
    cutoff = bny_cutoff(deadline.fact.value) if deadline else None
    cutoff_passed = bool(cutoff and cutoff < today)

    def make(tier: str) -> Decision:
        return Decision(tier, deadline, cutoff, cutoff_passed, in_window)

    if state.status in CLOSED:
        return make("completed") if in_window else None
    if not deadline and offer_deadline(state) and not implausible_deadline(state):
        # the acceptance period is over; only worth a line if there is news this period
        return make("completed") if in_window else None
    if not watch_only and deadline and _is_open(state) and (cutoff - today).days <= config.ACTION_WINDOW_DAYS:
        return make("action")
    if state.changes:
        return make("changed")
    if (today - state.first_filed).days < lookback_days:
        return make("new")
    if deadline or (today - state.latest.filed).days <= config.STALE_DAYS:
        return make("upcoming")
    return None


def sort_key(item: dict) -> tuple:
    deadline = item.get("cutoff", {}).get("date") or item.get("deadline", {}).get("date") or "9999-12-31"
    return (TIER_ORDER[item["tier"]], deadline, item["title"])
