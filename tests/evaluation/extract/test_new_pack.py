"""A brand-new corporate action is config-only: an inline ActionPack, no extract-package code."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from fakes import FakeBackend, FakeProvider
from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec
from src.evaluation.extract import policies as policies_mod
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EventContext

PKG = Path(policies_mod.__file__).parent
CLAUSE = "Holders may exercise the right until the expiration date, subject to the terms herein."


def _pack(extra_field: str | None = None) -> ActionPack:
    fields = ("rights_clause", "expiry") + ((extra_field,) if extra_field else ())
    return ActionPack(
        name="rights_test",
        fields=fields,
        field_defs={"rights_clause": "the exercise clause", "expiry": "rights expiry date"},
        field_pick={},
        hint_allow={"rights_clause": frozenset({"rights_clause"}), "expiry": frozenset({"expiry"})},
        gt_to_hint={"rights_clause": "rights_clause", "expiry": "expiry"},
        date_fields=frozenset({"expiry"}),
        temporal_cues={"expiry": ("expire",)},
        clause_fields={
            "rights_clause": ClauseFieldSpec(
                quote_field="rights",
                patterns=(r"(holders may exercise[^.]{10,}\.)",),
                extract_prompt="RIGHTS COPY {field}: {excerpt}",
            )
        },
    )


def _req(field: str, pack_name: str = "rights_test") -> FieldExtractRequest:
    return FieldExtractRequest(
        pack_name=pack_name,
        field=field,
        event_id=None,
        accession="acc1",
        model="m",
        validate_enabled=False,
        cascade=True,
    )


def _snapshot() -> dict[str, str]:
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(PKG.rglob("*.py"))
    }


def test_new_pack_runs_end_to_end_with_no_package_changes():
    before = _snapshot()
    pack = _pack()

    # policies resolve from the pack alone
    assert pack.policies == {} and pack.hooks is None
    clause_pol = resolve_policy(pack, "rights_clause", cascade=True)
    assert [s.name for s in clause_pol.stages] == ["clause"]
    date_pol = resolve_policy(pack, "expiry", cascade=True)
    assert [s.name for s in date_pol.stages] == ["rules", "span"]
    assert date_pol.stages[1].sources == ("gliner", "temporal")

    ctx = EventContext(
        excerpts="Preamble. " + CLAUSE.lower() + " More text.",
        rep={"candidate_facts": [{"method": "rules", "field_hint": "expiry", "raw": "May 1"}]},
        spans=[{"field_hint": "expiry", "label": "expiry", "text": "June 2, 2027", "score": 0.9}],
        temporal_cache={"expiry": ["- date='June 2, 2027' label=DATE field_cues=1 window='x'"]},
    )
    be = FakeBackend(
        [
            json.dumps({"rights_clause": "holders may exercise the right"}),  # clause, own prompt
            '{"expiry": null}',  # cascade pass A (rules) misses
            '{"expiry": "June 2, 2027"}',  # cascade pass B (gliner+temporal) hits
        ]
    )
    provider = FakeProvider({"acc1": ctx})
    g = build_extract_graph(pack, be, provider)

    clause = run_field(g, _req("rights_clause"))
    assert clause.pass_used == "clause"
    assert clause.pred == "holders may exercise the right"
    assert be.prompts[0].startswith("RIGHTS COPY rights_clause: holders may exercise the right")

    date = run_field(g, _req("expiry"))
    assert date.pass_used == "B"
    assert date.pred == "June 2, 2027"
    assert "hint=expiry value='May 1'" in be.prompts[1]
    assert "TEMPORAL SPANS" in be.prompts[2]
    assert len(be.calls) == 3

    assert _snapshot() == before


def test_field_without_any_config_entry_does_not_raise():
    pack = _pack(extra_field="orphan")
    assert "orphan" not in pack.field_defs
    assert "orphan" not in pack.hint_allow
    assert "orphan" not in pack.field_pick
    ctx = EventContext(spans=[{"field_hint": "orphan", "label": "orphan", "text": "X", "score": 0.9}])
    be = FakeBackend(fn=lambda s, u, m: '{"orphan": "X"}')
    g = build_extract_graph(pack, be, FakeProvider({"acc1": ctx}))
    res = run_field(g, _req("orphan"))
    assert res.pass_used != "error", res.raw_llm
    assert res.pred is None or isinstance(res.pred, str)


def test_extract_package_source_is_action_agnostic():
    # merger inventory logic (primary_entity / *14A,*14C proxies) lives in the merger pack hooks
    pat = re.compile(
        r"tender|merger|proration|SC TO|primary_entity|is_proxy_filing|14A|14C", re.IGNORECASE
    )
    hits = [
        f"{p.relative_to(PKG)}:{i}: {line.strip()}"
        for p in sorted(PKG.rglob("*.py"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.search(line)
    ]
    assert hits == []
