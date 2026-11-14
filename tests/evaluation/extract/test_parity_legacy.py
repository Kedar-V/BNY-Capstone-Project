"""Parity gate: the LangGraph extract layer vs the frozen legacy ``extract_field``.

Both sides see the same contexts (built by ArtifactProvider) and a deterministic
``EchoFirstBackend``, so only control flow is compared: for every (event, field) the
tuple (pred, pass_used, n_evidence_chars, n_rules, raw_llm) must match, and so must the
exact sequence of (system, user) prompts sent to the backend.

Legs
- synthetic: hand-built artifacts exercising clause hit/miss, direct-rules fields,
  the inventory prior on a proxy filing, cascade A->B, oneshot, validate drop/keep.
- real artifacts (tender + merger): skipped cleanly when GT / preprocess artifacts are
  absent. Sampled to keep runtime low: every ``STRIDE``-th accession of the sorted GT
  accessions (capped at ``MAX_EVENTS``), first GT row per accession, all core fields.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from fakes import EchoFirstBackend
from legacy_extract import extract_field as legacy_extract_field
from src.evaluation.action_packs import MERGER_PACK, TENDER_PACK
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.providers import ArtifactProvider
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

ROOT = Path(__file__).resolve().parents[3]
# Frozen copy of the 2026-11-13 harness (.txt so pytest never collects it)
SNAPSHOT = Path(__file__).resolve().parent / "fixtures/legacy_harness_snapshot_20261113.py.txt"
LIVE_SCRIPT = ROOT / "scripts/eval_unified_field_qwen.py"
MODEL = "echo-model"
MODES = [(c, v) for c in (True, False) for v in (True, False)]
MODE_IDS = [f"{'cascade' if c else 'oneshot'}-{'validate' if v else 'novalidate'}" for c, v in MODES]
BACKEND_MODES = ("plain", "noisy")
STRIDE = 8
MAX_EVENTS = 60


# --- comparison core ---------------------------------------------------------------


def _legacy_kwargs(ctx) -> dict:
    return dict(
        rep=ctx.rep,
        spans=ctx.spans,
        excerpts=ctx.excerpts,
        tagger=None,
        temporal_cache=ctx.temporal_cache,
        passages=ctx.passages,
        doc_text=ctx.doc_text,
        primary_entity=ctx.extras.get("primary_entity", ""),
        is_proxy_filing=ctx.extras.get("is_proxy_filing") == "1",
    )


def _compare(pack, provider, keys, *, cascade, validate, backend_mode, fields=None):
    """Return (n_cases, mismatches, pass_used histogram)."""
    graph_backend = EchoFirstBackend(backend_mode)
    legacy_backend = EchoFirstBackend(backend_mode)
    graph = build_extract_graph(pack, graph_backend, provider)
    mismatches: list[str] = []
    hist: dict[str, int] = {}
    n = 0
    for key in keys:
        for field in fields or pack.fields:
            req = FieldExtractRequest(
                pack_name=pack.name, field=field, event_id=None, accession=key,
                model=MODEL, validate_enabled=validate, cascade=cascade,
            )
            ctx = provider.context(req)
            g0, l0 = len(graph_backend.calls), len(legacy_backend.calls)
            got = run_field(graph, req)
            want = legacy_extract_field(
                pack=pack, backend=legacy_backend, model=MODEL, field=field,
                cascade=cascade, validate=validate, **_legacy_kwargs(ctx),
            )
            n += 1
            hist[want["pass_used"]] = hist.get(want["pass_used"], 0) + 1
            g_t = (got.pred, got.pass_used, got.n_evidence_chars, got.n_rules, got.raw_llm)
            l_t = (want["pred"], want["pass_used"], want["n_evidence_chars"],
                   want["n_rules"], want["raw_llm"])
            if g_t != l_t:
                mismatches.append(f"{key}/{field}: graph={g_t!r} legacy={l_t!r}")
            elif graph_backend.calls[g0:] != legacy_backend.calls[l0:]:
                mismatches.append(f"{key}/{field}: prompt sequences differ")
    return n, mismatches, hist


def _assert_parity(pack, provider, keys, **kw):
    n, bad, hist = _compare(pack, provider, keys, **kw)
    print(f"\n[parity] {pack.name} {kw} cases={n} mismatches={len(bad)} passes={dict(sorted(hist.items()))}")
    assert n > 0
    assert not bad, f"{len(bad)}/{n} mismatches; first: {bad[:3]}"
    return hist


# --- synthetic fixture ---------------------------------------------------------------


def _w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _event(store: ArtifactStore, eid: str, *, facts=(), spans=(), segments=(), inventory=None):
    base = store.path_root / "events" / eid
    if facts:
        _w(base / "concise" / "event_rep.json", {"candidate_facts": list(facts)})
    if spans:
        _w(base / "spans.json", {"spans": list(spans)})
    if segments:
        _w(base / "segments.json", {"segments": list(segments)})
    if inventory is not None:
        _w(base / "inventory.json", inventory)


def _row_key(rows, row) -> str:
    """Per-row context key (identity-based: duplicate accessions stay distinct)."""
    i = next(i for i, r in enumerate(rows) if r is row)
    return f"{row['accession_number']}#{i}"


def _fact(hint, raw, passage="ctx"):
    return {"method": "rules", "field_hint": hint, "raw": raw, "passage": passage}


def _span(hint, text, score=0.9, label=None):
    return {"field_hint": hint, "label": label or hint, "text": text, "passage": f"...{text}...", "score": score}


PRORATION = (
    "If more than 1,000,000 Shares are validly tendered and not withdrawn, "
    "the Purchaser will accept Shares on a pro rata basis, disregarding fractions."
)
FAQ = {"kind": "faq", "heading": "Summary Term Sheet", "text": (
    "The offer will expire at 5:00 p.m. on March 3, 2026. "
    "We will accept for payment promptly after expiration. " + PRORATION)}


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic_preprocess")

    def temporal_for(key, excerpts, fields):
        return {f: [f"- date='March 3, 2026' label=DATE field_cues=2 window='{key} {f}'"]
                for f in fields if excerpts}

    out = {}
    # ---- tender
    ts = ArtifactStore("tender", root)
    _event(ts, "t_full",
           facts=[_fact("ticker", "ACME"), _fact("cusip", "123456789"), _fact("isin", "US1234567890"),
                  _fact("target", "Acme Corp"), _fact("offer_price", "$12.50 per Share"),
                  _fact("expiration", "March 3, 2026")],
           spans=[_span("bidder", "Parent"), _span("bidder", "Buyer Holdings LLC"),
                  _span("expiration_date", "March 3, 2026"), _span("security_description", "common stock"),
                  _span("currency", "$"), _span("withdrawal_deadline", "March 3, 2026", label="withdrawal")],
           segments=[FAQ])
    _event(ts, "t_spans_only",
           spans=[_span("subject_company", "Acme Corp", label="target_organization"),
                  _span("effective_date", "January 5, 2026")],
           segments=[{"kind": "full_doc", "heading": "Doc", "text": "Nothing about the deadline here. " * 12}])
    _event(ts, "t_empty")
    rows = [
        {"accession_number": "T-hit", "passages": json.dumps(
            {"proration_terms": [{"quote": PRORATION}]}), "_eid": "t_full"},
        {"accession_number": "T-regex", "passages": "", "_eid": "t_full"},  # clause via doc_text/excerpts regex
        {"accession_number": "T-miss", "passages": "", "_eid": "t_spans_only"},  # clause miss
        {"accession_number": "T-empty", "passages": "", "_eid": "t_empty"},
        {"accession_number": "T-none", "passages": json.dumps(
            {"bidder": [{"quote": "Buyer Holdings LLC"}], "minimum_tender_condition": [
                {"quote": "at least a majority of the outstanding Shares"}]}), "_eid": None},
        {"accession_number": "T-dup", "passages": "", "_eid": "t_full"},
        {"accession_number": "T-dup", "passages": "", "_eid": "t_full"},
    ]
    keys_rows = [(f"{r['accession_number']}#{i}", r) for i, r in enumerate(rows)]
    prov = ArtifactProvider(
        TENDER_PACK, ts, None, event_id_for=lambda r: r["_eid"], temporal_for=temporal_for,
        key_for=lambda r: _row_key(rows, r),
    )
    prov.prepare(rows, TENDER_PACK.fields)
    out["tender"] = (TENDER_PACK, prov, [k for k, _ in keys_rows])

    # ---- merger
    ms = ArtifactStore("merger", root)
    proxy_inv = {"primary_entity": "Target Widgets Inc.", "docs": [{"form": "DEFM14A"}]}
    _event(ms, "m_proxy", inventory=proxy_inv,
           facts=[_fact("target", "Target Widgets Inc."), _fact("ticker", "TWI"),
                  _fact("cash_consideration", "$40.00 in cash")],
           spans=[_span("acquirer", "Target Widgets Inc."), _span("acquirer", "Big Acquirer Corp"),
                  _span("acquirer", "Parent"), _span("cash_consideration", "$40.00 per share"),
                  _span("shareholder_vote_date", "June 12, 2026"), _span("effective_date", "Q3 2026")],
           segments=[FAQ])
    _event(ms, "m_proxy_norules", inventory=proxy_inv,
           spans=[_span("target", "Other Name Corp")])
    _event(ms, "m_8k", inventory={"primary_entity": "Target Widgets Inc.", "docs": [{"form": "8-K"}]},
           facts=[_fact("target", "Target Widgets Inc.")],
           spans=[_span("cash_consideration", "$40.00 per share"), _span("target", "Target Widgets Inc.")])
    _event(ms, "m_cash_only", inventory={"primary_entity": "", "docs": [{"form": "S-4"}]},
           spans=[_span("cash_consideration", "$55 in cash")])
    mrows = [
        {"accession_number": "M-proxy", "passages": "", "_eid": "m_proxy"},
        {"accession_number": "M-proxy-norules", "passages": "", "_eid": "m_proxy_norules"},
        {"accession_number": "M-8k", "passages": "", "_eid": "m_8k"},
        {"accession_number": "M-cash", "passages": "", "_eid": "m_cash_only"},
        {"accession_number": "M-none", "passages": "", "_eid": None},
    ]
    mprov = ArtifactProvider(
        MERGER_PACK, ms, None, event_id_for=lambda r: r["_eid"], temporal_for=temporal_for,
        key_for=lambda r: _row_key(mrows, r),
    )
    mprov.prepare(mrows, MERGER_PACK.fields)
    out["merger"] = (MERGER_PACK, mprov, [f"{r['accession_number']}#{i}" for i, r in enumerate(mrows)])
    return out


@pytest.mark.parametrize("backend_mode", BACKEND_MODES)
@pytest.mark.parametrize("cascade,validate", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("pack_name", ["tender", "merger"])
def test_parity_synthetic(synthetic, pack_name, cascade, validate, backend_mode):
    pack, prov, keys = synthetic[pack_name]
    hist = _assert_parity(pack, prov, keys, cascade=cascade, validate=validate, backend_mode=backend_mode)
    # the fixture must actually reach the interesting branches
    if cascade and pack_name == "tender":
        assert {"clause", "clause_miss", "A_rules"} <= set(hist) or backend_mode == "noisy"
    if cascade and pack_name == "merger" and backend_mode == "plain":
        assert "A_inventory" in hist


def test_synthetic_fixture_covers_branches(synthetic):
    """Union over all modes must hit clause/miss/direct/prior/A->B/oneshot/C_drop/C_keep."""
    seen: set[str] = set()
    for pack_name in ("tender", "merger"):
        pack, prov, keys = synthetic[pack_name]
        for cascade, validate in MODES:
            for bm in BACKEND_MODES:
                seen |= set(_compare(pack, prov, keys, cascade=cascade, validate=validate,
                                     backend_mode=bm)[2])
    joined = " ".join(sorted(seen))
    for want in ("clause", "clause_miss", "A_rules", "A_inventory", "A", "B", "oneshot",
                 "C_drop", "C_keep", "empty"):
        assert want in joined, f"fixture never produced {want!r}; saw {sorted(seen)}"


# --- real artifacts -------------------------------------------------------------------

GT_PATHS = {
    "tender": ROOT / "notebooks/evaluation/tender_offers.csv",
    "merger": ROOT / "notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv",
}
DOCS_PARQUET = ROOT / "data/processed/documents.parquet"


@pytest.fixture(scope="module", params=["tender", "merger"])
def real(request):
    from src.evaluation.tender import gt_event_ids_from_corpus, load_gt

    name = request.param
    pack = TENDER_PACK if name == "tender" else MERGER_PACK
    if not GT_PATHS[name].exists() or not (DEFAULT_PREPROCESS_ROOT / pack.name / "events").exists():
        pytest.skip(f"no GT / preprocess artifacts for {name}")
    gt_rows = load_gt(GT_PATHS[name])
    first_by_acc: dict[str, dict] = {}
    for r in gt_rows:
        acc = (r.get("accession_number") or "").strip()
        if acc:
            first_by_acc.setdefault(acc, r)
    accs = sorted(first_by_acc)[::STRIDE][:MAX_EVENTS]
    rows = [first_by_acc[a] for a in accs]
    if name == "tender":
        if not DOCS_PARQUET.exists():
            pytest.skip("documents.parquet missing (tender accession->event_id map)")
        acc_to_eid = gt_event_ids_from_corpus(set(accs), DOCS_PARQUET)

        def eid_for(row):
            acc = (row.get("accession_number") or "").strip()
            return acc_to_eid.get(acc) or (row.get("event_id") or "").strip() or None
    else:
        def eid_for(row):
            acc = (row.get("accession_number") or "").strip()
            return f"merger_{acc}" if acc else None

    # per-row keys: duplicate accessions would raise with the default key
    keyed = {f"{(r.get('accession_number') or '').strip()}#{i}": r for i, r in enumerate(rows)}
    key_of = {id(r): k for k, r in keyed.items()}
    prov = ArtifactProvider(pack, event_id_for=eid_for, key_for=lambda r: key_of[id(r)])
    keys = prov.prepare(rows, pack.fields)
    n_rep = sum(1 for k in keys if prov._contexts[k].rep)
    if n_rep == 0:
        pytest.skip(f"no sampled {name} event has preprocess artifacts")
    n_proxy = sum(1 for k in keys if prov._contexts[k].extras.get("is_proxy_filing") == "1")
    print(f"\n[real:{name}] events={len(keys)} with_rep={n_rep} proxy={n_proxy}")
    return pack, prov, keys


@pytest.mark.parametrize("backend_mode", BACKEND_MODES)
@pytest.mark.parametrize("cascade,validate", MODES, ids=MODE_IDS)
def test_parity_real_artifacts(real, cascade, validate, backend_mode):
    pack, prov, keys = real
    _assert_parity(pack, prov, keys, cascade=cascade, validate=validate, backend_mode=backend_mode)


# --- drift watch ------------------------------------------------------------------------

DRIFT_FUNCS = ("extract_field", "build_evidence", "_gliner_lines", "_rules_lines")


def _func_sources(path: Path, names) -> dict[str, str | None]:
    src = path.read_text(encoding="utf-8")
    found: dict[str, str | None] = {n: None for n in names}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
            found[node.name] = ast.get_source_segment(src, node)
    return found


@pytest.mark.xfail(
    strict=False,
    reason="live harness differs from the frozen 2026-11-13 snapshot: the graph is "
    "pinned to the snapshot, so review the diff and re-baseline or port the change",
)
def test_live_script_has_not_drifted_from_snapshot():
    if not SNAPSHOT.exists():
        pytest.skip(f"frozen harness snapshot missing: {SNAPSHOT}")
    snap = _func_sources(SNAPSHOT, DRIFT_FUNCS)
    assert all(snap.values()), f"snapshot is missing functions: {snap}"
    live = _func_sources(LIVE_SCRIPT, DRIFT_FUNCS)
    drifted = [n for n in DRIFT_FUNCS if live[n] != snap[n]]
    assert not drifted, f"live script differs from snapshot in: {drifted}"
