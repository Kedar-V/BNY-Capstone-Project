"""Unit tests for tender preprocess helpers, ranking, and stages."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.preprocess.backends import FakeSpanBackend, iter_windows
from src.preprocess.contracts import StageContext
from src.preprocess.paths.tender import classify_doc_role, select_priority_docs
from src.preprocess.span_rank import dedupe_nms, is_label_like, rank_score
from src.preprocess.stages.assemble import AssembleStage
from src.preprocess.stages.cleanup import strip_sec_wrapper
from src.preprocess.stages.gliner_ie import GlinerStage
from src.preprocess.stages.inventory import InventoryStage
from src.preprocess.stages.segment import segment_faq, segment_toc
from src.preprocess.store import ArtifactStore


FIXTURE_OTP = """
<html><body>
<a name="toc">TABLE OF CONTENTS</a>
<a href="#sts">Summary</a>
<a name="sts"><b>SUMMARY TERM SHEET</b></a>
<p><b>How much are they offering to pay?</b></p>
<p>We are offering to pay $18.75 per Share, net to you in cash.</p>
<p><b>When does the Offer expire?</b></p>
<p>The Offer expires on February 19, 2020.</p>
<a name="intro"><b>INTRODUCTION</b></a>
<p>This Offer to Purchase relates to Dermira, Inc. common stock.</p>
</body></html>
"""


def test_strip_sec_wrapper():
    raw = "<DOCUMENT><TYPE>EX-99\n<TEXT>\n<html>hi</html>\n</TEXT></DOCUMENT>"
    assert "hi" in strip_sec_wrapper(raw)
    assert "<DOCUMENT>" not in strip_sec_wrapper(raw)


def test_classify_doc_role():
    role, method = classify_doc_role(
        {"form": "SC TO-T", "is_primary_form_doc": True, "is_exhibit": False, "file_type": "", "file_description": ""}
    )
    assert role == "cover"
    role, method = classify_doc_role(
        {
            "form": "SC TO-T",
            "is_exhibit": True,
            "file_type": "EX-99.(A)(1)(A)",
            "file_description": "OFFER TO PURCHASE",
            "is_primary_form_doc": False,
        }
    )
    assert role == "otp"
    assert method == "file_description"


def test_select_priority_docs_gold():
    docs = pd.DataFrame(
        [
            {
                "hit_id": "1",
                "event_id": "005-1",
                "accession": "a1",
                "filename": "cover.htm",
                "form": "SC TO-T",
                "file_type": "",
                "file_description": "",
                "is_primary_form_doc": True,
                "is_exhibit": False,
                "is_amendment": False,
                "file_date": "2020-01-01",
                "primary_cik": "1",
            },
            {
                "hit_id": "2",
                "event_id": "005-1",
                "accession": "a1",
                "filename": "otp.htm",
                "form": "SC TO-T",
                "file_type": "EX-99.(A)(1)(A)",
                "file_description": "OFFER TO PURCHASE",
                "is_primary_form_doc": False,
                "is_exhibit": True,
                "is_amendment": False,
                "file_date": "2020-01-01",
                "primary_cik": "1",
            },
            {
                "hit_id": "3",
                "event_id": "005-1",
                "accession": "a2",
                "filename": "14d9.htm",
                "form": "SC 14D9",
                "file_type": "",
                "file_description": "",
                "is_primary_form_doc": True,
                "is_exhibit": False,
                "is_amendment": False,
                "file_date": "2020-01-02",
                "primary_cik": "1",
            },
        ]
    )
    out = select_priority_docs(docs)
    assert out["cohort"] == "gold"
    assert out["has_otp"] and out["has_cover"] and out["has_14d9"]


def test_toc_priority_and_faq():
    toc = segment_toc(FIXTURE_OTP, "otp")
    assert any(s.get("priority") or s.get("kind") == "priority_section" for s in toc)
    faq = segment_faq(FIXTURE_OTP, "otp")
    assert len(faq) >= 1
    assert any("pay" in (f.get("question") or "").lower() for f in faq)


def test_iter_windows_and_ranker():
    text = "a" * 5000
    wins = iter_windows(text, window_chars=900, overlap_chars=150, max_windows=8)
    assert len(wins) >= 2
    assert wins[0][1] == 0
    assert all(len(w[0]) <= 900 for w in wins[:-1])

    assert is_label_like("Offer Price")
    assert not is_label_like("$18.75")
    heading = {"label": "offer_price_amount", "text": "Offer Price", "score": 0.95}
    value = {"label": "offer_price_amount", "text": "$18.75", "score": 0.70}
    assert rank_score(value) > rank_score(heading)
    ranked = dedupe_nms([heading, value])
    assert ranked[0]["text"] == "$18.75"

    agent = {"label": "offeror_organization", "text": "Computershare Trust Company, N.A.", "score": 0.95, "doc_role": "otp"}
    party = {"label": "offeror_organization", "text": "Vega MergerCo, Inc.", "score": 0.90, "doc_role": "otp"}
    assert rank_score(party) > rank_score(agent)
    parties = dedupe_nms([agent, party])
    assert parties[0]["text"] == "Vega MergerCo, Inc."

    cover_cusip = {"label": "cusip_code", "text": "928703107", "score": 0.8, "doc_role": "cover"}
    otp_cusip = {"label": "cusip_code", "text": "928703107", "score": 0.8, "doc_role": "otp"}
    assert rank_score(cover_cusip) > rank_score(otp_cusip)


def test_quality_gates_on_fixture_rep():
    from src.preprocess.quality_gates import check_event_rep

    good = {
        "candidate_facts": [
            {
                "field_hint": "offer_price",
                "raw": "$18.75",
                "rank_score": 1.2,
                "method": "gliner",
                "passage": "x" * 350,
            },
            {
                "field_hint": "expiration_date",
                "raw": "February 19, 2020",
                "rank_score": 1.1,
                "method": "gliner",
                "passage": "y" * 350,
            },
            {
                "field_hint": "offeror",
                "raw": "Eli Lilly and Company",
                "rank_score": 1.0,
                "method": "gliner",
                "passage": "z" * 350,
            },
        ]
    }
    assert check_event_rep(good)["ok"]

    bad = {
        "candidate_facts": [
            {"field_hint": "offer_price", "raw": "Offer Price", "rank_score": 1.0, "method": "gliner", "passage": "a" * 50},
            {
                "field_hint": "offeror",
                "raw": "Computershare Trust Company, N.A.",
                "rank_score": 1.0,
                "method": "gliner",
                "passage": "b" * 50,
            },
        ]
    }
    r = check_event_rep(bad)
    assert not r["ok"]
    assert "top1_offer_price_not_money" in r["failures"]
    assert "top1_offeror_is_agent_or_shell" in r["failures"]


def test_gliner_always_pass2_on_priority(tmp_path: Path):
    store = ArtifactStore("tender", tmp_path)
    eid = "005-pass2"
    store.write_json(
        store.inventory_path(eid),
        {"event_id": eid, "cohort": "gold", "mvp_event_type": "tender_offer", "docs": []},
    )
    store.write_json(
        store.segments_path(eid),
        {
            "event_id": eid,
            "segments": [
                {
                    "segment_id": "otp:faq:0",
                    "doc_role": "otp",
                    "kind": "faq",
                    "priority": True,
                    "question": "How much?",
                    "heading": "How much?",
                    "text": "We are offering to pay $18.75 per Share. The Offer expires on February 19, 2020.",
                    "hit_id": "h1",
                    "accession": "acc",
                    "filename": "otp.htm",
                }
            ],
        },
    )
    backend = FakeSpanBackend(
        {
            "$18.75": [{"label": "offer_price_amount", "text": "$18.75", "score": 0.9}],
            "February 19, 2020": [{"label": "expiration_datetime", "text": "February 19, 2020", "score": 0.9}],
            "money": [{"label": "money_amount", "text": "$18.75", "score": 0.85}],
        }
    )
    ctx = StageContext(path_name="tender", preprocess_root=tmp_path, event_ids=[eid], show_progress=False)
    gr = GlinerStage(backend=backend).run(ctx)
    assert gr.status == "ok"
    assert gr.metrics.get("n_pass2_events") == 1
    spans = store.read_json(store.spans_path(eid))
    assert spans.get("pass2") is True



def test_gliner_assemble_ranks_values(tmp_path: Path):
    store = ArtifactStore("tender", tmp_path)
    eid = "005-test"
    inv = {
        "event_id": eid,
        "cohort": "gold",
        "mvp_event_type": "tender_offer",
        "has_14d9": True,
        "docs": [{"role": "otp", "hit_id": "h1", "accession": "acc", "filename": "otp.htm"}],
    }
    store.write_json(store.inventory_path(eid), inv)
    store.write_json(
        store.segments_path(eid),
        {
            "event_id": eid,
            "segments": [
                {
                    "segment_id": "otp:faq:0",
                    "doc_role": "otp",
                    "kind": "faq",
                    "priority": True,
                    "question": "How much?",
                    "heading": "How much?",
                    "text": "We are offering to pay $18.75 per Share of Dermira, Inc. The Offer expires on February 19, 2020.",
                    "hit_id": "h1",
                    "accession": "acc",
                    "filename": "otp.htm",
                }
            ],
        },
    )

    backend = FakeSpanBackend(
        {
            "$18.75": [
                {"label": "offer_price_amount", "text": "$18.75", "score": 0.70},
                {"label": "offer_price_amount", "text": "Offer Price", "score": 0.95},
            ],
            "February 19, 2020": [
                {"label": "expiration_datetime", "text": "February 19, 2020", "score": 0.80},
            ],
            "Dermira, Inc.": [
                {"label": "target_organization", "text": "Dermira, Inc.", "score": 0.84},
            ],
        }
    )
    ctx = StageContext(
        path_name="tender",
        preprocess_root=tmp_path,
        event_ids=[eid],
        show_progress=False,
    )
    gr = GlinerStage(backend=backend).run(ctx)
    assert gr.status == "ok"
    spans = store.read_json(store.spans_path(eid))["spans"]
    price = [s for s in spans if s.get("field_hint") == "offer_price"]
    assert price
    assert price[0]["text"] == "$18.75"
    assert "rank_score" in price[0]
    assert len(price[0].get("passage") or "") >= 40

    ar = AssembleStage().run(ctx)
    assert ar.status == "ok"
    rep = store.read_json(store.event_rep_path(eid))
    facts = [f for f in rep["candidate_facts"] if f["field_hint"] == "offer_price"]
    assert facts[0]["raw"] == "$18.75"
    assert all(f["method"] == "gliner" for f in rep["candidate_facts"])


def test_stub_path(tmp_path: Path):
    ctx = StageContext(path_name="exchange", preprocess_root=tmp_path, show_progress=False)
    r = InventoryStage().run(ctx)
    assert r.status == "stub_not_implemented"
