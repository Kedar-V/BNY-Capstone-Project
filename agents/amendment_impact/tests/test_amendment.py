"""Rules of the amendment impact agent, on small hand-made events.

    python -m pytest agents/amendment_impact/tests -q
"""

from __future__ import annotations

from datetime import date

import pytest

from agents.amendment_impact.agent import assess
from agents.amendment_impact.checks import add_business_days
from agents.amendment_impact.holders import affected
from agents.amendment_impact.llm import TextJudge
from events.store import Event, Filing
from events.versioning import replay, text_similarity

CLIENTS = [{"id": "c1", "name": "Client One", "positions": [{"ticker": "TGT", "name": "Target", "shares": 1000},
                                                            {"ticker": "ACQ", "name": "Acquirer", "shares": 500}],
            "watchlist": []}]


def filing(n: int, filed: date, fields: dict, action: str = "tender_offer", quotes: bool = True) -> Filing:
    passages = {k: [{"quote": f"quote for {k}", "location": ""}] for k in fields} if quotes else {}
    return Filing(f"ACC-{n}", action, "SC TO-T/A" if n else "SC TO-T", filed, "Target Inc.", "1", ["TGT"], [], "url", fields, passages)


def event(filings: list[Filing], action: str = "tender_offer", roles=None) -> Event:
    return Event("e1", action, "Target tender offer", "Target Inc.", None, filings, roles or {"TGT": "target"})


def last(e: Event, **kw) -> dict:
    return assess(e, replay(e)[-1], CLIENTS, **kw)


BASE = {"offer_price": "25.00", "expiration_date": "11/20/2026 5:00 PM New York City time", "event_status": "Commenced"}


def test_extension_is_action_needed():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 11, 10), {"expiration_date": "12/4/2026"})])
    out = last(e)
    assert out["tier"] == "action" and out["review"] == []
    assert out["notice"]["lines"] == ["Expiration: Nov 20, 2026 → Dec 4, 2026"]
    assert out["notice"]["recipients"] == ["Client One"]


def test_a_blank_in_the_amendment_does_not_erase_the_earlier_value():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 10, 5), {"event_status": "Commenced"})])
    out = last(e)
    assert out["tier"] == "log_only" and out["changes"] == []


def test_same_price_written_another_way_is_not_a_change():
    e = event([filing(0, date(2026, 10, 1), BASE),
               filing(1, date(2026, 10, 5), {"offer_price": "$25.00 per Share, net to the seller in cash, without interest",
                                             "expiration_date": "November 20, 2026, at 5:00 p.m."})])
    assert last(e)["tier"] == "log_only"


def test_second_filing_of_the_same_extension_is_log_only():
    """A TO-T/A and a 14D-9/A often report the same extension: only the first notifies."""
    ext = {"expiration_date": "12/4/2026"}
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 11, 10), ext), filing(2, date(2026, 11, 10), ext)])
    versions = replay(e)
    assert [assess(e, v, CLIENTS)["tier"] for v in versions[1:]] == ["action", "log_only"]


def test_price_change_needs_ten_business_days():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 11, 16), {"offer_price": "27.00"})])
    out = last(e)
    assert out["tier"] == "action" and [r["code"] for r in out["review"]] == ["price_change_window"]
    assert add_business_days(date(2026, 11, 16), 10) == date(2026, 11, 30)


def test_price_change_with_enough_time_passes():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 10, 5), {"offer_price": "27.00"})])
    assert last(e)["review"] == []


def test_deadline_moved_earlier_and_into_the_past_go_to_review():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 10, 5), {"expiration_date": "9/30/2026"})])
    assert {r["code"] for r in last(e)["review"]} == {"deadline_moved_earlier", "deadline_in_past"}


def test_change_without_a_quote_goes_to_review():
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 10, 5), {"expiration_date": "12/4/2026"}, quotes=False)])
    assert [r["code"] for r in last(e)["review"]] == ["no_evidence"]


@pytest.mark.parametrize("status, tier", [("Terminated", "action"), ("Final results announced", "informational"),
                                          ("Amended", "log_only")])
def test_status_changes(status, tier):
    e = event([filing(0, date(2026, 10, 1), BASE), filing(1, date(2026, 10, 5), {"event_status": status})])
    assert last(e)["tier"] == tier


def test_rights_estimate_becoming_a_fixed_price_is_a_change():
    base = {"subscription_price": "Formula price. Estimated Subscription Price: $9.90 per Common Share", "expiration_date": "10/7/2026"}
    e = event([filing(0, date(2026, 9, 1), base, "rights_issue"),
               filing(1, date(2026, 10, 8), {"subscription_price": "$9.90 per Common Share"}, "rights_issue")], "rights_issue")
    assert last(e)["tier"] == "action"


TEXT = "Tender all or some Shares | Conditional tenders are permitted | Odd lots receive priority over other tenders"


def test_reworded_text_is_log_only_and_new_text_needs_review():
    assert text_similarity(TEXT, "ODD LOTS RECEIVE PRIORITY OVER OTHER TENDERS; conditional tenders are permitted; tender all or some shares") == 1
    same = event([filing(0, date(2026, 10, 1), {**BASE, "available_options": TEXT}),
                  filing(1, date(2026, 10, 5), {"available_options": TEXT.upper().replace("|", ";")})])
    assert last(same)["tier"] == "log_only"
    new = event([filing(0, date(2026, 10, 1), {**BASE, "available_options": TEXT}),
                 filing(1, date(2026, 10, 5), {"available_options": "Holders may now elect to receive preferred stock instead of cash"})])
    out = last(new)
    assert out["tier"] == "needs_review" and [r["code"] for r in out["review"]] == ["text_not_assessed"]


def _judge_with(answer: dict, previous: str, current: str, tmp_path) -> TextJudge:
    judge = TextJudge(use_llm=False, cache_path=tmp_path / "cache.json")
    judge.cache[judge._hash(TextJudge.record("tender_offer", "available_options", previous, current))] = answer
    return judge


def test_llm_decides_text_changes_only_with_a_real_quote(tmp_path):
    new_text = "Holders may now elect to receive preferred stock instead of cash"
    e = event([filing(0, date(2026, 10, 1), {**BASE, "available_options": TEXT}),
               filing(1, date(2026, 10, 5), {"available_options": new_text})])
    good = _judge_with({"material": True, "reason": "new stock option", "quote": "receive preferred stock"}, TEXT, new_text, tmp_path)
    assert last(e, judge=good)["tier"] == "action"
    made_up = _judge_with({"material": True, "reason": "x", "quote": "a quote that is not there"}, TEXT, new_text, tmp_path)
    assert last(e, judge=made_up)["tier"] == "needs_review"
    no_effect = _judge_with({"material": False, "reason": "same terms", "quote": "instead of cash"}, TEXT, new_text, tmp_path)
    assert last(e, judge=no_effect)["tier"] == "log_only"


def test_acquirer_holders_do_not_get_the_targets_consideration_change():
    e = event([], "merger", roles={"TGT": "target", "ACQ": "acquirer"})
    assert {h["ticker"] for h in affected(e, {"cash_per_share"}, CLIENTS)} == {"TGT"}
    assert {h["ticker"] for h in affected(e, {"vote_date"}, CLIENTS)} == {"TGT", "ACQ"}


def test_shared_store_matches_the_briefing_store():
    """events/ is a copy of the briefing's store: both must build the same events from the extraction runs."""
    from agents.client_briefing import event_store
    from events.store import load_events

    ours = {e.id: [f.accession for f in e.filings] for e in load_events()}
    theirs = {e.id: [f.accession for f in e.filings] for e in event_store.load_events()}
    assert ours == theirs
