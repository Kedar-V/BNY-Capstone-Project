"""Tender retrieval config: clause specs, two-stage fall-through, temporal knobs, scope.

Synthetic SEC-like text only (no GT rows). Covers the ``# --- tender retrieval config``
block of src/evaluation/action_packs/tender.py and the generic temporal knobs.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
from pathlib import Path

import pytest

from fakes import FakeBackend, FakeProvider
from src.evaluation.action_packs import MERGER_PACK, TENDER_PACK
from src.evaluation.action_packs.base import ActionPack
from src.evaluation.action_packs.retrieve import retrieve_clause
from src.evaluation.extract import temporal as T
from src.evaluation.extract.dtos import FieldExtractRequest
from src.evaluation.extract.graph import build_extract_graph, run_field
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EventContext

ROOT = Path(__file__).resolve().parents[3]
MIN = "minimum_tender_condition"
SEC = "security_description"


def _retrieve(field: str, text: str) -> str:
    spec = TENDER_PACK.clause_fields[field]
    return retrieve_clause(spec, passages={}, excerpts=text, doc_text=text)


# --- clause specs on synthetic SEC-like text -------------------------------------------

THIRD_PARTY = (
    "SUMMARY TERM SHEET. The Offer is conditioned upon, among other things, there being "
    "validly tendered and not validly withdrawn prior to the Expiration Time a number of "
    "Shares that, together with Shares then owned by Parent, represents at least a majority "
    "of the Shares then outstanding (the “ Minimum Condition ”). See Section 15."
)
SELF_TENDER_NO_MIN = (
    "The Fund is offering to repurchase up to 5% of its outstanding Shares. The Offer is "
    "being made to all shareholders and is not conditioned upon any minimum number of\n"
    "Shares being tendered. If more than 5% of the Shares are tendered, the Fund may "
    "repurchase Shares on a pro rata basis."
)
NO_MINIMUM_PHRASE = (
    "Section 7. Certain Conditions of the Offer. There is no minimum amount of Units that "
    "must be tendered for the Fund to complete the Offer, but the Fund may cancel the Offer "
    "in the circumstances described below."
)
FUND_BALANCE_ONLY = (
    "You must maintain a minimum account balance of at least $10,000 as of the Valuation "
    "Date. If a repurchase would cause your account to fall below the required minimum "
    "balance, the Fund may reduce the amount repurchased. The minimum initial investment is "
    "$25,000."
)


def test_min_tender_hit_on_defined_term():
    got = _retrieve(MIN, THIRD_PARTY)
    assert "at least a majority" in got and "Minimum Condition" in got


@pytest.mark.parametrize("text, needle", [
    (SELF_TENDER_NO_MIN, "not conditioned upon any minimum number of Shares"),
    (NO_MINIMUM_PHRASE, "no minimum amount of Units"),
])
def test_min_tender_absence_statement(text, needle):
    got = _retrieve(MIN, text)
    assert needle in got  # whitespace collapsed: "number of\nShares" still matches


def test_min_tender_miss_on_account_balance_minimums():
    assert _retrieve(MIN, FUND_BALANCE_ONLY) == ""


COVER = (
    "SCHEDULE TO TENDER OFFER STATEMENT UNDER SECTION 14(d)(1) OR 13(e)(1) OF THE "
    "SECURITIES EXCHANGE ACT OF 1934 EXAMPLE INCOME FUND (Name of Subject Company (Issuer)) "
    "EXAMPLE INCOME FUND (Name of Filing Person(s) (Issuer))\n"
    "CLASS I SHARES OF BENEFICIAL INTEREST\n(Title of Class of Securities)\n"
    "123456789 (CUSIP Number of Class of Securities)"
)
OFFER_INTRO = (
    "Example Holdings, Inc., a Delaware corporation, is offering to purchase for cash up to "
    "1,000,000 shares of its common stock, par value $0.001 per share (the “Shares”), "
    "at a price of $10.00 per Share."
)


def test_security_hit_on_cover_caption():
    got = _retrieve(SEC, COVER)
    assert got.endswith("(Title of Class of Securities)")
    assert "CLASS I SHARES OF BENEFICIAL INTEREST" in got
    assert "Name of Subject Company" in got  # issuer caption kept in the window


def test_security_hit_on_defined_term_when_no_cover():
    got = _retrieve(SEC, OFFER_INTRO)
    assert "common stock, par value $0.001 per share" in got
    assert got.endswith("“Shares”)")


def test_security_cover_outranks_defined_term():
    got = _retrieve(SEC, OFFER_INTRO + " " + COVER)
    assert "(Title of Class of Securities)" in got and "offering to purchase" not in got


def test_security_miss():
    assert _retrieve(SEC, FUND_BALANCE_ONLY) == ""


def test_clause_prompts_are_generic_and_format():
    for field in (MIN, SEC):
        prompt = TENDER_PACK.clause_fields[field].extract_prompt.format(excerpt="EX", field=field)
        assert prompt.rstrip().endswith("EXCERPT:\nEX")
        assert f'{{"{field}": null}}' in prompt
        assert "exact phrase" in prompt
    assert '"No minimum tender condition"' in TENDER_PACK.clause_fields[MIN].extract_prompt
    # no GT passage quotes (gold-derived) for the new clause fields
    assert not TENDER_PACK.clause_fields[MIN].use_passage_quotes
    assert not TENDER_PACK.clause_fields[SEC].use_passage_quotes


# --- two-stage policy: clause first, then the existing oneshot pick ------------------


def _req(field: str, *, cascade: bool = False) -> FieldExtractRequest:
    return FieldExtractRequest(pack_name="tender", field=field, event_id=None, accession="a",
                               model="m", validate_enabled=True, cascade=cascade)


# Graph tests: keep hybrid in sources, but BM25-only so CI never hits the embed host.
_PACK_BM25 = dataclasses.replace(
    TENDER_PACK, hybrid=dataclasses.replace(TENDER_PACK.hybrid, use_dense=False)
)


def _run(ctx: EventContext, field: str, replies, *, cascade=False):
    be = FakeBackend(replies)
    prov = FakeProvider({"a": ctx})
    res = run_field(build_extract_graph(_PACK_BM25, be, prov), _req(field, cascade=cascade))
    return res, be, prov


SPAN_CTX = dict(spans=[{"field_hint": "security_description", "label": "security_description",
                        "text": "common stock", "score": 0.9}])


@pytest.mark.parametrize("field", [MIN, SEC])
def test_policy_shape(field):
    for cascade in (True, False):
        pol = resolve_policy(TENDER_PACK, field, cascade=cascade)
        assert [s.name for s in pol.stages] == ["clause", "oneshot"]
        clause, pick = pol.stages
        assert clause.sources == ("clause",) and clause.on_empty == "skip"
        assert clause.prompt_mode == "copy" and pick.prompt_mode == "pick"
        assert pick.sources == ("rules", "gliner", "hybrid") and pick.on_empty == "ask"
        assert pol.stop_at_first_hit
        assert clause.validate is pick.validate is (field in TENDER_PACK.validate_fields)


@pytest.mark.parametrize("cascade", [False, True])
def test_empty_clause_falls_through_to_stage_two(cascade):
    ctx = EventContext(excerpts=FUND_BALANCE_ONLY, doc_text=FUND_BALANCE_ONLY, **SPAN_CTX)
    res, be, prov = _run(ctx, SEC, [json.dumps({SEC: "common stock"})], cascade=cascade)
    assert res.pred == "common stock" and res.pass_used == "oneshot"
    assert [s for _, s in prov.bundle_calls] == [("clause",), ("rules", "gliner", "hybrid")]
    assert len(be.calls) == 1 and "EXCERPT:" not in be.prompts[0]
    assert "GLINER SPANS" in res.evidence


def test_empty_clause_and_no_spans_still_asks_like_oneshot():
    ctx = EventContext(excerpts=FUND_BALANCE_ONLY, doc_text=FUND_BALANCE_ONLY)
    res, be, _ = _run(ctx, MIN, [json.dumps({MIN: None})])
    assert res.pred is None and res.pass_used == "oneshot" and len(be.calls) == 1


def test_clause_hit_short_circuits():
    ctx = EventContext(excerpts=COVER, doc_text=COVER, **SPAN_CTX)
    res, be, prov = _run(ctx, SEC, [json.dumps({SEC: "CLASS I SHARES OF BENEFICIAL INTEREST"})])
    assert res.pred == "CLASS I SHARES OF BENEFICIAL INTEREST" and res.pass_used == "clause"
    assert [s for _, s in prov.bundle_calls] == [("clause",)]  # stage 2 never built
    assert len(be.calls) == 1 and "(Title of Class of Securities)" in be.prompts[0]
    assert res.evidence.startswith("EXCERPT:\n")


def test_clause_absence_answer_short_circuits():
    ctx = EventContext(excerpts=SELF_TENDER_NO_MIN, doc_text=SELF_TENDER_NO_MIN)
    res, be, _ = _run(ctx, MIN, [json.dumps({MIN: "No minimum tender condition"})])
    assert res.pred == "No minimum tender condition" and res.pass_used == "clause"
    assert len(be.calls) == 1


def test_clause_null_answer_falls_through():
    ctx = EventContext(excerpts=COVER, doc_text=COVER, **SPAN_CTX)
    res, be, prov = _run(ctx, SEC, [json.dumps({SEC: None}), json.dumps({SEC: "common stock"})])
    assert res.pred == "common stock" and res.pass_used == "oneshot"
    assert [s for _, s in prov.bundle_calls] == [("clause",), ("rules", "gliner", "hybrid")]


def test_other_fields_keep_derived_policies():
    # settlement_date has its own gated v2 cascade (see test_settlement_gate_graph.py)
    assert set(TENDER_PACK.policies) == {MIN, SEC, "settlement_date"}
    # proration stays the legacy clause-only (null on miss) policy
    pol = resolve_policy(TENDER_PACK, "proration_terms", cascade=False)
    assert [(s.name, s.on_empty) for s in pol.stages] == [("clause", "null")]


# --- temporal knobs ---------------------------------------------------------------------


class _FakeTagger:
    """Stands in for the tagger helper module: two distinct DATE spans per chunk."""

    def __init__(self):
        self.chunks: list[str] = []

    def extract_timex(self, tagger, chunk):
        self.chunks.append(chunk)
        i = len(self.chunks)
        return [{"text": f"date number {i}{k}", "label": "DATE", "start": 0, "end": 5} for k in "ab"]

    @staticmethod
    def _window(text, start, end, radius=120):
        return text[:20].lower()


@pytest.fixture
def fake_tagger(monkeypatch):
    fake = _FakeTagger()
    monkeypatch.setattr(T, "_module", fake)
    return fake


def test_knob_defaults_unchanged():
    base = ActionPack(name="x", fields=("d",), field_defs={}, field_pick={}, hint_allow={},
                      gt_to_hint={}, date_fields=frozenset({"d"}))
    assert (base.temporal_scan_chars, base.temporal_max_spans) == (12_000, 25)
    assert base.temporal_scan_is_default
    assert (MERGER_PACK.temporal_scan_chars, MERGER_PACK.temporal_max_spans) == (12_000, 25)
    assert MERGER_PACK.policies == {}
    with pytest.raises(ValueError):
        dataclasses.replace(base, temporal_scan_chars=0)


def test_default_scan_reads_first_12000_chars_and_caps_25(fake_tagger):
    excerpts = "x" * 30_000
    out = T.precompute_temporal(MERGER_PACK, object(), excerpts, tuple(MERGER_PACK.date_fields))
    assert len(fake_tagger.chunks) == 7  # range(0, 12000, 1800)
    assert all(len(lines) == 14 for lines in out.values())
    many = dataclasses.replace(MERGER_PACK, temporal_scan_chars=60_000)
    fake_tagger.chunks.clear()
    out = T.precompute_temporal(many, object(), excerpts, tuple(MERGER_PACK.date_fields))
    assert len(fake_tagger.chunks) == 17  # whole 30k excerpt
    assert all(len(lines) == 25 for lines in out.values())  # default cap


def test_tender_scan_covers_full_excerpts(fake_tagger):
    excerpts = "y" * 24_000
    out = T.precompute_temporal(TENDER_PACK, object(), excerpts, ("expiration_date",))
    assert len(fake_tagger.chunks) == 14  # range(0, 24000, 1800)
    assert len(out["expiration_date"]) == 28  # under the tender cap of 40 (default cap: 25)
    fake_tagger.chunks.clear()
    lines = T.temporal_lines(TENDER_PACK, object(), excerpts, "expiration_date")
    assert len(lines) == 28 and len(fake_tagger.chunks) == 14
    capped = dataclasses.replace(TENDER_PACK, temporal_max_spans=3)
    assert len(T.precompute_temporal(capped, object(), excerpts, ("expiration_date",))
               ["expiration_date"]) == 3


# --- scope: tender retrieval strings live only in the tender pack ---------------------

_TENDER_RETRIEVAL_MARKERS = (
    "Minimum Condition",
    "Minimum Tender Condition",
    "Title of Class",
    r"title\s+of\s+class",
    r"minimum\s+(?:tender\s+)?condition",
    r"not\s+(?:be\s+)?(?:conditioned",
)


def test_tender_retrieval_strings_only_in_tender_pack():
    tender = ROOT / "src/evaluation/action_packs/tender.py"
    hits: dict[str, list[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        found = [m for m in _TENDER_RETRIEVAL_MARKERS if m in text]
        if found:
            hits[str(path.relative_to(ROOT))] = found
    assert set(hits) == {str(tender.relative_to(ROOT))}, hits
    text = tender.read_text(encoding="utf-8")
    start = text.index("# --- tender retrieval config (tune here) ---")
    end = text.index("# --- end tender retrieval config")
    for marker in _TENDER_RETRIEVAL_MARKERS:
        idx = [m.start() for m in re.finditer(re.escape(marker), text)]
        assert idx and all(start < i < end for i in idx), marker


def test_parity_scope_excludes_only_explicit_policy_fields():
    spec = importlib.util.spec_from_file_location(
        "parity_under_test", Path(__file__).with_name("test_parity_legacy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(TENDER_PACK.fields) - set(mod.parity_fields(TENDER_PACK)) == {MIN, SEC, "settlement_date"}
    assert mod.parity_fields(MERGER_PACK) == MERGER_PACK.fields
