from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Mapping

import pytest

from fakes import FakeBackend, FakeProvider
from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec, PackHooks
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.providers import ArtifactProvider, EventContext
from src.preprocess.store import ArtifactStore

NO_EVIDENCE = "(no rules/GLiNER/temporal evidence for this field)"
LONG_QUOTE = "If more than the maximum number of shares are tendered, pro rata applies to all."


def _prior(field: str, extras: Mapping[str, str]) -> str | None:
    pe = (extras.get("primary_entity") or "").strip()
    return pe if field == "target" and pe and extras.get("is_proxy_filing") == "1" else None


def _prelude(field: str, extras: Mapping[str, str]) -> list[str]:
    v = _prior(field, extras)
    return [f"- hint=primary_entity method=inventory value={v!r}"] if v else []


def _synth(field, gliner, spans, extras):
    if field != "ratio" or gliner or not spans:
        return []
    return ["- hint=ratio value='None' note='synth'"]


def _pack(*, hooks: PackHooks | None = None, validate=frozenset({"name", "clause_f", "ticker"})):
    fields = ("name", "ticker", "deadline", "clause_f", "target", "ratio", "other")
    return ActionPack(
        name="fake",
        fields=fields,
        field_defs={f: f"def of {f}" for f in fields},
        field_pick={},
        hint_allow={f: frozenset({f}) for f in fields},
        gt_to_hint={f: f for f in fields},
        date_fields=frozenset({"deadline"}),
        temporal_cues={"deadline": ("expire",)},
        validate_fields=frozenset(validate),
        clause_fields={
            "clause_f": ClauseFieldSpec(
                quote_field="q",
                patterns=(r"(if more than[^.]{20,}\.)",),
                extract_prompt="COPY {field}: {excerpt}",
            )
        },
        hooks=hooks,
    )


def _req(field: str, *, acc="acc1", cascade=True, validate=False) -> FieldExtractRequest:
    return FieldExtractRequest(
        pack_name="fake",
        field=field,
        event_id=None,
        accession=acc,
        model="m",
        validate_enabled=validate,
        cascade=cascade,
    )


def _rule(hint: str, raw: str) -> dict:
    return {"method": "rules", "field_hint": hint, "raw": raw}


def _span(hint: str, text: str, score=0.9) -> dict:
    return {"field_hint": hint, "label": hint, "text": text, "score": score}


def _run(pack, backend, ctx: EventContext, field: str, **kw):
    provider = FakeProvider({kw.pop("acc", "acc1"): ctx})
    g = build_extract_graph(pack, backend, provider)
    return run_field(g, _req(field, **kw)), provider


# --- clause --------------------------------------------------------------------


def test_clause_miss_no_llm_call():
    be = FakeBackend([])
    ctx = EventContext(rep={"candidate_facts": [_rule("clause_f", "x")]})
    res, _ = _run(_pack(), be, ctx, "clause_f")
    assert be.calls == []
    assert res.pred is None
    assert res.pass_used == "clause_miss"
    assert res.n_evidence_chars == 0
    assert res.n_rules == 1
    assert res.raw_llm == ""


def test_clause_hit_uses_copy_prompt_and_normalizes():
    be = FakeBackend([json.dumps({"clause_f": "  pro\n rata\xa0 applies "})])
    ctx = EventContext(passages={"q": [{"quote": LONG_QUOTE}]})
    res, _ = _run(_pack(), be, ctx, "clause_f")
    assert be.prompts == [f"COPY clause_f: {LONG_QUOTE}"]
    assert res.pred == "pro rata applies"
    assert res.pass_used == "clause"
    assert res.n_evidence_chars == len("EXCERPT:\n" + LONG_QUOTE)
    assert res.raw_llm.startswith("clause:{")


def test_clause_null_label_and_regex_from_excerpts():
    be = FakeBackend(['{"clause_f": null}'])
    ctx = EventContext(excerpts="blah. " + LONG_QUOTE.lower() + " tail")
    res, _ = _run(_pack(), be, ctx, "clause_f")
    assert res.pass_used == "clause_null"
    assert res.pred is None
    assert "if more than" in be.prompts[0]


# --- cascade -------------------------------------------------------------------


def test_direct_rules_field_skips_llm():
    be = FakeBackend([])
    ctx = EventContext(rep={"candidate_facts": [_rule("ticker", " AB\nC ")]})
    res, _ = _run(_pack(), be, ctx, "ticker")
    assert be.calls == []
    assert res.pred == "AB C"
    assert res.pass_used == "A_rules"
    assert res.raw_llm == "A_rules:'AB C'"
    assert res.n_evidence_chars == len("RULES:\n- hint=ticker value='AB\\nC'")
    assert res.n_rules == 1


def test_direct_rules_field_validated_when_in_validate_fields():
    be = FakeBackend(['{"keep": true}'])
    ctx = EventContext(rep={"candidate_facts": [_rule("ticker", "ABC")]})
    res, _ = _run(_pack(), be, ctx, "ticker", validate=True)
    assert res.pass_used == "A_rules+C_keep"
    assert res.validate_verdict is True
    assert be.calls[0]["system"] == "Return JSON only. Be conservative: drop unsupported values."
    assert "CANDIDATE: 'ABC'" in be.prompts[0]


def test_cascade_falls_from_A_to_B_labels():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("name", "Acme Rules")]},
        spans=[_span("name", "Acme Span")],
    )
    be = FakeBackend(['{"name": null}', '{"name": "Acme Span"}'])
    res, _ = _run(_pack(), be, ctx, "name")
    assert res.pass_used == "B"
    assert res.pred == "Acme Span"
    assert "RULES:\n- hint=name value='Acme Rules'" in be.prompts[0]
    assert "GLINER SPANS:\n- hint=name score=0.90 value='Acme Span'" in be.prompts[1]
    assert res.raw_llm == 'A:{"name": null} | B:{"name": "Acme Span"}'
    assert res.n_rules == 1

    be2 = FakeBackend(['{"name": null}', '{"name": null}'])
    res2, _ = _run(_pack(), be2, ctx, "name")
    assert res2.pass_used == "B_null"
    assert res2.pred is None

    be3 = FakeBackend(['{"name": "Acme Rules"}'])
    res3, _ = _run(_pack(), be3, ctx, "name")
    assert res3.pass_used == "A"
    assert len(be3.calls) == 1


def test_cascade_A_null_then_empty_B_keeps_A_label():
    ctx = EventContext(rep={"candidate_facts": [_rule("name", "Acme")]})
    be = FakeBackend(['{"name": null}'])
    res, _ = _run(_pack(), be, ctx, "name")
    assert len(be.calls) == 1
    assert res.pass_used == "A"
    assert res.pred is None
    assert res.n_evidence_chars == len(NO_EVIDENCE)


def test_cascade_no_rules_no_evidence_is_empty():
    be = FakeBackend([])
    res, _ = _run(_pack(), be, EventContext(), "name")
    assert be.calls == []
    assert res.pass_used == "empty"
    assert res.pred is None
    assert res.n_evidence_chars == len(NO_EVIDENCE)
    assert res.n_rules == 0
    assert res.raw_llm == ""


def test_b_pick_not_validated_unless_field_in_validate_fields():
    ctx = EventContext(spans=[_span("other", "X")])
    be = FakeBackend(['{"other": "X"}'])
    res, _ = _run(_pack(), be, ctx, "other", validate=True)
    assert res.pass_used == "B"
    assert len(be.calls) == 1
    assert res.validate_verdict is None


# --- oneshot -------------------------------------------------------------------


def test_oneshot_empty_evidence_still_calls_llm():
    be = FakeBackend(['{"name": "Ghost"}'])
    res, _ = _run(_pack(), be, EventContext(), "name", cascade=False)
    assert len(be.calls) == 1
    assert "Evidence pack is empty for this field" in be.prompts[0]
    assert res.pass_used == "oneshot"
    assert res.pred == "Ghost"
    assert res.n_evidence_chars == len(NO_EVIDENCE)


def test_oneshot_null_label_is_oneshot():
    be = FakeBackend(["nope"])
    res, _ = _run(_pack(), be, EventContext(), "name", cascade=False)
    assert res.pass_used == "oneshot"
    assert res.pred is None


def test_oneshot_date_field_includes_temporal_block():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("deadline", "May 1")]},
        spans=[_span("deadline", "May 2")],
        temporal_cache={"deadline": ["- date='May 3' label=DATE field_cues=1 window='x'"]},
    )
    be = FakeBackend(['{"deadline": "May 1"}'])
    res, _ = _run(_pack(), be, ctx, "deadline", cascade=False)
    ev = be.prompts[0].split("EVIDENCE:\n", 1)[1]
    assert ev == (
        "RULES:\n- hint=deadline value='May 1'\n\n"
        "GLINER SPANS:\n- hint=deadline score=0.90 value='May 2'\n\n"
        "TEMPORAL SPANS:\n- date='May 3' label=DATE field_cues=1 window='x'\n"
    )


# --- validate ------------------------------------------------------------------


def test_validate_drop_sets_pred_none_and_label():
    ctx = EventContext(spans=[_span("name", "Acme")])
    be = FakeBackend(['{"name": "Acme"}', '{"keep": false}'])
    res, _ = _run(_pack(), be, ctx, "name", validate=True)
    assert res.pred is None
    assert res.pass_used == "B+C_drop"
    assert res.validate_verdict is False
    assert res.raw_llm == 'B:{"name": "Acme"} | C:{"keep": false}'

    be2 = FakeBackend(['{"name": "Acme"}', '{"keep": true}'])
    res2, _ = _run(_pack(), be2, ctx, "name", validate=True)
    assert (res2.pred, res2.pass_used) == ("Acme", "B+C_keep")

    be3 = FakeBackend(['{"name": "Acme"}', "{broken json"])
    res3, _ = _run(_pack(), be3, ctx, "name", validate=True)
    assert (res3.pred, res3.pass_used) == ("Acme", "B")
    assert res3.validate_verdict is None


def test_validate_uses_normalized_pred_and_final_evidence():
    ctx = EventContext(spans=[_span("name", "Acme")])
    be = FakeBackend(['{"name": " Ac\\nme "}', '{"keep": true}'])
    res, _ = _run(_pack(), be, ctx, "name", validate=True)
    assert "CANDIDATE: 'Ac me'" in be.prompts[1]
    assert be.prompts[1].endswith("EVIDENCE:\nGLINER SPANS:\n- hint=name score=0.90 value='Acme'\n")
    assert res.pred == "Ac me"


# --- explicit multi-stage policy, stop_at_first_hit=False ------------------------


def _two_stage_pack(*, validate_first: bool = True) -> ActionPack:
    from dataclasses import replace

    from src.evaluation.extract.policies import FieldPolicy, Stage

    def stage(name, sources, label, validate):
        return Stage(
            name=name, sources=sources, prompt_mode="pick", on_empty="skip",
            pass_label=label, null_label=f"{label}_null", direct_from_rules=False,
            validate=validate,
        )

    policy = FieldPolicy(
        stages=(
            stage("r1", ("rules",), "R1", validate_first),
            stage("r2", ("gliner",), "R2", False),
        ),
        stop_at_first_hit=False,
    )
    return replace(_pack(), policies={"name": policy})


RULES_EV = "RULES:\n- hint=name value='Acme'"


def test_no_stop_later_null_keeps_earlier_hit():
    ctx = EventContext(rep={"candidate_facts": [_rule("name", "Acme")]}, spans=[_span("name", "Other")])
    be = FakeBackend(['{"name": " Acme "}', '{"name": null}'])
    res, _ = _run(_two_stage_pack(), be, ctx, "name")
    assert len(be.calls) == 2
    assert res.pred == "Acme"
    assert res.pass_used == "R1"
    assert res.n_evidence_chars == len(RULES_EV)
    assert res.raw_llm == 'R1:{"name": " Acme "} | R2:{"name": null}'


def test_no_stop_validate_uses_producing_stage_evidence():
    ctx = EventContext(rep={"candidate_facts": [_rule("name", "Acme")]}, spans=[_span("name", "Other")])
    be = FakeBackend(['{"name": "Acme"}', '{"name": null}', '{"keep": true}'])
    res, _ = _run(_two_stage_pack(), be, ctx, "name", validate=True)
    assert res.pass_used == "R1+C_keep"
    assert be.prompts[2].endswith(f"EVIDENCE:\n{RULES_EV}\n")
    assert "GLINER SPANS" not in be.prompts[2]


def test_no_stop_later_empty_stage_keeps_hit_evidence():
    ctx = EventContext(rep={"candidate_facts": [_rule("name", "Acme")]})
    be = FakeBackend(['{"name": "Acme"}'])
    res, _ = _run(_two_stage_pack(), be, ctx, "name")
    assert len(be.calls) == 1
    assert (res.pred, res.pass_used) == ("Acme", "R1")
    assert res.n_evidence_chars == len(RULES_EV)


def test_no_stop_later_hit_replaces_earlier_hit_and_its_evidence():
    ctx = EventContext(rep={"candidate_facts": [_rule("name", "Acme")]}, spans=[_span("name", "Other")])
    be = FakeBackend(['{"name": "Acme"}', '{"name": "Other"}'])
    res, _ = _run(_two_stage_pack(validate_first=True), be, ctx, "name", validate=True)
    # stage 2 (validate=False) produced the pred, so Pass C does not run
    assert len(be.calls) == 2
    assert (res.pred, res.pass_used) == ("Other", "R2")
    assert res.n_evidence_chars == len("GLINER SPANS:\n- hint=name score=0.90 value='Other'")


# --- temporal gate -------------------------------------------------------------


def test_non_date_field_never_requests_temporal():
    ctx = EventContext(
        spans=[_span("name", "Acme")],
        temporal_cache={"name": ["- date='bogus'"], "deadline": ["- date='May 3'"]},
    )
    for cascade in (True, False):
        be = FakeBackend(fn=lambda s, u, m: '{"name": null}')
        res, prov = _run(_pack(), be, ctx, "name", cascade=cascade)
        assert all("temporal" not in src for _, src in prov.bundle_calls)
        assert all("TEMPORAL" not in p for p in be.prompts)
    be = FakeBackend(fn=lambda s, u, m: '{"deadline": null}')
    _, prov = _run(_pack(), be, ctx, "deadline")
    assert ("deadline", ("gliner", "temporal")) in prov.bundle_calls


def test_artifact_provider_skips_temporal_for_non_date_fields(tmp_path):
    seen = []

    def tf(key, excerpts, fields):
        seen.append((key, fields))
        return {f: ["- date='x'"] for f in fields}

    pack = _pack()
    store = ArtifactStore("fake", tmp_path)
    row = {"accession_number": "acc1", "passages": json.dumps({"name": [{"quote": "Acme"}]})}
    prov = ArtifactProvider(pack, store, None, event_id_for=lambda r: "e1", temporal_for=tf)
    prov.prepare([row], ("name", "other"))
    assert seen == []
    prov.prepare([row], ("name", "deadline"))
    assert seen == [("e1", ("deadline",))]
    assert prov.context(_req("name")).temporal_cache == {"deadline": ["- date='x'"]}


# --- errors / robustness ---------------------------------------------------------


def test_backend_exception_returns_error_result():
    ctx = EventContext(spans=[_span("name", "Acme")])
    be = FakeBackend([RuntimeError("boom " + "x" * 600)])
    res, _ = _run(_pack(), be, ctx, "name")
    assert res.pred is None
    assert res.pass_used == "error"
    assert res.raw_llm == ("boom " + "x" * 600)[:400]
    assert (res.n_evidence_chars, res.n_rules) == (0, 0)


def test_unprepared_event_returns_error_result(tmp_path):
    prov = ArtifactProvider(_pack(), ArtifactStore("fake", tmp_path), None, event_id_for=lambda r: None)
    g = build_extract_graph(_pack(), FakeBackend([]), prov)
    res = run_field(g, _req("name", acc="never"))
    assert res.pass_used == "error"
    assert "never" in res.raw_llm


def test_missing_artifacts_returns_null_no_raise(tmp_path):
    pack = _pack()
    prov = ArtifactProvider(pack, ArtifactStore("fake", tmp_path), None, event_id_for=lambda r: "e404")
    prov.prepare([{"accession_number": "acc1"}], pack.fields)
    g = build_extract_graph(pack, FakeBackend([]), prov)
    for field in ("name", "ticker", "deadline", "clause_f"):
        res = run_field(g, _req(field))
        assert res.pred is None
        assert res.pass_used in {"empty", "clause_miss"}


def test_malformed_llm_output_is_null():
    ctx = EventContext(spans=[_span("name", "Acme")])
    for raw in ("not json at all", "[1, 2]", '{"other": "x"}', '{"name": "N/A"}', ""):
        be = FakeBackend([raw])
        res, _ = _run(_pack(), be, ctx, "name")
        assert res.pred is None
        assert res.pass_used == "B_null"


def test_concurrent_invocations_isolated():
    fields = [f"name{i}" for i in range(16)]
    pack = ActionPack(
        name="fake",
        fields=tuple(fields),
        field_defs={},
        field_pick={},
        hint_allow={f: frozenset({f}) for f in fields},
        gt_to_hint={f: f for f in fields},
        date_fields=frozenset(),
    )
    ctx = EventContext(spans=[_span(f, f"value-{f}") for f in fields])

    def reply(system, user, model):
        field = user.split("`", 2)[1]
        return json.dumps({field: f"value-{field}"})

    be = FakeBackend(fn=reply)
    g = build_extract_graph(pack, be, FakeProvider({"acc1": ctx}))
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda f: (f, run_field(g, _req(f))), fields))
    assert len(be.calls) == 16
    for f, res in results:
        assert res.pred == f"value-{f}"
        assert res.pass_used == "B"
        assert res.raw_llm == f'B:{{"{f}": "value-{f}"}}'


# --- pack hooks ----------------------------------------------------------------

def _extras(inv: Mapping) -> dict[str, str]:
    forms = " ".join(str(d.get("form") or d.get("file_type") or "") for d in inv.get("docs") or [])
    return {
        "primary_entity": str(inv.get("primary_entity") or "").strip(),
        "is_proxy_filing": "1" if "14a" in forms.lower() else "0",
    }


HOOKS = PackHooks(
    rules_prelude=_prelude,
    direct_prior=_prior,
    synth_spans=_synth,
    prior_hint="primary_entity",
    extras_from_inventory=_extras,
)
PROXY = {"primary_entity": "Target Co", "is_proxy_filing": "1"}


def test_prior_stage_fires_on_proxy_with_primary_entity():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("target", "Other")]},
        spans=[_span("target", "Other")],
        extras=PROXY,
    )
    be = FakeBackend([])
    res, _ = _run(_pack(hooks=HOOKS), be, ctx, "target")
    assert be.calls == []
    assert res.pred == "Target Co"
    assert res.pass_used == "A_inventory"
    assert res.raw_llm == "A_inventory:'Target Co'"
    assert res.n_evidence_chars == len("RULES:\n- hint=primary_entity value='Target Co'")
    assert res.n_rules == 1


def test_prior_evidence_hint_comes_from_pack_hooks():
    from dataclasses import replace

    ctx = EventContext(extras=PROXY)
    res, _ = _run(_pack(hooks=replace(HOOKS, prior_hint="registrant")), FakeBackend([]), ctx, "target")
    assert res.pass_used == "A_inventory"
    assert res.n_evidence_chars == len("RULES:\n- hint=registrant value='Target Co'")
    default = PackHooks(direct_prior=_prior)
    res2, _ = _run(_pack(hooks=default), FakeBackend([]), ctx, "target")
    assert res2.n_evidence_chars == len("RULES:\n- hint=prior value='Target Co'")


@pytest.mark.parametrize(
    "extras",
    [
        {"primary_entity": "Target Co", "is_proxy_filing": "0"},
        {"primary_entity": "", "is_proxy_filing": "1"},
        {},
    ],
)
def test_prior_stage_skipped_without_proxy_or_entity(extras):
    ctx = EventContext(spans=[_span("target", "Span Co")], extras=extras)
    be = FakeBackend(['{"target": "Span Co"}'])
    res, _ = _run(_pack(hooks=HOOKS), be, ctx, "target")
    assert res.pass_used == "B"
    assert res.pred == "Span Co"
    assert "primary_entity" not in be.prompts[0]


def test_prior_stage_absent_in_oneshot_but_prelude_leads_rules_block():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("target", "Other")]},
        extras=PROXY,
    )
    be = FakeBackend(['{"target": "Target Co"}'])
    res, _ = _run(_pack(hooks=HOOKS), be, ctx, "target", cascade=False)
    assert res.pass_used == "oneshot"
    ev = be.prompts[0].split("EVIDENCE:\n", 1)[1]
    assert ev == (
        "RULES:\n- hint=primary_entity method=inventory value='Target Co'\n"
        "- hint=target value='Other'\n"
    )
    assert res.n_rules == 1


def test_prelude_alone_makes_rules_block():
    ctx = EventContext(extras=PROXY)
    be = FakeBackend(['{"target": "Target Co"}'])
    _run(_pack(hooks=HOOKS), be, ctx, "target", cascade=False)
    ev = be.prompts[0].split("EVIDENCE:\n", 1)[1]
    assert ev == "RULES:\n- hint=primary_entity method=inventory value='Target Co'\n"


def test_synth_block_wrapped_as_gliner_spans_only_when_gliner_active():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("ratio", "1:1")]},
        spans=[_span("unrelated", "x")],
    )
    be = FakeBackend(['{"ratio": null}', '{"ratio": "No ratio"}'])
    res, _ = _run(_pack(hooks=HOOKS), be, ctx, "ratio")
    # Pass A (rules only): no synth block
    assert "GLINER SPANS" not in be.prompts[0]
    # Pass B (gliner): synth wrapped in its own GLINER SPANS block
    ev_b = be.prompts[1].split("EVIDENCE:\n", 1)[1]
    assert ev_b == "GLINER SPANS:\n- hint=ratio value='None' note='synth'\n"
    assert res.pass_used == "B"


def test_synth_block_follows_rules_in_oneshot():
    ctx = EventContext(
        rep={"candidate_facts": [_rule("ratio", "1:1")]},
        spans=[_span("unrelated", "x")],
    )
    be = FakeBackend(['{"ratio": "1:1"}'])
    _run(_pack(hooks=HOOKS), be, ctx, "ratio", cascade=False)
    ev = be.prompts[0].split("EVIDENCE:\n", 1)[1]
    assert ev == (
        "RULES:\n- hint=ratio value='1:1'\n\n"
        "GLINER SPANS:\n- hint=ratio value='None' note='synth'\n"
    )


# --- ArtifactProvider ------------------------------------------------------------


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_artifact_provider_reads_artifacts_and_extras(tmp_path):
    pack = _pack(hooks=HOOKS)
    store = ArtifactStore("fake", tmp_path)
    ev_dir = tmp_path / "fake" / "events" / "e1"
    _write(ev_dir / "concise" / "event_rep.json", {"candidate_facts": [_rule("name", "Acme")]})
    _write(ev_dir / "spans.json", {"spans": [_span("name", "Acme Span")]})
    _write(
        ev_dir / "segments.json",
        {"segments": [
            {"kind": "full_doc", "heading": "Body", "text": "body text"},
            {"kind": "faq", "heading": "Q", "text": "faq text"},
        ]},
    )
    _write(
        ev_dir / "inventory.json",
        {"primary_entity": " Target Co ", "docs": [{"form": "8-K"}, {"file_type": "defm14a"}]},
    )
    prov = ArtifactProvider(pack, store, None, event_id_for=lambda r: "e1")
    prov.prepare([{"accession_number": "acc1", "passages": '{"name": [{"quote": "Q1"}]}'}], ("name",))
    ctx = prov.context(_req("name"))
    assert ctx.rep["candidate_facts"][0]["raw"] == "Acme"
    assert ctx.spans[0]["text"] == "Acme Span"
    assert ctx.excerpts == "[q]\nfaq text\n\n---\n\n[body]\nbody text"
    assert ctx.doc_text == "body text\n\nfaq text"
    assert ctx.passages == {"name": [{"quote": "Q1"}]}
    assert dict(ctx.extras) == {"primary_entity": "Target Co", "is_proxy_filing": "1"}
    assert prov.n_rules(ctx, "name", pack) == 1
    assert prov.rules_direct(ctx, "name", pack) == ["Acme"]


def test_artifact_provider_passages_fill_missing_spans_and_excerpts(tmp_path):
    pack = _pack()
    store = ArtifactStore("fake", tmp_path)
    row = {"accession_number": "acc1", "passages": json.dumps({"Name": [{"quote": "Acme Q"}, "bad"]})}
    prov = ArtifactProvider(pack, store, None, event_id_for=lambda r: None)
    prov.prepare([row], pack.fields)
    ctx = prov.context(_req("name"))
    assert ctx.spans == [
        {"field_hint": "name", "label": "name", "text": "Acme Q", "passage": "Acme Q", "score": 1.0}
    ]
    assert ctx.excerpts == "[Name]\nAcme Q"
    assert ctx.doc_text == ""
    # no extras_from_inventory hook -> no extras
    assert dict(ctx.extras) == {}


def test_artifact_provider_extras_hook_sees_inventory_or_empty(tmp_path):
    seen: list[dict] = []

    def extras(inv):
        seen.append(dict(inv))
        return {"k": str(inv.get("primary_entity", "-"))}

    pack = _pack(hooks=PackHooks(extras_from_inventory=extras))
    store = ArtifactStore("fake", tmp_path)
    _write(tmp_path / "fake" / "events" / "e1" / "inventory.json", {"primary_entity": "X"})
    (tmp_path / "fake" / "events" / "e2").mkdir(parents=True)
    (tmp_path / "fake" / "events" / "e2" / "inventory.json").write_text("not json", encoding="utf-8")
    _write(tmp_path / "fake" / "events" / "e3" / "inventory.json", ["a list"])
    eids = {"a1": "e1", "a2": "e2", "a3": "e3", "a4": "e404", "a5": None}
    prov = ArtifactProvider(pack, store, None, event_id_for=lambda r: eids[r["accession_number"]])
    prov.prepare([{"accession_number": a} for a in eids], ("name",))
    got = {a: dict(prov.context(_req("name", acc=a)).extras) for a in eids}
    assert got == {"a1": {"k": "X"}, "a2": {"k": "-"}, "a3": {"k": "-"}, "a4": {"k": "-"}, "a5": {"k": "-"}}
    assert seen == [{"primary_entity": "X"}, {}, {}, {}, {}]


def test_artifact_provider_key_for_separates_rows_sharing_an_accession(tmp_path):
    pack = _pack()
    rows = [
        {"accession_number": "acc1", "_i": "0", "passages": json.dumps({"name": [{"quote": "One"}]})},
        {"accession_number": "acc1", "_i": "1", "passages": json.dumps({"name": [{"quote": "Two"}]})},
    ]
    prov = ArtifactProvider(
        pack, ArtifactStore("fake", tmp_path), None,
        event_id_for=lambda r: None, key_for=lambda r: f"{r['accession_number']}#{r['_i']}",
    )
    assert prov.prepare(rows, ("name",)) == ["acc1#0", "acc1#1"]
    assert prov.context(_req("name", acc="acc1#1")).spans[0]["text"] == "Two"
    assert prov.context(_req("name", acc="acc1#0")).spans[0]["text"] == "One"


def test_artifact_provider_duplicate_key_with_different_passages_raises(tmp_path):
    rows = [
        {"accession_number": "acc1", "passages": json.dumps({"name": [{"quote": "One"}]})},
        {"accession_number": "acc1", "passages": json.dumps({"name": [{"quote": "Two"}]})},
    ]
    prov = ArtifactProvider(_pack(), ArtifactStore("fake", tmp_path), None, event_id_for=lambda r: None)
    with pytest.raises(ValueError, match="'acc1'.*key_for"):
        prov.prepare(rows, ("name",))


def test_artifact_provider_duplicate_key_with_identical_passages_ok(tmp_path):
    passages = json.dumps({"name": [{"quote": "Same"}]})
    rows = [
        {"accession_number": "acc1", "passages": passages, "name": "a"},
        {"accession_number": "acc1", "passages": passages, "name": "b"},
    ]
    prov = ArtifactProvider(_pack(), ArtifactStore("fake", tmp_path), None, event_id_for=lambda r: None)
    assert prov.prepare(rows, ("name",)) == ["acc1", "acc1"]
    assert prov.context(_req("name")).spans[0]["text"] == "Same"
    # re-preparing the same rows is fine too
    prov.prepare(rows, ("name",))


def test_default_temporal_for_without_tagger_is_empty():
    from src.evaluation.extract.temporal import default_temporal_for, precompute_temporal

    assert default_temporal_for(_pack(), None)("k", "expires May 1, 2026", ("deadline",)) == {}
    assert precompute_temporal(_pack(), object(), "text", ("name",)) == {}
