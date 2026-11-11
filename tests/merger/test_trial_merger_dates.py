from scripts.trial_merger_dates import date_values, gated_date, meeting_candidates


def test_meeting_date_keeps_source_offsets_and_strict_tier():
    text = "The special meeting of shareholders will be held on February 26, 2026 at 10:00 a.m."
    values = meeting_candidates(text)
    assert len(values) == 1
    value = values[0]
    assert value["date_iso"] == "2026-02-26"
    assert value["selection_tier"] == "strict"
    assert text[value["date_start"]:value["date_end"]] == value["date_text"]
    assert text[value["quote_start"]:value["quote_end"]] == value["source_quote"]
    assert date_values("Meeting 2/26/2026") == {"2026-02-26"}


def test_date_gate_rejects_agreement_date_and_keeps_effective_context():
    bad_quote = "The Agreement and Plan of Merger, dated November 4, 2025, was signed."
    good_quote = "The merger effective date is February 26, 2026 after closing."
    bad_start = bad_quote.index("November")
    good_start = good_quote.index("February")
    candidates = [
        {"value": "November 4, 2025", "score": .9, "start": bad_start,
         "quote_start": 0, "source_quote": bad_quote},
        {"value": "February 26, 2026", "score": .6, "start": good_start,
         "quote_start": 0, "source_quote": good_quote},
    ]
    assert gated_date(candidates, "effective_date")["value"] == "February 26, 2026"
