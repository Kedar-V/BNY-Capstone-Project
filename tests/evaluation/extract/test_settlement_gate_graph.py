from __future__ import annotations

import json

from fakes import FakeBackend, FakeProvider
from src.evaluation.action_packs.base import ActionPack
from src.evaluation.action_packs.tender import TENDER_PACK
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.policies import FieldPolicy, Stage, resolve_policy
from src.evaluation.extract.providers import EventContext
from src.preprocess.rules_ids import settlement_accept


def _gated_pack() -> ActionPack:
    fields = ("settlement_date",)
    policy = FieldPolicy(
        stages=(
            Stage(name="rules", sources=("rules",), prompt_mode="pick", on_empty="skip",
                  pass_label="A", null_label="A_null", direct_from_rules=False, validate=False,
                  accept=settlement_accept),
            Stage(name="span", sources=("gliner",), prompt_mode="pick", on_empty="skip",
                  pass_label="B", null_label="B_null", direct_from_rules=False, validate=False,
                  accept=settlement_accept),
        ),
        stop_at_first_hit=True,
    )
    return ActionPack(
        name="fake",
        fields=fields,
        field_defs={"settlement_date": "payment date"},
        field_pick={},
        hint_allow={"settlement_date": frozenset({"settlement_date"})},
        gt_to_hint={"settlement_date": "settlement_date"},
        date_fields=frozenset({"settlement_date"}),
        validate_fields=frozenset(),
        policies={"settlement_date": policy},
    )


def _req() -> FieldExtractRequest:
    return FieldExtractRequest(pack_name="fake", field="settlement_date", event_id=None,
                               accession="acc1", model="m", validate_enabled=False, cascade=True)


def test_promptly_template_kept_when_rules_evidence_has_cue():
    """Mirror oracle Settlement template: accept Payment: promptly on Pass A."""
    ctx = EventContext(
        rep={"candidate_facts": [{"method": "rules", "field_hint": "settlement_date",
                                  "raw": "Payment: promptly"}]},
        excerpts=(
            "Shares will be accepted for payment promptly following expiration of the Offer."
        ),
        spans=[{"field_hint": "settlement_date", "label": "settlement_date",
                "text": "The Fund paid on or about January 5, 2026 to holders.", "score": 0.9}],
    )
    be = FakeBackend([
        json.dumps({"settlement_date": "Payment: promptly"}),
        json.dumps({"settlement_date": "1/5/2026"}),
    ])
    provider = FakeProvider({"acc1": ctx})
    res = run_field(build_extract_graph(_gated_pack(), be, provider), _req())
    assert res.pred == "Payment: promptly"
    assert res.pass_used == "A"
    assert len(be.prompts) == 1


def test_date_without_pay_cue_falls_through_to_spans():
    ctx = EventContext(
        rep={"candidate_facts": [{"method": "rules", "field_hint": "settlement_date",
                                  "raw": "3/31/2025"}]},
        excerpts="Valuation Date: March 31, 2025. The Offer expires on February 8, 2026.",
        spans=[{"field_hint": "settlement_date", "label": "settlement_date",
                "text": "The Fund paid on or about January 5, 2026 to holders.", "score": 0.9}],
    )
    be = FakeBackend([
        json.dumps({"settlement_date": "3/31/2025"}),  # stage A: gate rejects
        json.dumps({"settlement_date": "1/5/2026"}),   # stage B: dated, cue present
    ])
    provider = FakeProvider({"acc1": ctx})
    res = run_field(build_extract_graph(_gated_pack(), be, provider), _req())
    assert res.pred == "1/5/2026"
    assert res.pass_used == "B"
    assert len(be.prompts) == 2


def test_tender_settlement_policy_is_gated_cascade():
    p = resolve_policy(TENDER_PACK, "settlement_date", cascade=True)
    assert [s.name for s in p.stages] == ["rules", "span"]
    assert all(s.accept is settlement_accept for s in p.stages)
    assert p.stages[0].direct_from_rules is True
    assert p.stop_at_first_hit is True
