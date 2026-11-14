from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.policies import FieldPolicy, Stage, resolve_policy


def _pack(**kw) -> ActionPack:
    base = dict(
        name="fake",
        fields=("ticker", "cusip", "deadline", "name", "clause_f"),
        field_defs={},
        field_pick={},
        hint_allow={},
        gt_to_hint={},
        date_fields=frozenset({"deadline"}),
        validate_fields=frozenset({"clause_f", "name"}),
        clause_fields={
            "clause_f": ClauseFieldSpec(quote_field="q", patterns=("x",), extract_prompt="p")
        },
    )
    base.update(kw)
    return ActionPack(**base)


def test_clause_field_resolves_single_clause_stage():
    p = resolve_policy(_pack(), "clause_f", cascade=True)
    assert len(p.stages) == 1
    s = p.stages[0]
    assert s.sources == ("clause",)
    assert s.on_empty == "null"
    assert s.pass_label == "clause"
    assert s.null_label == "clause_null"
    assert s.validate is True
    pk = _pack(validate_fields=frozenset())
    assert resolve_policy(pk, "clause_f", cascade=False).stages[0].validate is False


def test_oneshot_policy_for_date_field_includes_temporal():
    pack = _pack()
    s = resolve_policy(pack, "deadline", cascade=False).stages[0]
    assert s.sources == ("rules", "gliner", "temporal")
    assert s.on_empty == "ask"
    assert s.pass_label == "oneshot"
    # legacy Pass C gate: field in validate_fields, regardless of stage
    assert s.validate is False
    assert resolve_policy(pack, "name", cascade=False).stages[0].validate is True
    assert resolve_policy(pack, "name", cascade=False).stages[0].sources == ("rules", "gliner")


def test_cascade_policy_has_rules_then_span_stage():
    pack = _pack()
    a, b = resolve_policy(pack, "name", cascade=True).stages
    assert a.sources == ("rules",)
    assert a.on_empty == "skip"
    assert a.pass_label == "A"
    assert a.null_label is None
    assert a.validate is True
    assert b.sources == ("gliner",)
    assert b.pass_label == "B"
    assert b.null_label == "B_null"
    assert b.validate is True
    a2, b2 = resolve_policy(pack, "deadline", cascade=True).stages
    assert a2.validate is False
    assert b2.validate is False
    assert b2.sources == ("gliner", "temporal")


def test_identifier_fields_are_direct_from_rules():
    pack = _pack()
    for f in ("ticker", "cusip"):
        a = resolve_policy(pack, f, cascade=True).stages[0]
        assert a.direct_from_rules is True
        assert a.direct_label == "A_rules"
    assert resolve_policy(pack, "name", cascade=True).stages[0].direct_from_rules is False


def test_pack_policy_overrides_derivation():
    custom = FieldPolicy(
        stages=(
            Stage(
                name="x", sources=("rules",), prompt_mode="pick", on_empty="null",
                pass_label="X", null_label="X_null", direct_from_rules=False, validate=False,
            ),
        )
    )
    pack = _pack(policies={"name": custom})
    assert resolve_policy(pack, "name", cascade=True) is custom


def _stage(**kw) -> Stage:
    base = dict(
        name="x", sources=("rules",), prompt_mode="pick", on_empty="skip",
        pass_label="X", null_label=None, direct_from_rules=True, validate=False,
    )
    base.update(kw)
    return Stage(**base)


@pytest.mark.parametrize("sources", [("rules",), ("prior",)])
def test_direct_stage_accepts_rules_or_prior_only_sources(sources):
    assert _stage(sources=sources).direct_from_rules is True


@pytest.mark.parametrize("sources", [("gliner",), ("rules", "gliner"), ("clause",), ("rules", "prior")])
def test_direct_stage_rejects_other_sources(sources):
    with pytest.raises(ValueError, match="direct_from_rules"):
        _stage(sources=sources)
    assert _stage(sources=sources, direct_from_rules=False).sources == sources


def test_pack_policy_key_must_be_in_fields():
    with pytest.raises(ValueError):
        _pack(policies={"nope": FieldPolicy(stages=())})


def test_unknown_field_without_defs_derives_default():
    p = resolve_policy(_pack(), "not_in_anything", cascade=True)
    assert len(p.stages) == 2


def test_request_rejects_blank_field():
    kw = dict(pack_name="p", event_id=None, accession="a", model="m",
              validate_enabled=True, cascade=True)
    with pytest.raises(ValidationError):
        FieldExtractRequest(field="  ", **kw)
    assert FieldExtractRequest(field="f", **kw).field == "f"
