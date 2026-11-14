"""CLI contract of scripts/eval_unified_field_graph.py (graph-backed eval harness).

``main([...])`` runs in-process with ``make_backend`` patched to ``EchoFirstBackend``.
The expected JSON keys are derived from the frozen 2026-11-13 harness snapshot's
``main`` (AST), so the new harness keeps the on-disk summary/details/checkpoint shape.

Legs
- synthetic (always runs): ``load_gt`` patched to in-memory rows, preprocess root and
  ``--out`` in tmp; covers resume and duplicate accessions with different passages.
- real holdout (tender, merger): skipped when GT csv / preprocess artifacts are absent.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fakes import EchoFirstBackend

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eval_unified_field_graph.py"
SNAPSHOT = Path(__file__).resolve().parent / "fixtures/legacy_harness_snapshot_20261113.py.txt"
RESULT_KEYS = {"pred", "pass_used", "n_evidence_chars", "n_rules", "raw_llm"}
PING_USER = 'Return {"ping": true}'


# --- expected shapes from the frozen snapshot --------------------------------------


def _snapshot_dict_keys() -> dict[str, set[str]]:
    """String keys of the dict literals in the snapshot's ``main`` (by role)."""
    if not SNAPSHOT.exists():
        pytest.skip(f"frozen harness snapshot missing: {SNAPSHOT}")
    tree = ast.parse(SNAPSHOT.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    dicts: list[set[str]] = []
    for node in ast.walk(main):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if keys:
                dicts.append(keys)

    def pick(marker: str, also: str) -> set[str]:
        hits = [d for d in dicts if marker in d and also in d]
        assert len(hits) == 1, (marker, also, hits)
        return hits[0]

    return {
        "summary": pick("baselines", "pass_counts"),
        "row": pick("n_spans", "n_excerpt_chars"),
        "field": pick("outcome", "gold"),
        "error_result": pick("pass_used", "raw_llm"),
        "checkpoint": pick("ei", "result"),
    }


def test_snapshot_shapes_are_what_we_expect():
    keys = _snapshot_dict_keys()
    assert keys["error_result"] == RESULT_KEYS
    assert {"micro", "per_field", "pass_counts", "baselines", "mode"} <= keys["summary"]
    assert keys["row"] == {"accession", "event_id", "n_spans", "n_excerpt_chars", "fields"}


# --- harness loading -----------------------------------------------------------------


def _load_harness():
    if not SCRIPT.exists():
        pytest.fail(f"harness script missing: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("eval_unified_field_graph_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_does_not_load_heavy_models():
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('h', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "heavy = [k for k in ('transformers', 'torch', 'eval_temporal_tagger_dates', 'pandas')"
        " if k in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"heavy modules loaded at import: {out.stdout.strip()}"


class _Backends:
    """``make_backend`` stub: a fresh EchoFirstBackend per call, all kept for inspection."""

    def __init__(self) -> None:
        self.made: list[EchoFirstBackend] = []

    def __call__(self, name: str) -> EchoFirstBackend:
        b = EchoFirstBackend("plain")
        self.made.append(b)
        return b

    def extract_calls(self, i: int = -1) -> list[tuple[str, str]]:
        return [c for c in self.made[i].calls if c[1] != PING_USER]


@pytest.fixture
def harness(monkeypatch):
    mod = _load_harness()
    backends = _Backends()
    monkeypatch.setattr(mod, "make_backend", backends)
    return mod, backends


def _run_dir(out: Path, run: str) -> Path:
    return out / "experiments" / "runs" / run


def _read(out: Path, run: str):
    d = _run_dir(out, run)
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    details = json.loads((d / "details.json").read_text(encoding="utf-8"))
    ckpt = [
        json.loads(ln)
        for ln in (d / "checkpoint.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    with (d / "per_field.csv").open(newline="", encoding="utf-8") as f:
        per_field_rows = list(csv.DictReader(f))
    return summary, details, ckpt, per_field_rows


def _assert_shape(summary, details, ckpt, per_field_rows, *, n_rows: int):
    keys = _snapshot_dict_keys()
    assert set(summary) == keys["summary"]
    assert summary["n_rows"] == n_rows
    fields = summary["fields"]
    assert set(summary["per_field"]) == set(fields)
    assert [r["field"] for r in per_field_rows] == fields
    assert len(details) == n_rows
    for row in details:
        assert set(row) == keys["row"]
        assert "#" not in row["accession"], "context key leaked into output accession"
        assert set(row["fields"]) == set(fields)
        for field, fd in row["fields"].items():
            assert set(fd) == keys["field"] | RESULT_KEYS, (field, set(fd))
            assert isinstance(fd["pass_used"], str) and fd["pass_used"], (row["accession"], field)
    assert sum(summary["pass_counts"].values()) == n_rows * len(fields)
    assert len(ckpt) == n_rows * len(fields)
    for rec in ckpt:
        assert set(rec) == keys["checkpoint"]
        assert set(rec["result"]) == RESULT_KEYS
        assert "#" not in rec["accession"]


# --- synthetic leg (always runs) -----------------------------------------------------


def _passages(**quotes: str) -> str:
    return json.dumps({k: [{"quote": v}] for k, v in quotes.items()})


TENDER_ROWS = [
    {
        "accession_number": "0000000001-26-000001",
        "event_id": "",
        "subject_company": "Acme Corp",
        "bidder": "Bidco Inc",
        "offer_price": "$10.00",
        "expiration_date": "January 5, 2026",
        "passages": _passages(
            subject_company="Acme Corp",
            bidder="Bidco Inc",
            offer_price="$10.00 per share in cash",
            expiration_date="January 5, 2026",
            proration_terms="If more than the maximum number of shares are tendered, "
            "we will purchase shares on a pro rata basis.",
        ),
    },
    {
        "accession_number": "0000000001-26-000002",
        "event_id": "",
        "subject_company": "Beta Holdings",
        "offer_price": "$4.25",
        "passages": _passages(subject_company="Beta Holdings", offer_price="$4.25"),
    },
    {
        "accession_number": "0000000001-26-000003",
        "event_id": "",
        "subject_company": "Gamma",
        "passages": _passages(subject_company="Gamma"),
    },
]

# Two rows share an accession but carry different passages (real merger GT does this).
MERGER_ROWS = [
    {
        "accession_number": "0000000002-26-000001",
        "acquirer": "Parent Co",
        "target": "Target Inc",
        "passages": _passages(acquirer="Parent Co", target="Target Inc"),
    },
    {
        "accession_number": "0000000002-26-000001",
        "acquirer": "Other Parent LLC",
        "target": "Target Inc",
        "passages": _passages(
            acquirer="Other Parent LLC",
            target="Target Inc",
            cash_consideration="$12.00 in cash per share",
        ),
    },
    {
        "accession_number": "0000000002-26-000009",
        "target": "Zeta",
        "passages": _passages(target="Zeta"),
    },
]


def _synthetic_argv(out: Path, pack: str, run: str, *extra: str) -> list[str]:
    return [
        "--pack", pack,
        "--backend", "orin",
        "--model", "echo-model",
        "--split", "holdout",
        "--limit", "2",
        "--no-temporal",
        "--out", str(out),
        "--gt", str(out / "unused_gt.csv"),
        "--documents-parquet", str(out / "no_documents.parquet"),
        "--run-name", run,
        "--concurrency", "2",
        *extra,
    ]


@pytest.fixture
def synthetic(harness, monkeypatch, tmp_path):
    mod, backends = harness
    monkeypatch.setattr(mod, "DEFAULT_PREPROCESS_ROOT", tmp_path / "preprocess")

    def use_rows(rows):
        monkeypatch.setattr(mod, "load_gt", lambda _p: [dict(r) for r in rows])

    return mod, backends, use_rows, tmp_path / "out"


def test_synthetic_tender_run_shape_and_resume(synthetic):
    mod, backends, use_rows, out = synthetic
    use_rows(TENDER_ROWS)
    argv = _synthetic_argv(out, "tender", "graph_cli_tender")

    assert mod.main(argv) == 0
    summary, details, ckpt, pf = _read(out, "graph_cli_tender")
    _assert_shape(summary, details, ckpt, pf, n_rows=2)
    assert summary["mode"] == "cascade_v2" and summary["validate"] is True
    first_calls = backends.extract_calls(0)
    assert first_calls, "the stub backend was never asked to extract"
    used = {fd["pass_used"] for row in details for fd in row["fields"].values()}
    assert "error" not in used, used
    assert details[0]["accession"] == TENDER_ROWS[0]["accession_number"]
    assert details[0]["fields"]["subject_company"]["pred"] == "Acme Corp"

    # Full resume: every field-call is checkpointed -> only the ping hits the backend.
    assert mod.main(argv) == 0
    assert backends.extract_calls(1) == []
    summary2, details2, ckpt2, _ = _read(out, "graph_cli_tender")
    assert len(ckpt2) == len(ckpt)
    assert {k: v for k, v in summary2.items() if k != "wall_seconds"} == {
        k: v for k, v in summary.items() if k != "wall_seconds"
    }
    assert details2 == details

    # Partial resume: drop the last 5 checkpoint lines -> exactly those jobs rerun.
    ckpt_path = _run_dir(out, "graph_cli_tender") / "checkpoint.jsonl"
    lines = ckpt_path.read_text(encoding="utf-8").splitlines()
    ckpt_path.write_text("\n".join(lines[:-5]) + "\n", encoding="utf-8")
    dropped = {(json.loads(ln)["ei"], json.loads(ln)["field"]) for ln in lines[-5:]}
    assert mod.main(argv) == 0
    rerun = backends.extract_calls(2)
    assert rerun, "dropped field-calls were not re-run"
    _, details3, ckpt3, _ = _read(out, "graph_cli_tender")
    assert len(ckpt3) == len(lines)
    assert {(r["ei"], r["field"]) for r in ckpt3[-5:]} == dropped
    assert details3 == details


def test_synthetic_oneshot_novalidate_mode(synthetic):
    mod, backends, use_rows, out = synthetic
    use_rows(TENDER_ROWS)
    argv = _synthetic_argv(
        out, "tender", "graph_cli_oneshot", "--no-cascade", "--no-validate",
        "--fields", "subject_company,offer_price,proration_terms",
    )
    assert mod.main(argv) == 0
    summary, details, ckpt, pf = _read(out, "graph_cli_oneshot")
    _assert_shape(summary, details, ckpt, pf, n_rows=2)
    assert summary["mode"] == "oneshot_v1" and summary["validate"] is False
    assert summary["fields"] == ["subject_company", "offer_price", "proration_terms"]
    used = {fd["pass_used"] for row in details for fd in row["fields"].values()}
    assert used <= {"oneshot", "clause", "clause_null", "clause_miss"}, used
    assert not any(u.startswith("Validate") for _, u in backends.extract_calls(0))


def test_synthetic_merger_duplicate_accessions(synthetic):
    mod, backends, use_rows, out = synthetic
    use_rows(MERGER_ROWS)
    argv = _synthetic_argv(out, "merger", "graph_cli_merger_dupes")

    assert mod.main(argv) == 0
    summary, details, ckpt, pf = _read(out, "graph_cli_merger_dupes")
    _assert_shape(summary, details, ckpt, pf, n_rows=2)
    acc = MERGER_ROWS[0]["accession_number"]
    assert [r["accession"] for r in details] == [acc, acc]
    assert [r["event_id"] for r in details] == [f"merger_{acc}"] * 2
    used = {fd["pass_used"] for row in details for fd in row["fields"].values()}
    assert "error" not in used, used
    # Per-row contexts: each row keeps its own passages-derived evidence.
    assert details[0]["n_spans"] == 2 and details[1]["n_spans"] == 3
    assert details[0]["fields"]["acquirer"]["pred"] == "Parent Co"
    assert details[1]["fields"]["acquirer"]["pred"] == "Other Parent LLC"
    assert [r["accession"] for r in ckpt] == [acc] * len(ckpt)


def test_unknown_field_is_rejected(synthetic):
    mod, _, use_rows, out = synthetic
    use_rows(TENDER_ROWS)
    argv = _synthetic_argv(out, "tender", "graph_cli_bad", "--fields", "not_a_field")
    assert mod.main(argv) == 2


# --- real holdout leg (skips when artifacts are absent) ------------------------------

REAL_GT = {
    "tender": ROOT / "notebooks/evaluation/tender_offers.csv",
    "merger": ROOT / "notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv",
}
REAL_OUT = {"tender": ROOT / "outputs/tender_eval", "merger": ROOT / "outputs/merger_eval"}


@pytest.mark.parametrize("pack", ["tender", "merger"])
def test_real_holdout_limit2(harness, tmp_path, pack):
    from src.evaluation.experiments import holdout_path
    from src.preprocess.store import DEFAULT_PREPROCESS_ROOT

    if not REAL_GT[pack].exists() or not (DEFAULT_PREPROCESS_ROOT / pack / "events").exists():
        pytest.skip(f"no GT csv / preprocess artifacts for {pack}")
    mod, backends = harness
    out = tmp_path / "out"
    real_holdout = holdout_path(REAL_OUT[pack])
    if real_holdout.exists():
        holdout_path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(real_holdout, holdout_path(out))
    argv = [
        "--pack", pack, "--backend", "orin", "--model", "echo-model",
        "--split", "holdout", "--limit", "2", "--no-temporal",
        "--out", str(out), "--run-name", "graph_cli_real",
    ]
    assert mod.main(argv) == 0
    summary, details, ckpt, pf = _read(out, "graph_cli_real")
    _assert_shape(summary, details, ckpt, pf, n_rows=2)
    used = {fd["pass_used"] for row in details for fd in row["fields"].values()}
    assert "error" not in used, used


# --- temporal disk cache -------------------------------------------------------------


def test_disk_temporal_cache_hit_miss_and_no_tagger(harness, monkeypatch, tmp_path):
    mod, _ = harness
    from src.evaluation.action_packs import TENDER_PACK

    calls: list[tuple] = []

    def fake_precompute(pack, tagger, excerpts, fields):
        calls.append((tagger, excerpts, fields))
        return {"expiration_date": ["- date='Jan 5' label=DATE field_cues=1 window='x'"]}

    monkeypatch.setattr(mod, "precompute_temporal", fake_precompute)
    cache_dir = tmp_path / "temporal_cache" / "tender"

    # --no-temporal: a miss returns {} and must not write (would poison later runs)
    no_tagger = mod.DiskTemporalCache(TENDER_PACK, cache_dir, lambda: None)
    assert no_tagger("evt1", "text", ("expiration_date",)) == {}
    assert not (cache_dir / "evt1.json").exists() and calls == []

    # miss with a tagger: precompute once, write <key>.json (snapshot file layout)
    cache = mod.DiskTemporalCache(TENDER_PACK, cache_dir, lambda: "TAGGER")
    got = cache("evt1", "text", ("expiration_date",))
    assert calls == [("TAGGER", "text", ("expiration_date",))]
    assert json.loads((cache_dir / "evt1.json").read_text(encoding="utf-8")) == got
    assert (cache.hits, cache.misses) == (0, 1)

    # hit: read from disk, no tagger needed (also under --no-temporal)
    assert no_tagger("evt1", "other", ("expiration_date",)) == got
    assert len(calls) == 1 and no_tagger.hits == 1


def test_subset_run_caches_all_date_fields_for_later_full_run(synthetic, monkeypatch):
    """A --fields run with one date field must not leave a cache file missing the others."""
    import types

    from src.evaluation.action_packs import TENDER_PACK

    mod, _, use_rows, out = synthetic
    use_rows(TENDER_ROWS)
    calls: list[tuple[str, ...]] = []

    def fake_precompute(pack, tagger, excerpts, fields):
        calls.append(tuple(fields))
        return {f: [f"- date='Jan 5, 2026' label=DATE field_cues=1 window='{f}'"] for f in fields}

    monkeypatch.setattr(mod, "precompute_temporal", fake_precompute)
    monkeypatch.setitem(
        sys.modules, "transformers", types.SimpleNamespace(pipeline=lambda *a, **k: "TAGGER")
    )
    date_fields = [f for f in TENDER_PACK.fields if f in TENDER_PACK.date_fields]
    assert len(date_fields) >= 2, date_fields

    def argv(run, *extra):
        return [a for a in _synthetic_argv(out, "tender", run, *extra) if a != "--no-temporal"]

    assert mod.main(argv("subset", "--fields", date_fields[0])) == 0
    assert calls and all(set(c) == set(date_fields) for c in calls), calls
    cache_dir = out / "temporal_cache" / "tender"
    for p in cache_dir.glob("*.json"):
        assert set(json.loads(p.read_text(encoding="utf-8"))) == set(date_fields), p

    n_calls = len(calls)
    assert mod.main(argv("full")) == 0
    assert len(calls) == n_calls, "full run re-ran the tagger instead of hitting the cache"
    _, details, _, _ = _read(out, "full")
    for row in details:
        for f in date_fields:
            # every date field has (cached) temporal evidence, so none ends up "empty"
            assert row["fields"][f]["pass_used"] != "empty", (row["accession"], f)
            assert row["fields"][f]["n_evidence_chars"] > 0, (row["accession"], f)


# --- packs without a harness config --------------------------------------------------


def _rights_pack():
    from src.evaluation.action_packs.base import ActionPack

    return ActionPack(
        name="rights_test",
        fields=("issuer", "ratio"),
        field_defs={"issuer": "issuing company", "ratio": "rights ratio"},
        field_pick={},
        hint_allow={"issuer": frozenset({"issuer"}), "ratio": frozenset({"ratio"})},
        gt_to_hint={"issuer": "issuer", "ratio": "ratio"},
        date_fields=frozenset(),
    )


@pytest.fixture
def rights(harness, monkeypatch, tmp_path):
    mod, backends = harness
    pack = _rights_pack()
    real_get_pack = mod.get_pack
    monkeypatch.setattr(
        mod, "get_pack", lambda name: pack if name == "rights_test" else real_get_pack(name)
    )
    monkeypatch.setattr(mod, "DEFAULT_PREPROCESS_ROOT", tmp_path / "preprocess")
    # default --gt/--out resolve under ROOT: keep any regression out of the real repo tree
    monkeypatch.setattr(mod, "ROOT", tmp_path / "repo")
    return mod, backends, tmp_path


def _rights_argv(*extra: str) -> list[str]:
    return [
        "--pack", "rights_test", "--backend", "orin", "--model", "echo-model",
        "--no-temporal", "--run-name", "graph_cli_rights", *extra,
    ]


@pytest.mark.parametrize("given", [(), ("--gt",), ("--out",)])
def test_pack_without_harness_config_needs_gt_and_out(rights, capsys, given):
    mod, backends, tmp_path = rights
    extra: list[str] = []
    if "--gt" in given:
        extra += ["--gt", str(tmp_path / "gt.csv")]
    if "--out" in given:
        extra += ["--out", str(tmp_path / "out")]
    assert mod.main(_rights_argv(*extra)) == 2
    err = capsys.readouterr().err
    assert "rights_test" in err and "--gt" in err and "--out" in err
    assert backends.made == [], "must fail before touching the backend"
    assert not (tmp_path / "repo").exists()


def test_unknown_pack_name_exits_2(harness, capsys):
    mod, _ = harness
    assert mod.main(["--pack", "no_such_pack", "--backend", "orin"]) == 2
    assert "no_such_pack" in capsys.readouterr().err


def test_pack_without_harness_config_runs_with_gt_and_out(rights):
    mod, backends, tmp_path = rights
    gt = tmp_path / "rights_gt.csv"
    rows = [
        {"accession_number": "0000000003-26-000001", "event_id": "rights_evt_1", "issuer": "Acme Corp",
         "ratio": "1 right per share", "passages": _passages(issuer="Acme Corp", ratio="1 right per share")},
        {"accession_number": "0000000003-26-000002", "event_id": "", "issuer": "Beta Inc",
         "ratio": "", "passages": _passages(issuer="Beta Inc")},
    ]
    with gt.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "rights_out"
    assert mod.main(_rights_argv("--gt", str(gt), "--out", str(out), "--split", "holdout")) == 0
    summary, details, ckpt, pf = _read(out, "graph_cli_rights")
    _assert_shape(summary, details, ckpt, pf, n_rows=2)
    assert summary["pack"] == "rights_test"
    # generic event-id strategy: the GT row's own event_id (None when blank)
    assert [r["event_id"] for r in details] == ["rights_evt_1", None]
    assert details[0]["fields"]["issuer"]["pred"] == "Acme Corp"
    assert details[0]["fields"]["issuer"]["outcome"] == "tp"
    assert not (tmp_path / "repo").exists(), "wrote outside --out"
