#!/usr/bin/env python3
"""Verify LayaClient against the live systemone server.

1) GET /health — print checkpoints
2) 8 texts: one batch vs 8 singles — answers must match; print timings
3) 6 labeled tender snippets × 3 noul phrasings — print accuracy per phrasing
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.llm_backends import load_dotenv  # noqa: E402
from src.evaluation.extract.laya_client import LayaClient  # noqa: E402

# Tone probe used for batch↔single parity (same question for every text).
TONE_Q = {
    "tone": {
        "type": "choice",
        "instructions": "Overall tone of the excerpt?",
        "criteria": {
            "positive": "growth, increase, raise, improve",
            "negative": "decline, lower, reduce, cut",
            "neutral": "no clear directional language",
        },
    }
}

# 8 short states for parity check
PARITY_STATES = [
    "Management raised full-year guidance and increased the dividend.",
    "The company lowered its outlook after weak demand.",
    "Shares were tendered pursuant to the Offer to Purchase.",
    "The Offer will expire at 5:00 p.m. New York City time on March 3, 2026.",
    "There is no minimum tender condition.",
    "If more Shares are tendered than the Fund will purchase, proration will apply.",
    "Payment for Shares will be made promptly after acceptance.",
    "CUSIP Number of Class of Securities: 123456789.",
]

# 6 labeled tender-ish snippets for phrasing sensitivity (gold = yes/no on min tender absence)
LABELED = [
    (
        "The Offer is not conditioned upon any minimum number of Shares being tendered.",
        True,
    ),
    (
        "There is no minimum tender condition to this Offer.",
        True,
    ),
    (
        "The Offer is conditioned upon there being validly tendered a majority of the Shares.",
        False,
    ),
    (
        "Minimum Condition means at least a majority of the outstanding Shares.",
        False,
    ),
    (
        "The Fund may cancel the Offer if fewer than the Minimum Condition Shares are tendered.",
        False,
    ),
    (
        "Shareholders may tender without any minimum amount being required for the Offer to proceed; "
        "the Board explicitly stated there is no minimum tender condition.",
        True,
    ),
]

PHRASINGS = {
    "past_doc_words": "Did the filing state there is no minimum tender condition?",
    "present_generic": "Does the offer have no minimum tender requirement?",
    "past_weak": "Was a minimum tender condition absent?",
}


def _answers_key(res) -> dict:
    """Comparable subset of answers (ignore usage/routing noise)."""
    out = {}
    for name, a in res.answers.items():
        out[name] = {
            "type": a.type,
            "value": a.value,
            "confidence": round(a.confidence, 4),
        }
        if a.probabilities:
            out[name]["probabilities"] = {
                k: round(v, 4) for k, v in sorted(a.probabilities.items())
            }
    return out


def main() -> int:
    load_dotenv()
    cli = LayaClient(max_in_flight=1, batch_size=24)

    print("=== 1) health ===")
    t0 = time.perf_counter()
    health = cli.health()
    t_health = time.perf_counter() - t0
    print(f"time_s={t_health:.3f}")
    print(health)
    # common checkpoint fields
    for key in ("checkpoints", "models", "loaded", "model", "status"):
        if key in health:
            print(f"  {key}: {health[key]}")

    print("\n=== 2) batch vs single (8 texts) ===")
    t0 = time.perf_counter()
    batch = cli.decide_batch(PARITY_STATES, TONE_Q)
    t_batch = time.perf_counter() - t0
    print(f"batch_time_s={t_batch:.3f}  n={len(batch)}")

    singles = []
    t0 = time.perf_counter()
    for s in PARITY_STATES:
        singles.append(cli.decide(s, TONE_Q))
    t_singles = time.perf_counter() - t0
    print(f"singles_time_s={t_singles:.3f}  n={len(singles)}")

    mismatches = 0
    for i, (b, s) in enumerate(zip(batch, singles)):
        bk, sk = _answers_key(b), _answers_key(s)
        # Compare choice value primarily (probs may jitter slightly)
        b_choice = b.choice("tone")
        s_choice = s.choice("tone")
        ok = b_choice == s_choice
        if not ok:
            mismatches += 1
            print(f"  MISMATCH i={i}: batch={b_choice} single={s_choice}")
            print(f"    batch={bk} single={sk}")
    print(f"choice_mismatches={mismatches}/{len(PARITY_STATES)}")

    print("\n=== 3) phrasing accuracy on 6 labeled snippets ===")
    t0 = time.perf_counter()
    for name, instr in PHRASINGS.items():
        q = {"no_min": {"type": "noul", "instructions": instr}}
        # one batch for all 6
        results = cli.decide_batch([t for t, _ in LABELED], q)
        correct = 0
        for (text, gold_yes), res in zip(LABELED, results):
            p = res.noul("no_min") or 0.0
            pred_yes = p >= 0.5
            if pred_yes == gold_yes:
                correct += 1
            conf = res.answers["no_min"].confidence
            flag = " REVIEW" if res.needs_review else ""
            print(
                f"  [{name}] gold={'Y' if gold_yes else 'N'} pred={'Y' if pred_yes else 'N'} "
                f"noul={p:.3f} conf={conf:.3f}{flag} :: {text[:70]}…"
            )
        acc = correct / len(LABELED)
        print(f"  >> {name} accuracy={acc:.3f} ({correct}/{len(LABELED)})")
    t_phrase = time.perf_counter() - t0
    print(f"phrasing_block_time_s={t_phrase:.3f}")

    print("\n=== timings summary ===")
    print(
        {
            "health_s": round(t_health, 3),
            "batch_8_s": round(t_batch, 3),
            "singles_8_s": round(t_singles, 3),
            "phrasing_s": round(t_phrase, 3),
            "choice_mismatches": mismatches,
        }
    )
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
