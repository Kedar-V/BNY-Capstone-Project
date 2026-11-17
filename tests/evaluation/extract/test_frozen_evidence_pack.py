"""Frozen evidence pack: freeze live bundles, replay with EchoFirstBackend matches live graph."""

from __future__ import annotations

import json
from pathlib import Path

from fakes import EchoFirstBackend, FakeProvider
from src.evaluation.action_packs.base import ActionPack, HybridSpec
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.frozen import (
    FrozenEvidenceProvider,
    FrozenFieldRecord,
    FrozenStage,
    build_manifest,
    load_evidence_pack,
    write_evidence_pack,
)
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EventContext, build_bundle, context_n_rules, context_rules_direct


def _pack() -> ActionPack:
    return ActionPack(
        name="fake",
        fields=("offer_price", "ticker"),
        field_defs={
            "offer_price": "cash price per share",
            "ticker": "trading ticker",
        },
        field_pick={
            "offer_price": "Pick the purchase price.",
            "ticker": "Pick the ticker.",
        },
        hint_allow={
            "offer_price": frozenset({"offer_price", "price"}),
            "ticker": frozenset({"ticker"}),
        },
        gt_to_hint={"offer_price": "offer_price", "ticker": "ticker"},
        date_fields=frozenset(),
        hybrid=HybridSpec(use_dense=False, top_k=2, max_chars=500),
    )


def _ctx() -> EventContext:
    return EventContext(
        rep={
            "candidate_facts": [
                {
                    "method": "rules",
                    "field_hint": "ticker",
                    "raw": "ACME",
                    "value": "ACME",
                },
                {
                    "method": "rules",
                    "field_hint": "offer_price",
                    "raw": "$12.50 per Share",
                    "value": "$12.50 per Share",
                },
            ]
        },
        spans=[
            {
                "field_hint": "offer_price",
                "label": "price",
                "text": "$12.50",
                "score": 0.9,
            }
        ],
        excerpts="The purchase price is $12.50 per Share in cash. Ticker: ACME.",
        doc_text="The purchase price is $12.50 per Share in cash. Ticker: ACME. " * 4,
        accession="ACC1",
        event_id="evt1",
    )


def test_write_load_roundtrip(tmp_path: Path):
    pack = _pack()
    ctx = _ctx()
    field = "offer_price"
    policy = resolve_policy(pack, field, cascade=False)
    stages = []
    for stage in policy.stages:
        b = build_bundle(pack, ctx, field, stage.sources)
        stages.append(
            FrozenStage(
                name=stage.name,
                sources=stage.sources,
                prompt_mode=stage.prompt_mode,
                on_empty=stage.on_empty,
                direct_from_rules=stage.direct_from_rules,
                empty=b.empty,
                text=b.text,
                source=b.source,
                n_chars=b.n_chars,
            )
        )
    rec = FrozenFieldRecord(
        ei=0,
        accession="ACC1",
        key="ACC1#0",
        event_id="evt1",
        field=field,
        gold="$12.50 per Share",
        stages=tuple(stages),
        rules_direct=tuple(context_rules_direct(pack, ctx, field)),
        n_rules=context_n_rules(pack, ctx, field),
    )
    man = build_manifest(
        pack_id="test_pack",
        pack=pack,
        fields=(field,),
        cascade=False,
        validate=False,
        split="holdout",
        n_rows=1,
        accessions=["ACC1"],
        accession_hash="abc",
    )
    out = write_evidence_pack(tmp_path / "pack", manifest=man, records=[rec])
    man2, recs, by_key = load_evidence_pack(out)
    assert man2["pack_id"] == "test_pack"
    assert len(recs) == 1
    assert by_key[("ACC1#0", field)].gold == "$12.50 per Share"
    assert "HYBRID EXCERPTS" in by_key[("ACC1#0", field)].stages[0].text or "GLINER" in by_key[
        ("ACC1#0", field)
    ].stages[0].text


def test_frozen_replay_matches_live_graph(tmp_path: Path):
    pack = _pack()
    ctx = _ctx()
    fields = ("offer_price", "ticker")
    records: list[FrozenFieldRecord] = []
    for field in fields:
        policy = resolve_policy(pack, field, cascade=False)
        stages = []
        for stage in policy.stages:
            b = build_bundle(pack, ctx, field, stage.sources)
            stages.append(
                FrozenStage(
                    name=stage.name,
                    sources=stage.sources,
                    prompt_mode=stage.prompt_mode,
                    on_empty=stage.on_empty,
                    direct_from_rules=stage.direct_from_rules,
                    empty=b.empty,
                    text=b.text,
                    source=b.source,
                    n_chars=b.n_chars,
                    validate=stage.validate,
                    pass_label=stage.pass_label,
                    null_label=stage.null_label,
                    empty_label=stage.empty_label,
                    direct_label=stage.direct_label,
                )
            )
        records.append(
            FrozenFieldRecord(
                ei=0,
                accession="ACC1",
                key="ACC1#0",
                event_id="evt1",
                field=field,
                gold="x",
                stages=tuple(stages),
                rules_direct=tuple(context_rules_direct(pack, ctx, field)),
                n_rules=context_n_rules(pack, ctx, field),
            )
        )
    by_key = {(r.key, r.field): r for r in records}
    write_evidence_pack(
        tmp_path / "pack",
        manifest=build_manifest(
            pack_id="rt",
            pack=pack,
            fields=fields,
            cascade=False,
            validate=False,
            split="holdout",
            n_rows=1,
            accessions=["ACC1"],
            accession_hash="x",
        ),
        records=records,
    )

    live_be = EchoFirstBackend()
    live_prov = FakeProvider({"ACC1#0": ctx})
    live_graph = build_extract_graph(pack, live_be, live_prov)

    frozen_be = EchoFirstBackend()
    frozen_prov = FrozenEvidenceProvider(by_key)
    frozen_graph = build_extract_graph(pack, frozen_be, frozen_prov)

    for field in fields:
        req = FieldExtractRequest(
            pack_name=pack.name,
            field=field,
            event_id="evt1",
            accession="ACC1#0",
            model="echo",
            validate_enabled=False,
            cascade=False,
        )
        live = run_field(live_graph, req)
        frozen = run_field(frozen_graph, req)
        assert frozen.pred == live.pred
        assert frozen.pass_used == live.pass_used
        assert frozen.evidence == live.evidence
        assert [c[1] for c in frozen_be.calls] == [c[1] for c in live_be.calls]
        live_be.calls.clear()
        frozen_be.calls.clear()


def test_compare_script_requires_shared_pack_id(tmp_path: Path):
    import subprocess
    import sys

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "summary.json").write_text(
        json.dumps(
            {
                "evidence_pack_id": "p1",
                "model": "m1",
                "fields": ["offer_price"],
                "micro": {"f1": 0.5},
                "per_field": {"offer_price": {"f1": 0.5}},
            }
        ),
        encoding="utf-8",
    )
    (b / "summary.json").write_text(
        json.dumps(
            {
                "evidence_pack_id": "p2",
                "model": "m2",
                "fields": ["offer_price"],
                "micro": {"f1": 0.6},
                "per_field": {"offer_price": {"f1": 0.6}},
            }
        ),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/compare_evidence_runs.py"), str(a), str(b)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
