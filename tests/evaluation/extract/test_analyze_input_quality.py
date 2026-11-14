"""scripts/analyze_input_quality.py on a synthetic inputs.jsonl (one call per category)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "analyze_input_quality.py"
NO_EVIDENCE = "(no rules/GLiNER/temporal evidence for this field)"


def _rec(ei, field, gold, pred, evidence):
    return {
        "request": {"pack_name": "tender", "field": field, "event_id": None,
                    "accession": f"acc{ei}#{ei}", "model": "m", "validate_enabled": False,
                    "cascade": False},
        "accession": f"acc{ei}", "ei": ei, "gold": gold, "evidence": evidence,
        "prompt": "p", "pred": pred, "pass_used": "oneshot", "validate_verdict": None,
    }


def test_analyze_input_quality_categories(tmp_path, capsys):
    spans = "GLINER SPANS:\n- hint=subject_company score=0.90 value='{}'"
    recs = [
        _rec(0, "subject_company", "", "Ghost", spans.format("Ghost")),  # gold blank
        _rec(1, "subject_company", "Acme", None, NO_EVIDENCE),  # evidence empty
        _rec(2, "subject_company", "Acme", None, spans.format("Beta")),  # not in evidence
        _rec(3, "subject_company", "Acme Corp", "Beta", spans.format("Acme Corp")),  # candidate
        _rec(4, "subject_company", "Acme", "Acme", spans.format("Acme")),  # tp: not wrong
        # strict dates: '2026' alone is not the gold date (soft_match would say it is)
        _rec(5, "expiration_date", "May 1, 2026", None,
             "TEMPORAL SPANS:\n- date='2026' label=DATE field_cues=1 window='expires May 1, 2026 at 5pm'"),
        _rec(6, "expiration_date", "May 1, 2026", "May 2, 2026",
             "TEMPORAL SPANS:\n- date='May 2, 2026' label=DATE field_cues=1 window='x'"),
        _rec(7, "proration_terms", "pro rata", None, "EXCERPT:\nshares are bought pro rata."),
        # a resumed re-run of ei=4 replaces the earlier line (now wrong: model said null)
        _rec(4, "subject_company", "Acme", None, spans.format("Acme")),
    ]
    run = tmp_path / "run"
    run.mkdir()
    (run / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("analyze_input_quality_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    totals, per_field = mod.analyze(run)
    assert dict(totals) == {
        "gold blank, model gave a value": 1,
        "evidence empty": 1,
        "answer not in evidence": 2,
        "answer in a listed candidate": 3,
        "answer only in surrounding text": 1,
    }
    assert per_field["subject_company"]["calls"] == 5
    assert per_field["subject_company"]["wrong"] == 5
    assert per_field["expiration_date"]["answer only in surrounding text"] == 1
    assert per_field["expiration_date"]["answer not in evidence"] == 1
    assert per_field["proration_terms"]["answer in a listed candidate"] == 1

    assert mod.main(["--run", str(run)]) == 0
    out = capsys.readouterr().out
    assert "8 wrong of 8" in out and "expiration_date" in out
    assert mod.main(["--run", str(tmp_path / "missing")]) == 2
