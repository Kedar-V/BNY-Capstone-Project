"""Field evidence routing: heuristic/oracle maps, guards, recipe_to_policy, mock Laya."""

from __future__ import annotations

from unittest.mock import patch

from src.evaluation.action_packs import TENDER_PACK
from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.laya_client import LayaAnswer, LayaResult, _parse_answers_to_recipe
from src.evaluation.extract.routing import (
    apply_guards,
    heuristic_recipe,
    load_oracle_priors,
    pack_with_recipes,
    recipe_to_policy,
    route_fields,
)


def test_oracle_priors_load():
    priors = load_oracle_priors()
    assert priors.get("cusip") == "Rules"
    assert "Temporal" in (priors.get("expiration_date") or "")


def test_heuristic_maps_oracle_systems():
    pack = TENDER_PACK
    r = heuristic_recipe(pack, "cusip", oracle_system="Rules")
    assert r.shape == "oneshot" and r.legs == frozenset({"rules"})

    r = heuristic_recipe(pack, "expiration_date", oracle_system="Temporal NER")
    assert "temporal" in r.legs and "hybrid" in r.legs

    r = heuristic_recipe(pack, "settlement_date", oracle_system="Settlement template")
    assert r.shape == "rules_then_span"
    pol = recipe_to_policy(pack, r)
    assert [s.name for s in pol.stages] == ["rules", "span"]
    assert "hybrid" in pol.stages[1].sources

    r = heuristic_recipe(pack, "proration_terms", oracle_system="Llama clauses")
    assert r.shape == "clause_then_pick"
    assert "hybrid" in r.legs and "clause" in r.legs
    pol = recipe_to_policy(pack, r)
    assert [s.name for s in pol.stages] == ["clause", "oneshot"]
    assert "hybrid" in pol.stages[1].sources

    r = heuristic_recipe(pack, "offer_price", oracle_system="Qwen direct")
    assert r.shape == "oneshot"
    assert r.legs == frozenset({"rules", "hybrid"})
    assert "gliner" not in r.legs


def test_guards_drop_temporal_on_non_date():
    pack = TENDER_PACK
    shape, legs, notes = apply_guards(
        pack, "bidder", "oneshot", frozenset({"rules", "temporal", "hybrid"})
    )
    assert "temporal" not in legs
    assert any("temporal" in n for n in notes)


def test_guards_drop_hybrid_when_pack_has_none():
    pack = ActionPack(
        name="fake",
        fields=("x",),
        field_defs={"x": "x"},
        field_pick={},
        hint_allow={},
        gt_to_hint={"x": "x"},
        date_fields=frozenset(),
        hybrid=None,
    )
    shape, legs, notes = apply_guards(pack, "x", "oneshot", frozenset({"gliner", "hybrid"}))
    assert "hybrid" not in legs


def test_clause_then_pick_sources_exclude_clause_from_pick():
    pack = TENDER_PACK
    r = heuristic_recipe(pack, "minimum_tender_condition", oracle_system="Qwen clauses")
    assert r.shape == "clause_then_pick"
    pol = recipe_to_policy(pack, r)
    assert pol.stages[0].sources == ("clause",)
    assert "clause" not in pol.stages[1].sources
    assert "hybrid" in pol.stages[1].sources or "gliner" in pol.stages[1].sources


def test_route_fields_heuristic_mode():
    recipes = route_fields(TENDER_PACK, ("cusip", "expiration_date"), mode="heuristic")
    assert recipes["cusip"].source == "heuristic"
    assert "temporal" in recipes["expiration_date"].legs


def test_pack_with_recipes_overrides_policies():
    recipes = route_fields(TENDER_PACK, ("cusip",), mode="heuristic")
    pack2 = pack_with_recipes(TENDER_PACK, recipes)
    assert "cusip" in pack2.policies
    assert pack2.policies["cusip"].stages[0].sources == ("rules",)


def test_mock_laya_combo_hybrid_temporal():
    pack = TENDER_PACK
    result = LayaResult(
        answers={
            "shape": LayaAnswer(
                name="shape", type="choice", value="oneshot", confidence=0.85,
                probabilities={"oneshot": 0.9},
            ),
            "use_rules": LayaAnswer(name="use_rules", type="noul", value=0.1, confidence=0.9),
            "use_gliner": LayaAnswer(name="use_gliner", type="noul", value=0.2, confidence=0.9),
            "use_temporal": LayaAnswer(name="use_temporal", type="noul", value=0.9, confidence=0.9),
            "use_hybrid": LayaAnswer(name="use_hybrid", type="noul", value=0.85, confidence=0.9),
            "use_clause": LayaAnswer(name="use_clause", type="noul", value=0.05, confidence=0.9),
        }
    )
    rec = _parse_answers_to_recipe(
        pack, "expiration_date", result, oracle_system="Temporal NER", noul_threshold=0.5
    )
    assert rec.source == "laya"
    assert rec.legs == frozenset({"temporal", "hybrid"})
    pol = recipe_to_policy(pack, rec)
    assert pol.stages[0].sources == ("temporal", "hybrid")


def test_laya_fallback_on_failure():
    with patch(
        "src.evaluation.extract.laya_client.laya_configured", return_value=True
    ), patch(
        "src.evaluation.extract.laya_client.route_field_laya",
        side_effect=RuntimeError("down"),
    ):
        recipes = route_fields(TENDER_PACK, ("cusip",), mode="laya")
    assert recipes["cusip"].source == "heuristic"
    assert "laya_failed" in recipes["cusip"].rationale
