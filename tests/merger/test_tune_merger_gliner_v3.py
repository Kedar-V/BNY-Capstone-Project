from scripts.tune_merger_gliner_v3 import select, evaluate


def mention(value, score, quote=""):
    return {"value": value, "score": score, "source_quote": quote}


def test_target_consensus_prefers_repeated_full_organization():
    values = [
        mention("Parent", 0.93),
        mention("Target Technologies Inc.", 0.82),
        mention("Target Technologies Inc.", 0.81),
    ]
    assert select(values, "target")["value"] == "Target Technologies Inc."


def test_cash_prefers_explicit_dollar_amount_over_label():
    values = [mention("Per Share Merger Consideration", 0.9), mention("$12.50", 0.55)]
    assert select(values, "cash_consideration")["value"] == "$12.50"
    assert select(values, "effective_date")["value"] == "Per Share Merger Consideration"
    assert select([mention("$360 million", 0.99)], "cash_consideration") is None


def test_reference_is_scoring_input_only():
    predictions = {"a": {"candidates": {"target": [mention("Target Technologies Inc.", 0.8)]}}}
    result = evaluate([{"accession_number": "a", "target": "Target Technologies Inc."}], predictions, {"a"}, enhanced=True)
    assert result["per_field"]["target"]["tp"] == 1
