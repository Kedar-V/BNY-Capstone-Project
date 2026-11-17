"""scripts/eval_retrieval_recall.py: evidence per policy, recall helpers, sealed protocol."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.evaluation.action_packs import TENDER_PACK
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EventContext
from src.preprocess.store import ArtifactStore

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eval_retrieval_recall.py"
COVER = (
    "ACME FUND (Name of Subject Company (Issuer)) ACME FUND (Name of Filing Person(s) (Issuer)) "
    "CLASS I SHARES OF BENEFICIAL INTEREST (Title of Class of Securities)"
)
GOLD_SECRET = "Acme Fund Class I Shares of beneficial interest"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("eval_retrieval_recall_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_stage_evidence_follows_policy(mod):
    sec = resolve_policy(TENDER_PACK, "security_description", cascade=False)
    span = {"field_hint": "security_description", "label": "security_description",
            "text": "common stock", "score": 0.9}
    stage, ev, every = mod.stage_evidence(TENDER_PACK, EventContext(spans=[span]), "security_description", sec)
    assert stage == "oneshot" and "GLINER SPANS" in ev and every == [ev]
    ctx = EventContext(spans=[span], excerpts=COVER, doc_text=COVER)
    stage, ev, every = mod.stage_evidence(TENDER_PACK, ctx, "security_description", sec)
    assert stage == "clause" and ev.startswith("EXCERPT:\n") and len(every) == 2
    # clause-only proration: empty clause ends the policy with no evidence
    pro = resolve_policy(TENDER_PACK, "proration_terms", cascade=False)
    assert mod.stage_evidence(TENDER_PACK, EventContext(spans=[span]), "proration_terms", pro)[:2] == (
        "clause", "")


def test_recall_helpers(mod):
    assert mod._span_in("Acme Fund common stock, par value $0.001", "x COMMON STOCK, PAR VALUE $0.001 y")
    assert not mod._span_in("Acme Fund common stock, par value $0.001", "common stock only")
    assert mod._absence_in("No minimum tender condition",
                           "The Offer is not conditioned upon any minimum number of Shares")
    assert not mod._absence_in("No minimum tender condition", "a minimum account balance applies")
    assert not mod._absence_in("At least a majority", "not conditioned upon any minimum number")
    ev = "EXCERPT:\n" + COVER
    assert mod._piece_in("security_description", GOLD_SECRET, ev, mod.H._party_soft_match,
                         TENDER_PACK.date_fields)
    assert not mod._piece_in("expiration_date", "May 1, 2026", "EXCERPT:\nMay 1, 2026", mod.H.soft_match,
                             TENDER_PACK.date_fields)


def test_sha_order_is_deterministic(mod):
    accs = [f"0000000001-26-{i:06d}" for i in range(30)]
    assert mod.sha_order(accs) == mod.sha_order(list(reversed(accs)))


def test_sealed_split_needs_sealed_flag_and_out(mod, tmp_path, capsys):
    assert mod.main(["--split", "holdout"]) == 2
    assert mod.main(["--split", "confirm", "--sealed"]) == 2
    out = tmp_path / "r.json"
    assert mod.main(["--split", "confirm", "--sealed", "--out", str(out), "--show-rows"]) == 2
    assert not out.exists() and not out.with_name("r.json.sealed").exists()


def _synthetic(mod, monkeypatch, tmp_path):
    root = tmp_path / "preprocess"
    store = ArtifactStore("tender", root)
    seg = store.path_root / "events" / "e1" / "segments.json"
    seg.parent.mkdir(parents=True)
    seg.write_text(json.dumps({"segments": [{"kind": "full_doc", "heading": "cover", "text": COVER}]}))
    rows = [{"accession_number": "0000000009-26-000001", "event_id": "e1",
             "security_description": GOLD_SECRET, "passages": ""}]
    monkeypatch.setattr(mod, "load_gt", lambda _p: [dict(r) for r in rows])
    monkeypatch.setattr(mod, "DEFAULT_PREPROCESS_ROOT", root)
    monkeypatch.setattr(mod, "split_accessions", lambda *a, **k: {"0000000009-26-000001"})
    return ["--fields", "security_description", "--no-temporal",
            "--eval-out", str(tmp_path / "eval"), "--documents-parquet", str(tmp_path / "none.parquet")]


def test_sealed_pass_is_aggregate_only_and_runs_once(mod, monkeypatch, tmp_path, capsys):
    common = _synthetic(mod, monkeypatch, tmp_path)
    out = tmp_path / "sealed.json"
    assert mod.main(["--split", "confirm", "--sealed", "--out", str(out), *common]) == 0
    printed = capsys.readouterr().out
    res = json.loads(out.read_text())
    assert "rows" not in res and "pattern_counts" not in res
    assert res["fields"]["security_description"]["rows_with_gold"] == 1
    assert res["fields"]["security_description"]["recall_piece"] == 1.0
    for text in (printed, out.read_text()):
        assert GOLD_SECRET.lower() not in text.lower() and "0000000009-26-000001" not in text
    assert out.with_name("sealed.json.sealed").exists()
    # second pass on the same output file is refused
    assert mod.main(["--split", "confirm", "--sealed", "--out", str(out), *common]) == 2


def test_dev_pass_reports_rows_without_gold(mod, monkeypatch, tmp_path, capsys):
    common = _synthetic(mod, monkeypatch, tmp_path)
    out = tmp_path / "dev.json"
    assert mod.main(["--split", "dev", "--out", str(out), "--pattern-counts", *common]) == 0
    res = json.loads(out.read_text())
    assert res["rows"][0]["stage"] == "clause" and "gold" not in res["rows"][0]
    counts = {(r["pattern_index"], r["distinct_filings"]) for r in res["pattern_counts"]["security_description"]}
    assert (0, 1) in counts
