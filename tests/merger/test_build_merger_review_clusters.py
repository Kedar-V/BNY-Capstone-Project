from scripts.build_merger_review_clusters import cluster_rows, term_evidence


def test_conditional_and_formula_quotes_are_exact_source_substrings():
    text = ("The merger will become effective upon filing a certificate of merger. "
            "The Exchange Ratio is $4.58 divided by the Closing VWAP.")
    matches = term_evidence(text)
    assert {m["term"] for m in matches} == {"effective_time_context", "exchange_ratio_context"}
    assert all(text[m["start"]:m["end"]] == m["source_quote"] for m in matches)


def test_window_review_rows_leave_deal_identity_blank():
    doc = {"accession_number": "a", "filing_date": "2026-01-01", "sec_source_url": "https://example.test",
           "candidates": {"acquirer": [{"window_id": 2, "value": "Buyer Inc.", "score": .8,
                                         "source_quote": "Buyer Inc. acquired Target Corp."}],
                          "target": [{"window_id": 2, "value": "Target Corp.", "score": .7,
                                      "source_quote": "Buyer Inc. acquired Target Corp."}]}}
    rows = cluster_rows(doc)
    assert len(rows) == 1
    assert rows[0]["window_id"] == 2
    assert rows[0]["deal_id"] == ""
    assert rows[0]["acquirer_candidates"] == "Buyer Inc."
