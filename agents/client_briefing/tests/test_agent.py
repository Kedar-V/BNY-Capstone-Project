"""Behaviour the brief must never get wrong. Run from the repository root: python -m pytest agents/client_briefing/tests -q"""

from __future__ import annotations

from datetime import date

import pytest

import pandas as pd

from agents.client_briefing import agent, config, parsers
from agents.client_briefing.event_store import Event, Filing, clean_party, load_events, load_rights_events, load_tender_events
from agents.client_briefing.impact import Position, bny_cutoff, compute_impact, match_positions
from agents.client_briefing.narrate import Narrator, template_summary
from agents.client_briefing.prioritize import decide
from agents.client_briefing.verify import QuoteChecker, check_narrative, check_record


def rights_filing(acc: str, filed: date, **fields) -> Filing:
    base = {"event_status": "Commenced", "subscription_ratio": "1 right per 1 share held; 3 rights required to purchase 1 new share",
            "subscription_price": "Formula; estimated $19.93 per share", "record_date": "1/22/2026", "expiration_date": "2/18/2026",
            "security_description": "Common Shares"}
    base.update(fields)
    return Filing(acc, "rights_issue", "424B2", filed, "Test Fund", "1", ["TEST"], [], f"https://sec.test/{acc}", base,
                  {"expiration_date": [{"quote": "expires February 18, 2026", "location": "Cover"}]})


def rights_event(*filings: Filing) -> Event:
    return Event("rights-1", "rights_issue", "Test Fund rights offering", "Test Fund", None, list(filings), {"TEST": "issuer"})


def tender_filing(acc: str, filed: date, form: str = "SC TO-T", **fields) -> Filing:
    base = {"event_status": "Commenced", "offer_price": "10.00", "expiration_date": "3/10/2026 5:00 PM Eastern Time",
            "security_description": "Target Inc. common stock"}
    base.update(fields)
    return Filing(acc, "tender_offer", form, filed, "Target Inc.", "3", ["TND"], ["005-1"], f"https://sec.test/{acc}", base,
                  {"expiration_date": [{"quote": "expires March 10, 2026", "location": "Cover"}]})


def tender_event(*filings: Filing) -> Event:
    return Event("tender-1", "tender_offer", "Buyer / Target Inc. tender offer", "Target Inc.", "Buyer", list(filings), {"TND": "target"})


def merger_event(**fields) -> Event:
    base = {"event_status": "Pending", "target": "Target Inc.", "acquirer": "Buyer Corp.", "cash_consideration": "$10.00 in cash per share",
            "stock_exchange_ratio": "0.5 shares of Buyer common stock per 1 share of Target common stock", "shareholder_vote_date": "3/10/2026"}
    base.update(fields)
    f = Filing("m1", "merger", "DEFM14A", date(2026, 2, 1), "Target Inc.", "2", ["TGT"], [], "https://sec.test/m1", base, {})
    return Event("merger-1", "merger", "Buyer Corp. / Target Inc. merger", "Target Inc.", "Buyer Corp.", [f], {"TGT": "target", "BUY": "acquirer"})


# ---------------------------------------------------------------- parsing

def test_dates_are_not_invented():
    assert parsers.parse_date("1/30/2026, close of business") == date(2026, 1, 30)
    assert parsers.parse_date("January 22, 2026") == date(2026, 1, 22)
    assert parsers.parse_date("Not fixed. Filed January 20, 2026.") is None
    assert parsers.parse_date("25 days from the date rights are issued") is None


def test_ratio_never_pairs_numbers_across_clauses():
    text = "1 non-transferable Subscription Right per 1 Permian Basin Royalty Trust unit held; the number of Class A shares purchasable per right is not stated"
    assert parsers.parse_ratio(text) == {"rights_per_share": 1.0, "shares_per_right": None}


def test_one_third_stays_one_third():
    assert parsers.exact_fraction(0.3333) * 6000 == 2000
    assert parsers.exact_fraction(0.333333) * 6000 == 2000
    assert parsers.exact_fraction(0.25) * 12000 == 3000


def test_stated_decimals_are_not_rounded_to_a_nice_fraction():
    assert int(parsers.exact_fraction(0.1251) * 12000) == 1501  # Rent the Runway: not one eighth
    assert int(parsers.exact_fraction(1.145) * 1000) == 1145
    assert int(parsers.exact_fraction(0.53486) * 1000) == 534


def test_price_kinds():
    assert parsers.parse_price("$6.90 per share, equal to a 3% discount to VWAP") == {"amount": 6.9, "currency": "USD", "is_estimate": False}
    assert parsers.parse_price("95% of average price; estimated $8.69 per share")["is_estimate"] is True
    assert parsers.parse_price("the greater of $3.55 and the 15-day VWAP")["amount"] is None
    assert parsers.parse_price("C$6.74 or US$4.81 per share")["amount"] == 4.81


def test_conditional_merger_terms_are_not_calculated():
    assert parsers.parse_cash_per_share("$175.00 in cash per share, without interest") == 175.0
    assert parsers.parse_cash_per_share("USD $11.25 in cash, without interest, per eligible share") == 11.25
    assert parsers.parse_cash_per_share("If Tempus makes a Cash Election, $16.25 in cash") is None
    assert parsers.parse_cash_per_share("No cash consideration is stated") is None
    assert parsers.parse_exchange_ratio("0.2215 shares of New CommerceOne common stock per 1 share of Green Dot common stock") == 0.2215
    assert parsers.parse_exchange_ratio("For each share, a number of shares equal to 12,388,291 divided by the total") is None


def test_party_names_lose_the_description():
    assert clean_party("Fertitta Gaming Holdco, LLC, the acquiring parent; its subsidiary Empire Merger Sub") == "Fertitta Gaming Holdco, LLC"
    assert clean_party("Fox Corporation (FOX), through Falcon Merger Sub 1, Inc.") == "Fox Corporation"
    assert clean_party("Dominion Energy, Inc.; it will survive the first merger") == "Dominion Energy, Inc."
    assert clean_party("Aquarian Holdings VI L.P.; its affiliates") == "Aquarian Holdings VI L.P."
    assert clean_party("Prysmian S.p.A.; its wholly owned subsidiary") == "Prysmian S.p.A."


# ---------------------------------------------------------------- client numbers

def test_slide_example_arrowmark_numbers():
    state = rights_event(rights_filing("a", date(2026, 1, 22))).as_of(date(2026, 1, 30))
    impact = compute_impact(state, Position("TEST", "Test", 6000), "issuer")
    values = {line["label"]: line["value"] for line in impact.lines}
    assert values["Rights you would receive"] == "6,000"
    assert values["New shares you could buy"] == "Up to 2,000"
    assert values["Cash to exercise in full (estimate)"] == "≈ $39,860"
    assert values["If you do not exercise"] == "Stake about 25.0% smaller"


def test_shares_on_loan_get_no_rights():
    state = rights_event(rights_filing("a", date(2026, 1, 22))).as_of(date(2026, 1, 30))
    impact = compute_impact(state, Position("TEST", "Test", 6000, on_loan=3000), "issuer")
    assert impact.lines[0]["value"] == "3,000"
    assert any("on loan" in c for c in impact.caveats)


def test_acquirer_holders_do_not_get_target_consideration():
    state = merger_event().as_of(date(2026, 2, 10))
    target = compute_impact(state, Position("TGT", "Target", 1001), "target")
    assert [line["value"] for line in target.lines] == ["$10,010", "500"]
    acquirer = compute_impact(state, Position("BUY", "Buyer", 1000), "acquirer")
    assert not acquirer.lines and "not calculated" in acquirer.not_computed_reason


def test_offering_limit_is_flagged():
    f = rights_filing("a", date(2026, 1, 22), subscription_ratio="1 right per 1 share held; 1 right permits the purchase of 1 Unit. Subscriptions accepted for only 12,000 Units",
                      subscription_price="$1,000 per Unit", security_description="Units of preferred stock and warrants")
    state = rights_event(f).as_of(date(2026, 1, 30))
    impact = compute_impact(state, Position("TEST", "Test", 30000), "issuer")
    assert impact.offering_cap_exceeded
    assert any(r["code"] == "offering_limit" for r in check_record(state, impact, "action"))
    # The impossible number is never shown, even if a reviewer clears the item
    shown = " ".join(line["value"] for line in impact.lines)
    assert "30,000,000" not in shown and "Prorated" in shown


@pytest.mark.parametrize("text, kind, key, value", [
    ("8.85", "fixed", "amount", 8.85),
    ("$30.00 per share, net to the seller in cash", "fixed", "amount", 30.0),
    ("80.00 to 92.00", "range", "low", 80.0),
    ("$115.00 cash plus one contingent value right per common share", "cash_plus", "amount", 115.0),
    ("Net asset value per Share as of March 31, 2026", "formula", None, None),
    ("99% of NAV per Share", "formula", None, None),
    ("One ordinary share of Cadeler plc for each share", "noncash", None, None),
    ("5.5 newly issued shares of Series A Common Stock", "noncash", None, None),
])
def test_tender_price_kinds(text, kind, key, value):
    price = parsers.parse_tender_price(text)
    assert price["kind"] == kind
    if key:
        assert price[key] == value


@pytest.mark.parametrize("text, kind", [
    ("Warner Bros. Discovery, Inc. Series A Common Stock", "shares"),
    ("Preferred Income Fund common shares of beneficial interest", "shares"),
    ("Dow 30 Option Income Fund common shares", "shares"),
    ("iQIYI 4.625% convertible senior notes due 2030", "notes"),
    ("Enzon Pharmaceuticals, Inc. Series C Non-Convertible Redeemable Preferred Stock", "preferred"),
    ("Lincoln National Corporation depositary shares", "preferred"),
    ("Eligible options to purchase common stock", "options"),
    ("American depositary shares of Example Ltd.", "shares"),
])
def test_tender_security_kind(text, kind):
    assert parsers.tender_security(text) == kind


def test_tender_cash_assumes_every_share_is_accepted():
    state = tender_event(tender_filing("t1", date(2026, 2, 1))).as_of(date(2026, 2, 10))
    lines = {l["label"]: l["value"] for l in compute_impact(state, Position("TND", "Target", 1000), "target").lines}
    assert lines == {"Shares you could tender": "1,000", "Cash if all are accepted": "$10,000"}


def test_tender_shares_on_loan_are_excluded_and_flagged():
    state = tender_event(tender_filing("t1", date(2026, 2, 1))).as_of(date(2026, 2, 10))
    impact = compute_impact(state, Position("TND", "Target", 1000, on_loan=200), "target")
    assert impact.lines[0]["value"] == "800"
    assert impact.lines[1]["value"] == "$8,000"
    assert any("must be recalled" in c for c in impact.caveats)


def test_an_exchange_offer_is_not_described_as_a_buyback():
    self_offer = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="One share of NewCo plc for each share"))
    self_offer.counterparty = None
    assert "exchange offer" in agent._headline(self_offer.as_of(date(2026, 2, 10)), "target")
    cash = tender_event(tender_filing("t1", date(2026, 2, 1)))
    cash.counterparty = None
    assert "buy back" in agent._headline(cash.as_of(date(2026, 2, 10)), "target")


def test_tender_price_range_shows_both_ends():
    state = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="80.00 to 92.00")).as_of(date(2026, 2, 10))
    impact = compute_impact(state, Position("TND", "Target", 100), "target")
    assert impact.lines[1]["value"] == "$8,000 to $9,200"
    assert any("auction" in c for c in impact.caveats)


def test_tender_formula_price_gets_no_cash_figure():
    state = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="99% of net asset value")).as_of(date(2026, 2, 10))
    impact = compute_impact(state, Position("TND", "Target", 100), "target")
    assert [l["label"] for l in impact.lines] == ["Shares you could tender"]
    assert any("formula" in c for c in impact.caveats)


def test_tender_contingent_right_is_disclosed_not_valued():
    state = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="$25.00 in cash plus one contingent value right")).as_of(date(2026, 2, 10))
    impact = compute_impact(state, Position("TND", "Target", 100), "target")
    assert impact.lines[1]["value"] == "$2,500"
    assert any("contingent right" in c for c in impact.caveats)


def test_tender_limit_is_flagged_unless_the_filing_says_none():
    limited = tender_event(tender_filing("t1", date(2026, 2, 1), proration_terms="If more than 650000 shares are tendered, pro rata")).as_of(date(2026, 2, 10))
    assert any("fewer shares" in c for c in compute_impact(limited, Position("TND", "T", 100), "target").caveats)
    unlimited = tender_event(tender_filing("t1", date(2026, 2, 1), proration_terms="No proration applies")).as_of(date(2026, 2, 10))
    assert not any("fewer shares" in c for c in compute_impact(unlimited, Position("TND", "T", 100), "target").caveats)


def test_tender_offer_tiers_and_close():
    event = tender_event(tender_filing("t1", date(2026, 2, 1)))
    assert decide(event.as_of(date(2026, 3, 1)), "target", 7).tier == "action"
    assert decide(event.as_of(date(2026, 3, 1)), "target", 7, watch_only=True).tier != "action"
    assert decide(event.as_of(date(2026, 2, 1)), "target", 7).tier == "new"
    # Expired and nothing new: out of the brief. Results filed this week: recently closed.
    assert decide(event.as_of(date(2026, 3, 20)), "target", 7) is None
    closed = tender_event(tender_filing("t1", date(2026, 2, 1)), tender_filing("t2", date(2026, 3, 12), "SC TO-T/A", event_status="Final results announced"))
    assert decide(closed.as_of(date(2026, 3, 13)), "target", 7).tier == "completed"


def test_tender_extension_is_reported_as_a_change():
    event = tender_event(tender_filing("t1", date(2026, 2, 1)), tender_filing("t2", date(2026, 3, 5), "SC TO-T/A", event_status="Extended", expiration_date="3/24/2026 5:00 PM"))
    state = event.as_of(date(2026, 3, 6))
    assert [c.key for c in state.changes] == ["expiration_date"]
    assert state.status == "extended"
    assert state.facts["expiration_date"].value == date(2026, 3, 24)


def test_tender_same_amount_described_two_ways_is_not_a_change():
    event = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="25.00"),
                         tender_filing("t2", date(2026, 2, 5), "SC TO-T/A", offer_price="$25.00 in cash plus one contingent value right"))
    assert event.as_of(date(2026, 2, 6)).changes == []


def test_later_tender_filing_without_a_number_keeps_the_stated_price():
    event = tender_event(tender_filing("t1", date(2026, 2, 1), offer_price="25.00"), tender_filing("t2", date(2026, 2, 5), "SC TO-T/A", offer_price="As described in the offer"))
    assert event.as_of(date(2026, 2, 6)).facts["offer_price"].value == {"kind": "fixed", "amount": 25.0}


def test_real_tender_events_only_reach_holders_of_the_shares():
    events = {e.id: e for e in load_tender_events()}
    for e in events.values():
        if e.ticker_roles:
            assert any(parsers.tender_security(f.fields.get("security_description")) == "shares" for f in e.filings)
    # Notes, preferred and warrant offers never match a stock position
    by_issuer = {e.issuer: e for e in events.values()}
    assert by_issuer["FuboTV Inc."].ticker_roles == {}


def test_a_new_offer_after_the_last_one_expired_is_a_new_event():
    eagle = [e for e in load_tender_events() if e.issuer.startswith("Eagle Point Institutional")]
    assert len(eagle) == 2
    assert eagle[0].filings[-1].filed < eagle[1].filings[0].filed


def test_same_day_filings_read_the_most_final_status_last():
    wbd = next(e for e in load_tender_events() if "WBD" in e.ticker_roles)
    assert wbd.as_of(date(2026, 2, 27)).status == "terminated"


def test_rights_can_be_switched_off():
    actions = {e.action for e in load_events(("merger", "tender_offer"))}
    assert actions == {"merger", "tender_offer"}


def test_the_whole_rights_run_is_read():
    assert sum(len(e.filings) for e in load_rights_events()) == pd.read_csv(config.RIGHTS_CSV).accession_number.nunique()


def test_bny_cutoff_skips_weekends():
    assert bny_cutoff(date(2026, 2, 18)) == date(2026, 2, 13)
    assert bny_cutoff(date(2026, 10, 14)) == date(2026, 10, 9)


# ---------------------------------------------------------------- priority

def test_tiers():
    e = rights_event(rights_filing("a", date(2026, 1, 22)))
    assert decide(e.as_of(date(2026, 2, 5)), "issuer", 7).tier == "action"
    assert decide(e.as_of(date(2026, 1, 25)), "issuer", 7).tier == "new"
    assert decide(e.as_of(date(2026, 2, 19)), "issuer", 7) is None  # expired and no news


def test_cutoff_passed_but_deadline_open():
    d = decide(rights_event(rights_filing("a", date(2026, 1, 22))).as_of(date(2026, 2, 16)), "issuer", 7)
    assert d.tier == "action" and d.cutoff_passed


def test_proposed_offering_is_not_yet_actionable():
    e = rights_event(rights_filing("a", date(2026, 1, 22), event_status="Proposed"))
    assert decide(e.as_of(date(2026, 2, 5)), "issuer", 7).tier == "upcoming"


def test_watchlist_never_shows_action():
    e = rights_event(rights_filing("a", date(2026, 1, 22)))
    assert decide(e.as_of(date(2026, 2, 5)), "issuer", 7, watch_only=True).tier == "upcoming"


def test_source_typo_goes_to_review_instead_of_vanishing():
    e = rights_event(rights_filing("a", date(2026, 9, 1), expiration_date="9/15/2025"))
    state = e.as_of(date(2026, 9, 30))
    d = decide(state, "issuer", 7)
    assert d is not None
    assert any(r["code"] == "date_conflict" for r in check_record(state, compute_impact(state, Position("TEST", "T", 100), "issuer"), d.tier))


# ---------------------------------------------------------------- point in time

def test_later_filings_are_invisible():
    first = rights_filing("a", date(2026, 1, 22))
    amended = rights_filing("b", date(2026, 2, 10), expiration_date="3/2/2026")
    e = rights_event(first, amended)
    assert e.as_of(date(2026, 1, 21)) is None
    before = e.as_of(date(2026, 2, 9))
    assert before.facts["expiration_date"].value == date(2026, 2, 18) and not before.changes
    after = e.as_of(date(2026, 2, 12))
    assert after.facts["expiration_date"].value == date(2026, 3, 2)
    assert [c.key for c in after.changes] == ["expiration_date"]
    assert not e.as_of(date(2026, 2, 25)).changes  # outside the weekly window


def test_later_filing_without_a_value_keeps_the_earlier_one():
    e = rights_event(rights_filing("a", date(2026, 1, 22)), rights_filing("b", date(2026, 2, 1), expiration_date="Not stated"))
    assert e.as_of(date(2026, 2, 2)).facts["expiration_date"].value == date(2026, 2, 18)


def test_formula_mention_does_not_erase_a_stated_estimate():
    e = rights_event(rights_filing("a", date(2026, 1, 22)), rights_filing("b", date(2026, 1, 28), subscription_price="92.5% of the average price"))
    state = e.as_of(date(2026, 1, 30))
    assert state.facts["price"].value["amount"] == 19.93 and not state.changes


def test_partial_ratio_is_merged_not_overwritten():
    e = rights_event(rights_filing("a", date(2026, 1, 22), subscription_ratio="1 right per 1 share held"),
                     rights_filing("b", date(2026, 1, 28), subscription_ratio="3 rights required to purchase 1 new share"))
    assert e.as_of(date(2026, 1, 30)).facts["ratio"].value == {"rights_per_share": 1.0, "shares_per_right": 0.333333}


def test_deadline_moving_earlier_goes_to_review():
    e = rights_event(rights_filing("a", date(2026, 1, 22)), rights_filing("b", date(2026, 1, 28), expiration_date="2/10/2026"))
    state = e.as_of(date(2026, 1, 30))
    reasons = check_record(state, compute_impact(state, Position("TEST", "T", 100), "issuer"), "action")
    assert any(r["code"] == "deadline_moved_earlier" for r in reasons)


# ---------------------------------------------------------------- narrative checks

FACTS = '{"impact": "≈ $39,860", "shares": "6,000", "deadline": "Feb 18, 2026"}'


def test_invented_numbers_are_rejected():
    assert check_narrative("Your 6,000 shares could cost about $39,860 by Feb 18, 2026.", FACTS) == []
    assert any("numbers not in the record" in p for p in check_narrative("You could buy $40,000 of new shares.", FACTS))


@pytest.mark.parametrize("text", ["You should exercise your rights.", "We recommend participating.", "This is an attractive price.",
                                  "Consider tendering before the deadline."])
def test_advice_is_rejected(text):
    assert any("advice" in p for p in check_narrative(text, FACTS))


def test_merger_terms_are_not_mistaken_for_advice():
    assert check_narrative("The stated consideration is not calculated for your holding.", FACTS) == []
    assert check_narrative("The financial advisor to the company is named in the filing.", FACTS) == []


@pytest.mark.parametrize("text", ["Instructions were due to BNY by Feb 18, 2026.", "The subscription deadline was Feb 18, 2026.",
                                  "The shareholder vote was Feb 18, 2026.", "The BNY cut-off has passed."])
def test_future_deadlines_are_not_described_as_past(text):
    assert any("wrong tense" in p for p in check_narrative(text, FACTS))


def test_past_tense_is_fine_once_the_cutoff_has_passed():
    facts = FACTS[:-1] + ', "cutoff_passed": true}'
    assert check_narrative("Instructions were due to BNY by Feb 18, 2026, and the BNY cut-off has passed.", facts) == []


def test_a_passed_cutoff_must_be_stated_without_contradiction():
    facts = FACTS[:-1] + ', "cutoff_passed": true}'
    assert check_narrative("The BNY cut-off of Feb 18, 2026 has passed.", facts) == []
    assert check_narrative("Instructions are due to BNY by Feb 18, 2026, and the BNY cut-off has passed.", facts)
    assert check_narrative("Your 6,000 shares would receive rights.", facts)  # the passed cut-off cannot be left out


def test_tender_cash_needs_its_condition():
    facts = '{"tender_cash": true, "x": "$10,000"}'
    assert check_narrative("Your shares would receive $10,000.", facts)
    assert not check_narrative("If all shares tendered are accepted, you would receive $10,000.", facts)
    assert not check_narrative("You could tender your shares.", facts)


def test_tender_rule_is_only_sent_for_tender_offers(monkeypatch, tmp_path):
    sent = []

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"outputs": {"out-0": '{"summary": "Text."}'}}

    import requests
    monkeypatch.setattr(requests, "post", lambda url, headers, json, timeout: sent.append(json["in-1"]) or Reply())
    n = Narrator(None, use_llm=False, cache_path=tmp_path / "c.json")
    n.url, n.key = "http://test", "k"
    n._call({"event_type": "Tender offer"}, None)
    n._call({"event_type": "Merger"}, None)
    assert "tender_cash" in sent[0]
    assert "tender_cash" not in sent[1]


@pytest.mark.parametrize("text", ["The client's 6,000 shares receive rights.", "The record lists a deadline of Feb 18, 2026."])
def test_voice_and_process_leaks_are_rejected(text):
    assert any("wrong voice" in p for p in check_narrative(text, FACTS))


def test_record_date_is_not_a_process_leak():
    assert check_narrative("Your holding on the record date of Feb 18, 2026 sets your rights.", FACTS) == []


def test_dilution_figure_is_kept_away_from_the_model():
    state = rights_event(rights_filing("a", date(2026, 1, 22))).as_of(date(2026, 2, 5))
    pos = Position("TEST", "Test", 6000)
    facts = agent._narrative_facts(state, pos, decide(state, "issuer", 7), compute_impact(state, pos, "issuer"), "issuer")
    assert facts["brief_date"] == "Feb 5, 2026"
    assert "25.0%" not in str(facts) and "39,860" in str(facts)


def test_failed_model_falls_back_to_template(tmp_path):
    facts = {"headline": "Test Fund is conducting a rights offering", "position_effect": "Rights you would receive: 6,000"}
    narrator = Narrator(use_llm=False, cache_path=tmp_path / "c.json")
    drafted = narrator.get(facts)
    assert drafted["source"] == "template" and drafted["summary"] == template_summary(facts)


FACTS_DICT = {"headline": "Test Fund is conducting a rights offering", "position_effect": "Your 6,000 eligible shares would receive 6,000 rights"}


def _scripted_narrator(tmp_path, replies):
    """A narrator whose model calls return scripted replies. An exception in the script is raised as an API error."""
    narrator = Narrator(use_llm=False, cache_path=tmp_path / "c.json")
    narrator.url, narrator.key = "https://llm.test", "not-a-real-key"
    calls = []

    def fake_call(facts, feedback):
        calls.append(feedback)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    narrator._call = fake_call
    return narrator, calls


def test_good_draft_is_used_and_cached(tmp_path):
    narrator, calls = _scripted_narrator(tmp_path, ["Your 6,000 shares receive 6,000 rights in this offering."])
    narrator.prepare([FACTS_DICT])
    drafted = narrator.get(FACTS_DICT)
    assert drafted["source"] == "llm" and len(calls) == 1
    narrator.prepare([FACTS_DICT])
    assert len(calls) == 1  # cached, so the model is not asked again


def test_rejected_draft_is_retried_with_the_problem_stated(tmp_path):
    narrator, calls = _scripted_narrator(tmp_path, ["You would pay $99,000 for 6,000 rights.", "Your 6,000 shares receive 6,000 rights."])
    narrator.prepare([FACTS_DICT])
    drafted = narrator.get(FACTS_DICT)
    assert drafted["source"] == "llm" and drafted["attempts"] == 2
    assert calls[0] is None and "99000" in calls[1]


def test_model_that_keeps_giving_advice_falls_back_to_template(tmp_path):
    narrator, _ = _scripted_narrator(tmp_path, ["You should exercise your 6,000 rights."])
    narrator.prepare([FACTS_DICT])
    drafted = narrator.get(FACTS_DICT)
    assert drafted["source"] == "template" and "should" not in drafted["summary"]


def test_api_outage_is_not_cached(tmp_path):
    narrator, _ = _scripted_narrator(tmp_path, [RuntimeError("401")])
    narrator.prepare([FACTS_DICT])
    assert narrator.cache == {}
    assert narrator.get(FACTS_DICT)["source"] == "template"


def test_quote_checker(tmp_path):
    (tmp_path / "x.txt").write_text("The rights\n expire on February 18, 2026.", encoding="utf-8")
    checker = QuoteChecker(tmp_path)
    assert checker.verified("x", "rights expire on February 18") is True
    assert checker.verified("x", "rights expire on March 2") is False
    assert checker.verified("missing", "anything") is None


# ---------------------------------------------------------------- whole briefs on the real sample

@pytest.fixture(scope="module")
def real_briefs(tmp_path_factory):
    events = load_events()
    narrator = Narrator(use_llm=False, cache_path=tmp_path_factory.mktemp("n") / "c.json")
    out = []
    for client in agent.load_clients():
        for day in agent.DEMO_AS_OF:
            for cadence in agent.DEMO_CADENCES:
                as_of = date.fromisoformat(day)
                out.append((client, as_of, agent.build_brief(client, as_of, cadence, events, narrator, QuoteChecker(None))))
    return out


def test_only_the_clients_securities_appear(real_briefs):
    for client, _, brief in real_briefs:
        allowed = {p["ticker"] for p in client["positions"]} | {w["ticker"] for w in client["watchlist"]}
        assert all(i["ticker"] in allowed for i in brief["items"])


def test_no_filing_from_the_future(real_briefs):
    for _, as_of, brief in real_briefs:
        assert all(s["filed"] <= as_of.isoformat() for i in brief["items"] for s in i["sources"])


def test_action_items_have_a_future_deadline(real_briefs):
    for _, as_of, brief in real_briefs:
        for i in brief["items"]:
            if i["tier"] == "action":
                assert i["deadline"]["date"] >= as_of.isoformat() and i["cutoff"]["date"] < i["deadline"]["date"]


def test_every_action_item_can_be_traced_to_a_filing(real_briefs):
    for _, _, brief in real_briefs:
        for i in brief["items"]:
            assert i["sources"] and all(s["url"].startswith("https://www.sec.gov/") for s in i["sources"])


def test_each_position_appears_once_per_event(real_briefs):
    for _, _, brief in real_briefs:
        ids = [i["id"] for i in brief["items"]]
        assert len(ids) == len(set(ids))
