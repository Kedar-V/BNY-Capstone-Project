from __future__ import annotations

from src.preprocess.rules_ids import find_ticker, find_tickers


def test_find_ticker_prefers_target_over_acquirer_under_symbol():
    text = (
        "Parent Real Brokerage Inc. trades on the NYSE under the symbol “REAX.” "
        "Company common stock trades on the NYSE under the symbol “RMAX.” "
        "Holders of our common stock will vote on the merger."
    )
    assert find_ticker(text) == "RMAX"
    assert find_tickers(text, limit=2)[0] == "RMAX"


def test_find_tickers_multi_symbol_line():
    text = "Trading Symbols: ABCU, ABCUR, ABCWU\nOther noise NYSE: PRNT appears later."
    assert find_tickers(text, limit=1) == ["ABCU, ABCUR, ABCWU"]
