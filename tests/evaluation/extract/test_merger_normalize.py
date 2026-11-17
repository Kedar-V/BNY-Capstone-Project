from __future__ import annotations

from src.evaluation.action_packs.merger import MERGER_PACK, _merger_normalize


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
