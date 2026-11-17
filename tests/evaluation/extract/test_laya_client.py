"""Unit tests for LayaClient (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.extract.laya_client import (
    LayaClient,
    LayaResult,
    _parse_result,
    truncate_state,
)


def test_truncate_state():
    assert truncate_state("short") == "short"
    long = "x" * 5000
    out = truncate_state(long, max_chars=100)
    assert len(out) <= 100
    assert out.endswith("…[truncated]")


def test_parse_result_choice_noul_score():
    body = {
        "answers": {
            "a": {
                "type": "choice",
                "choice": "oneshot",
                "confidence": 0.9,
                "probabilities": {"oneshot": 0.9, "clause_only": 0.1},
            },
            "b": {"type": "noul", "noul": 0.82, "confidence": 0.75},
            "c": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.6,
                "probabilities": {"low": 0.1, "mid": 0.2, "high": 0.7},
            },
        },
        "model": "systemone",
    }
    res = _parse_result(body)
    assert isinstance(res, LayaResult)
    assert res.choice("a") == "oneshot"
    assert res.noul("b") == pytest.approx(0.82)
    assert res.score("c") == pytest.approx(2.0)
    assert res.answers["c"].needs_review  # conf 0.6 < 0.7 default
    assert not res.answers["a"].needs_review


def test_decide_and_batch_preserve_order():
    cli = LayaClient(base_url="http://laya.test", max_in_flight=1, batch_size=4)

    single_body = {
        "answers": {"tone": {"type": "choice", "choice": "neutral", "confidence": 0.8}}
    }
    batch_body = {
        "results": [
            {"answers": {"tone": {"type": "choice", "choice": f"c{i}", "confidence": 0.8}}}
            for i in range(3)
        ]
    }

    with patch.object(cli, "_post_json") as post:
        post.return_value = single_body
        r = cli.decide("hello", {"tone": {"type": "choice", "instructions": "x", "criteria": {}}})
        assert r.choice("tone") == "neutral"
        post.assert_called_once()
        assert post.call_args.args[0] == "/v1/systemone"

        post.reset_mock()
        post.return_value = batch_body
        states = ["a", "b", "c"]
        out = cli.decide_batch(states, {"tone": {"type": "choice", "instructions": "x", "criteria": {}}})
        assert [x.choice("tone") for x in out] == ["c0", "c1", "c2"]
        post.assert_called_once()
        assert post.call_args.args[0] == "/v1/systemone/batch"
        assert post.call_args.args[1]["states"] == states


def test_health():
    cli = LayaClient(base_url="http://laya.test")
    mock_resp = MagicMock()
    mock_resp.content = b'{"status":"ok","checkpoints":["a.pt"]}'
    mock_resp.json.return_value = {"status": "ok", "checkpoints": ["a.pt"]}
    mock_resp.raise_for_status = MagicMock()
    with patch("src.evaluation.extract.laya_client.requests.get", return_value=mock_resp) as get:
        h = cli.health()
        assert h["checkpoints"] == ["a.pt"]
        get.assert_called_once()
        assert get.call_args.args[0] == "http://laya.test/health"
