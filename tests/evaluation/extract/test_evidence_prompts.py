from __future__ import annotations

from dataclasses import replace

from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec, PackHooks
from src.evaluation.extract import evidence as ev
from src.evaluation.extract.prompts import parse_field, parse_keep, select_prompt, validate_prompt


def _pack() -> ActionPack:
    return ActionPack(
        name="fake",
        fields=("ticker", "settlement_date", "clause_f"),
        field_defs={"ticker": "Stock ticker", "clause_f": "A clause"},
        field_pick={"ticker": "Pick the ticker."},
        hint_allow={"ticker": frozenset({"ticker", "symbol"})},
        gt_to_hint={"ticker": "ticker", "settlement_date": "settlement_date"},
        date_fields=frozenset(),
        clause_fields={
            "clause_f": ClauseFieldSpec(
                quote_field="q", patterns=("x",), extract_prompt="F={field} X={excerpt}"
            )
        },
    )


REP = {
    "candidate_facts": [
        {"method": "rules", "field_hint": "Ticker", "raw": "ABC", "passage": "sym\nABC here"},
        {"method": "rules", "field_hint": "symbol", "value": "XYZ"},
        {"method": "rules", "field_hint": "cusip", "raw": "123"},
        {"method": "gliner", "field_hint": "ticker", "raw": "NOPE"},
    ]
}


def test_rules_lines_exact():
    assert ev.rules_lines(_pack(), REP, "ticker", "") == [
        "- hint=ticker value='ABC' context='sym ABC here'",
        "- hint=symbol value='XYZ'",
    ]


def test_rules_raw_values():
    assert ev.rules_raw_values(_pack(), REP, "ticker", "") == ["ABC", "XYZ"]


def test_settlement_excerpt():
    ex = "Payment will be made promptly after the offer expires."
    assert ev.rules_lines(_pack(), {}, "settlement_date", ex) == [
        "- hint=settlement_date method=settlement_template value='Payment: promptly'"
    ]
    assert ev.rules_raw_values(_pack(), {}, "settlement_date", ex) == ["Payment: promptly"]


def test_gliner_lines_allowed_and_cap():
    spans = [
        {"label": "ticker", "text": "ABC", "score": 0.9, "passage": "a\nb"},
        {"label": "person", "text": "Bob"},
    ]
    assert ev.gliner_lines(_pack(), spans, "ticker") == [
        "- hint=ticker score=0.90 value='ABC' context='a b'"
    ]
    many = [{"label": "ticker", "text": f"T{i}"} for i in range(40)]
    assert len(ev.gliner_lines(_pack(), many, "ticker")) == ev.MAX_GLINER == 25


def test_gliner_junk_and_label_suffix():
    spans = [
        {"label": "ticker", "text": "Parent"},
        {"field_hint": "ticker", "label": "ticker_symbol", "text": "Q"},
    ]
    # junk roles come only from the pack's hooks (default: none)
    assert len(ev.gliner_lines(_pack(), spans, "ticker")) == 2
    p = replace(_pack(), hooks=PackHooks(junk_roles=frozenset({"parent"})))
    assert ev.gliner_lines(p, spans, "ticker") == [
        "- hint=ticker label=ticker_symbol value='Q'"
    ]


def test_cue_score():
    assert ev.cue_score("a b c", ("a", "c", "z")) == 2


def test_parse_field():
    assert parse_field('{"ticker": "ABC"}', "ticker") == "ABC"
    assert parse_field('```json\n{"ticker": "ABC"}\n```', "ticker") == "ABC"
    assert parse_field('<think>hm</think>{"ticker": "ABC"}', "ticker") == "ABC"
    assert parse_field('{"ticker": "N/A"}', "ticker") is None
    assert parse_field('{"value": "V"}', "ticker") == "V"
    assert parse_field("garbage", "ticker") is None
    assert parse_field('{"ticker": null}', "ticker") is None


def test_parse_keep():
    assert parse_keep("garbage") is None
    assert parse_keep('{"keep": false}') is False
    assert parse_keep('{"keep": true}') is True
    assert parse_keep('{"x": 1}') is None


def test_select_prompt_empty_evidence():
    p = select_prompt(_pack(), "ticker", "(no rules evidence)", mode="pick")
    assert "return null" in p and "(no rules evidence)" in p


def test_select_prompt_pick():
    p = select_prompt(_pack(), "ticker", "- hint=ticker value='A'", mode="pick")
    assert p.startswith("Extract `ticker` from the evidence pack below.")
    assert "- Pick the ticker." in p and p.endswith("EVIDENCE:\n- hint=ticker value='A'\n")


def test_select_prompt_election_deadline_abstains():
    p = select_prompt(
        _pack(),
        "election_deadline",
        "- hint=election_deadline date='2026-01-01'",
        mode="pick",
    )
    assert "If none clearly match the DEFINITION, return null" in p
    assert "Do NOT return null if at least one listed value" not in p


def test_select_prompt_party_rejects_bare_roles():
    p = select_prompt(_pack(), "acquirer", "- hint=acquirer value='Holdco'", mode="pick")
    assert "NEVER return bare role nouns" in p
    assert "Holdco" in p


def test_select_prompt_includes_field_shots():
    from src.evaluation.action_packs.base import FieldShot
    from dataclasses import replace

    p0 = _pack()
    pack = replace(
        p0,
        field_shots={
            "ticker": (
                FieldShot(
                    evidence="- hint=ticker value='AAAA'\n- hint=ticker value='BBBB'",
                    answer="AAAA",
                    note="target not acquirer",
                ),
            )
        },
    )
    p = select_prompt(pack, "ticker", "- hint=ticker value='ZZZZ'", mode="pick")
    assert "EXAMPLES" in p
    assert '→ {"ticker": "AAAA"}' in p
    assert "target not acquirer" in p


def test_select_prompt_copy():
    assert select_prompt(_pack(), "clause_f", "RAW", mode="copy") == "F=clause_f X=RAW"


def test_validate_prompt():
    p = validate_prompt(_pack(), "ticker", "ABC", "ev")
    assert "CANDIDATE: 'ABC'" in p and p.endswith("EVIDENCE:\nev\n")
    assert "target/subject issuer ticker" in p


def test_validate_prompt_consideration_type():
    p = validate_prompt(_pack(), "consideration_type", "Cash", "ev")
    assert "conversion/exchange-ratio" in p
