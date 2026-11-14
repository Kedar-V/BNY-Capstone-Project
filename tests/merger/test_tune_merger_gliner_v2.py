from scripts.tune_merger_gliner_v2 import select, evaluate


def mention(value, score, quote=""):
    return {"value": value, "score": score, "source_quote": quote}


def test_role_context_and_full_name_can_beat_adviser_and_generic_role():
    values = [
        mention("Goldman Sachs & Co. LLC", 0.94, "provides advisory and underwriting services"),
        mention("Parent", 0.86, "Parent entered into the merger agreement"),
        mention("Example Acquisition Inc.", 0.77, "Example Acquisition Inc. entered into the agreement"),
        mention("Example Acquisition Inc.", 0.75, "Example Acquisition Inc. will acquire shares"),
    ]
    assert select(values, "acquirer", role_aware=False)["value"] == "Goldman Sachs & Co. LLC"
    assert select(values, "acquirer", role_aware=True)["value"] == "Example Acquisition Inc."
    assert select(values, "target", role_aware=True)["value"] == "Goldman Sachs & Co. LLC"


def test_provisional_score_counts_wrong_present_value_as_fp_and_fn():
    predictions = {"a": {"candidates": {"acquirer": [mention("Wrong Corp", 0.8)]}}}
    reference = [{"accession_number": "a", "acquirer": "Right Corp"}]
    result = evaluate(reference, predictions, {"a"}, role_aware=True)["per_field"]["acquirer"]
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)
