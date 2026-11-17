from __future__ import annotations

import json

import pytest

from src.evaluation.run_tracker import RunTracker


def _live(done, total):
    return {"n_done": done, "n_total": total, "n_accessions_missing_prediction": 0,
            "micro": {"precision": 0.5, "recall": 0.5, "f1": 0.5},
            "per_field": {"offer_price": {"f1": 0.25}}}


def test_heartbeats_every_n_rows_and_final(tmp_path):
    t = RunTracker(tmp_path, {"gt_path": "x"}, every=5)
    t.eval_started(0)
    for i in range(1, 13):
        t.on_row(_live(i, 12))
    lines = [json.loads(l) for l in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert [l["done"] for l in lines] == [5, 10, 12]
    assert lines[-1]["pct"] == 100.0 and lines[-1]["per_field_f1"] == {"offer_price": 0.25}


def test_stage_records_and_failure_marks_run_failed(tmp_path):
    t = RunTracker(tmp_path, {})
    with t.stage("a") as rec:
        rec["metrics"] = {"n": 1}
    with pytest.raises(RuntimeError):
        with t.stage("b"):
            raise RuntimeError("boom")
    m = json.loads((tmp_path / "run_manifest.json").read_text())
    assert [s["status"] for s in m["stages"]] == ["ok", "failed"]
    assert m["status"] == "failed" and "boom" in m["stages"][1]["error"]
