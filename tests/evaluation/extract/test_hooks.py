from __future__ import annotations

from src.evaluation.action_packs.base import ActionPack, PackHooks
from src.evaluation.action_packs.merger import MERGER_PACK
from src.evaluation.action_packs.tender import TENDER_PACK
from src.evaluation.extract import evidence as ev
from src.evaluation.extract.policies import resolve_policy


def _pack(hooks=None) -> ActionPack:
    return ActionPack(
        name="fake",
        fields=("a", "b", "ratio"),
        field_defs={},
        field_pick={},
        hint_allow={"a": frozenset({"a"}), "b": frozenset({"b"}), "ratio": frozenset({"ratio"})},
        gt_to_hint={"a": "a", "b": "b", "ratio": "ratio"},
        date_fields=frozenset(),
        hooks=hooks,
    )


def _sp(hint, text):
    return {"field_hint": hint, "label": hint, "text": text}


def test_junk_roles_come_only_from_pack_hooks():
    spans = [_sp("a", "Parent"), _sp("a", "Acme")]
    assert len(ev.gliner_lines(_pack(), spans, "a")) == 2
    h = PackHooks(junk_roles=frozenset({"parent"}))
    lines = ev.gliner_lines(_pack(h), spans, "a")
    assert len(lines) == 1 and "Acme" in lines[0]


def test_drop_span_called_with_extras():
    seen = []

    def drop(field, raw, extras):
        seen.append((field, raw, dict(extras)))
        return raw == "X"

    p = _pack(PackHooks(drop_span=drop))
    lines = ev.gliner_lines(p, [_sp("a", "X"), _sp("a", "Y")], "a", extras={"k": "v"})
    assert len(lines) == 1 and "'Y'" in lines[0]
    assert seen[0] == ("a", "X", {"k": "v"})


def test_rules_prelude_prepended_for_target_only():
    p = _pack(PackHooks(rules_prelude=lambda f, e: ["- p"] if f == "a" else []))
    assert ev.rules_prelude_lines(p, "a", {}) == ["- p"]
    assert ev.rules_prelude_lines(p, "b", {}) == []
    assert ev.rules_prelude_lines(_pack(), "a", {}) == []


def test_synth_spans_only_when_no_ratio_spans():
    def synth(f, gl, spans, extras):
        return ["- s"] if f == "ratio" and not gl else []

    p = _pack(PackHooks(synth_spans=synth))
    assert ev.synth_lines(p, "ratio", [], [], {}) == ["- s"]
    assert ev.synth_lines(p, "ratio", ["x"], [], {}) == []
    assert ev.synth_lines(_pack(), "ratio", [], [], {}) == []


def test_pack_without_hooks_behaves_as_before():
    spans = [_sp("a", "Parent"), _sp("a", "Acme")]
    assert ev.gliner_lines(_pack(), spans, "a") == ev.gliner_lines(
        _pack(PackHooks()), spans, "a"
    )


def test_resolve_policy_adds_prior_stage_only_with_direct_prior_hook():
    base = resolve_policy(_pack(), "a", cascade=True)
    assert [s.name for s in base.stages] == ["rules", "span"]
    p = _pack(PackHooks(direct_prior=lambda f, e: None, prior_label="P"))
    pol = resolve_policy(p, "a", cascade=True)
    assert [s.name for s in pol.stages] == ["prior", "rules", "span"]
    st = pol.stages[0]
    assert st.sources == ("prior",) and st.on_empty == "skip" and st.pass_label == "P"
    assert st.direct_from_rules and st.direct_label == "P" and not st.validate
    assert [s.name for s in resolve_policy(p, "a", cascade=False).stages] == ["oneshot"]
    assert [s.name for s in resolve_policy(_pack(PackHooks()), "a", cascade=True).stages] == [
        "rules",
        "span",
    ]


EX = {"primary_entity": "Acme Corp"}


def _m(field, hint, text):
    return {"field_hint": hint, "label": hint, "text": text}


def test_merger_acquirer_drops_primary_entity_and_junk():
    spans = [_m("acquirer", "acquirer", t) for t in ("Acme Corporation", "Parent", "Merger Sub", "Beta Inc")]
    lines = ev.gliner_lines(MERGER_PACK, spans, "acquirer", extras=EX)
    assert len(lines) == 1 and "Beta Inc" in lines[0]
    # no extras: primary-entity drop does not fire
    assert len(ev.gliner_lines(MERGER_PACK, spans, "acquirer")) == 2


def test_merger_target_prelude_and_direct_prior():
    h = MERGER_PACK.hooks
    px = {**EX, "is_proxy_filing": "1"}
    assert ev.rules_prelude_lines(MERGER_PACK, "target", px) == [
        "- hint=primary_entity method=inventory value='Acme Corp'"
    ]
    assert ev.rules_prelude_lines(MERGER_PACK, "acquirer", px) == []
    assert ev.rules_prelude_lines(MERGER_PACK, "target", {}) == []
    proxy = {**EX, "is_proxy_filing": "1"}
    assert h.direct_prior("target", proxy) == "Acme Corp"
    assert h.direct_prior("target", EX) is None  # not a proxy filing
    assert h.direct_prior("target", {"is_proxy_filing": "1"}) is None
    assert h.direct_prior("acquirer", proxy) is None
    assert h.prior_label == "A_inventory"
    assert h.prior_hint == "primary_entity"


def test_merger_extras_from_inventory():
    fn = MERGER_PACK.hooks.extras_from_inventory
    assert fn(
        {"primary_entity": " Acme Corp ", "docs": [{"form": "8-K"}, {"file_type": "defm14a"}]}
    ) == {"primary_entity": "Acme Corp", "is_proxy_filing": "1"}
    assert fn({"primary_entity": "Acme", "docs": [{"form": "PREM14C"}]})["is_proxy_filing"] == "1"
    assert fn({"primary_entity": "Acme", "docs": [{"form": "S-4"}]}) == {
        "primary_entity": "Acme", "is_proxy_filing": "0"
    }
    empty = {"primary_entity": "", "is_proxy_filing": "0"}
    assert fn({}) == empty
    # malformed docs: legacy behaviour drops everything
    assert fn({"primary_entity": "Acme", "docs": ["DEFM14A"]}) == empty
    assert TENDER_PACK.hooks is None or TENDER_PACK.hooks.extras_from_inventory is None


def test_merger_policy_prior_stage_for_all_fields():
    assert resolve_policy(MERGER_PACK, "target", cascade=True).stages[0].name == "prior"


def test_merger_synth_no_stock_consideration():
    cash = [_m("cash_consideration", "cash_consideration", "$5.00 per share")]
    out = ev.synth_lines(MERGER_PACK, "stock_exchange_ratio", [], cash, EX)
    assert len(out) == 1 and "No stock consideration" in out[0]
    assert ev.synth_lines(MERGER_PACK, "stock_exchange_ratio", [], [], EX) == []
    assert ev.synth_lines(MERGER_PACK, "stock_exchange_ratio", ["r"], cash, EX) == []
    assert ev.synth_lines(MERGER_PACK, "target", [], cash, EX) == []


def test_tender_pack_drops_parent_span_for_legacy_parity():
    field = next(f for f in TENDER_PACK.fields if f in TENDER_PACK.hint_allow)
    hint = sorted(TENDER_PACK.hint_allow[field])[0]
    spans = [_m(field, hint, "Parent"), _m(field, hint, "Zeta Holdings")]
    lines = ev.gliner_lines(TENDER_PACK, spans, field)
    assert len(lines) == 1 and "Zeta Holdings" in lines[0]
    assert [s.name for s in resolve_policy(TENDER_PACK, field, cascade=True).stages][0] != "prior"


def _synth(*extra, cash_text="$5.00 per share"):
    cash = _m("cash_consideration", "cash_consideration", cash_text)
    return ev.synth_lines(MERGER_PACK, "stock_exchange_ratio", [], [cash, *extra], EX)


def test_merger_synth_stockish_guard_matches_legacy():
    assert len(_synth()) == 1
    assert _synth({"label": "stock_exchange"}) == []
    assert _synth({"field_hint": "exchange_ratio", "label": "x"}) == []
    assert _synth({"label": "x", "text": "the Exchange Ratio"}) == []
    assert _synth({"label": "x", "text": "mixed consideration"}) == []
    # "shares of" alone does not suppress; with "per share" it does
    assert len(_synth({"label": "x", "text": "shares of Acme"}, cash_text="$5 cash")) == 1
    assert _synth({"label": "x", "text": "shares of Acme"}) == []
    # legacy joins only `text` for texts: a label-only "exchange ratio" does not suppress
    assert len(_synth({"label": "exchange ratio"})) == 1


def test_merger_prelude_and_prior_require_proxy_filing():
    h = MERGER_PACK.hooks
    nonproxy = {**EX, "is_proxy_filing": "0"}
    assert ev.rules_prelude_lines(MERGER_PACK, "target", nonproxy) == []
    assert ev.rules_prelude_lines(MERGER_PACK, "target", EX) == []
    assert h.direct_prior("target", nonproxy) is None
    proxy = {**EX, "is_proxy_filing": "1"}
    assert len(ev.rules_prelude_lines(MERGER_PACK, "target", proxy)) == 1
