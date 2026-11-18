from __future__ import annotations

from src.evaluation.action_packs.merger import (
    MERGER_PACK,
    _merger_normalize,
    apply_cross_field_rules,
)


def test_merger_normalize_rejects_bare_party_roles():
    assert _merger_normalize("acquirer", "Holdco") == ""
    assert _merger_normalize("acquirer", "Parent") == ""
    assert _merger_normalize("target", "Company") == ""
    assert _merger_normalize("acquirer", "Odysseus Holdings Limited") == "Odysseus Holdings Limited"


def test_merger_normalize_ticker_and_absence_labels():
    assert _merger_normalize("ticker", "Nasdaq") == ""
    assert _merger_normalize("ticker", "RVYL") == "RVYL"
    assert _merger_normalize("stock_exchange_ratio", "'No stock consideration'") == (
        "No stock consideration"
    )
    assert _merger_normalize("cash_consideration", '"No cash consideration"') == (
        "No cash consideration"
    )


def test_merger_pack_uses_custom_normalize():
    assert MERGER_PACK.normalize("acquirer", "Holdco") == ""


def test_cross_field_sibling_fill_only_when_unanimous():
    acc = {1: "A", 2: "A", 3: "A", 4: "B", 5: "B", 6: "B"}
    preds = {
        (1, "shareholder_vote_date"): "",
        (2, "shareholder_vote_date"): "October 16, 2026",
        (3, "shareholder_vote_date"): "",
        (4, "consideration_type"): "Stock",
        (5, "consideration_type"): "Cash",
        (6, "consideration_type"): "",
        (1, "target"): "",
        (2, "target"): "Kestrel Inc.",
    }
    out = apply_cross_field_rules(preds, acc)
    assert out[(1, "shareholder_vote_date")] == "October 16, 2026"
    assert out[(3, "shareholder_vote_date")] == "October 16, 2026"
    assert out[(6, "consideration_type")] == ""
    assert out[(1, "target")] == ""


def test_cross_field_stock_means_no_cash():
    acc = {1: "A", 2: "B", 3: "B"}
    preds = {
        (1, "consideration_type"): "Stock",
        (1, "cash_consideration"): "$48.42",
        (2, "consideration_type"): "Mixed cash and stock",
        (2, "cash_consideration"): "$5.00 per share",
    }
    out = apply_cross_field_rules(preds, acc)
    assert out[(1, "cash_consideration")] == "No cash consideration"
    assert out[(2, "cash_consideration")] == "$5.00 per share"
