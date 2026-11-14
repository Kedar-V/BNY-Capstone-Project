from scripts.tune_merger_gliner import choose, score


def test_consensus_only_reranks_acquirer():
    values = [
        {"value": "Wrong Holdings", "score": 0.90},
        {"value": "Right Corp", "score": 0.86},
        {"value": "Right Corp", "score": 0.85},
        {"value": "Right Corp", "score": 0.84},
    ]
    assert choose(values, field="acquirer", consensus=False)["value"] == "Wrong Holdings"
    assert choose(values, field="acquirer", consensus=True)["value"] == "Right Corp"
    assert choose(values, field="target", consensus=True)["value"] == "Wrong Holdings"


def test_score_keeps_multi_deal_reference_rows_provisional():
    predictions = {"a": {"candidates": {"acquirer": [{"value": "Right Corp", "score": 0.8}]}}}
    reference = [
        {"accession_number": "a", "acquirer": "Right Corp"},
        {"accession_number": "a", "acquirer": "Other Corp"},
    ]
    result = score(reference, predictions, {"a"}, consensus=False, threshold=0.4, bonus=0.07)
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 1
