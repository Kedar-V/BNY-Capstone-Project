"""Hybrid BM25+dense retrieval (offline unit tests; dense mocked / BM25-only)."""

from __future__ import annotations

from src.evaluation.action_packs.base import ActionPack, HybridSpec
from src.evaluation.extract.hybrid import (
    bm25_rank,
    chunk_text,
    field_query,
    hybrid_retrieve,
    reset_dense_circuit,
    rrf,
)
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EventContext, build_bundle


def test_chunk_text_overlap_and_short():
    assert chunk_text("") == []
    assert chunk_text("short enough", chunk_chars=900) == ["short enough"]
    blob = ("word " * 400).strip()
    parts = chunk_text(blob, chunk_chars=100, overlap=20)
    assert len(parts) >= 2
    assert all(len(p) <= 100 for p in parts)


def test_bm25_ranks_relevant_chunk_first():
    chunks = [
        "The Fund maintains a minimum account balance of $10,000.",
        "The Offer is conditioned upon a minimum tender condition of a majority of Shares.",
        "CUSIP Number of Class of Securities 123456789.",
    ]
    ranked = bm25_rank("minimum tender condition majority shares", chunks)
    assert ranked and ranked[0][0] == 1


def test_rrf_fuses_legs():
    # idx 0 ranks 2nd + 1st; idx 1 ranks 1st + 2nd → 0 wins on tie-break by index
    fused = rrf([[1, 0, 2], [0, 1]], limit=3, k=60)
    assert [i for i, _ in fused] == [0, 1, 2]


def test_hybrid_retrieve_bm25_only_formats_block():
    reset_dense_circuit()
    doc = (
        "SUMMARY. The Offer expires at 5:00 p.m. New York City time on March 3, 2026. "
        "Shareholders may withdraw tendered Shares until the expiration time. "
        "Payment for Shares will be made promptly after acceptance. "
        "The purchase price is $12.50 per Share in cash. "
    ) * 3
    block, vectors = hybrid_retrieve(
        "offer will expire expiration time",
        doc,
        top_k=2,
        max_chars=800,
        use_dense=False,
    )
    assert block.startswith("HYBRID EXCERPTS:\n")
    assert "expire" in block.lower() or "expiration" in block.lower()
    assert vectors is None


def test_field_query_merges_def_and_extra():
    q = field_query("The price paid per share.", "offer_price", extra="purchase price cash")
    assert "offer price" in q and "purchase price cash" in q


def test_resolve_policy_injects_hybrid_when_pack_enables():
    pack = ActionPack(
        name="fake",
        fields=("name", "deadline"),
        field_defs={},
        field_pick={},
        hint_allow={},
        gt_to_hint={},
        date_fields=frozenset({"deadline"}),
        hybrid=HybridSpec(use_dense=False),
    )
    oneshot = resolve_policy(pack, "name", cascade=False).stages[0]
    assert oneshot.sources == ("rules", "gliner", "hybrid")
    _, span = resolve_policy(pack, "deadline", cascade=True).stages
    assert span.sources == ("gliner", "temporal", "hybrid")
    # rules-only stage stays rules-only
    rules = resolve_policy(pack, "name", cascade=True).stages[0]
    assert rules.sources == ("rules",)


def test_build_bundle_appends_hybrid_next_to_gliner():
    reset_dense_circuit()
    pack = ActionPack(
        name="fake",
        fields=("offer_price",),
        field_defs={"offer_price": "cash price per share"},
        field_pick={},
        hint_allow={"offer_price": frozenset({"offer_price", "price"})},
        gt_to_hint={"offer_price": "offer_price"},
        date_fields=frozenset(),
        hybrid=HybridSpec(use_dense=False, top_k=2, max_chars=600),
    )
    ctx = EventContext(
        excerpts="The purchase price is $12.50 per Share in cash consideration.",
        doc_text="The purchase price is $12.50 per Share in cash consideration. " * 5,
        spans=[{"field_hint": "offer_price", "label": "price", "text": "$12.50", "score": 0.9}],
    )
    bundle = build_bundle(pack, ctx, "offer_price", ("rules", "gliner", "hybrid"))
    assert "GLINER SPANS" in bundle.text
    assert "HYBRID EXCERPTS" in bundle.text
    assert "$12.50" in bundle.text
