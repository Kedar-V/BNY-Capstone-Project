"""Score the agent against the synthetic amendments' answer key.

    python -m agents.amendment_impact.synthetic        # build the cases first
    python -m agents.amendment_impact.evaluate         # rules only: reworded text should go to review
    python -m agents.amendment_impact.evaluate --env-file .env   # with the LLM judging reworded text

Writes synthetic/evaluation_summary.json and synthetic/results.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

from events.store import load_events
from events.versioning import replay

from . import config, synthetic
from .agent import assess, text_records
from .holders import load_clients
from .llm import TextJudge
from .triage import TIER_ORDER

NOTIFY = {"action", "informational"}


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def score(rows: list[dict]) -> dict:
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_action: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    confusion: Counter = Counter()
    for r in rows:
        ok = r["tier"] == r["expected"]
        for bucket in (by_type[r["type"]], by_action[r["action"]]):
            bucket[0] += ok
            bucket[1] += 1
        confusion[(r["expected"], r["tier"])] += 1

    notify_true = {r["case_id"] for r in rows if r["expected"] in NOTIFY}
    notify_pred = {r["case_id"] for r in rows if r["tier"] in NOTIFY}
    codes_true = {(r["case_id"], c) for r in rows for c in r["expected_review"]}
    codes_pred = {(r["case_id"], c) for r in rows for c in r["review"]}
    return {
        "cases": len(rows),
        "tier_accuracy": _ratio(sum(r["tier"] == r["expected"] for r in rows), len(rows)),
        "notify": {"precision": _ratio(len(notify_true & notify_pred), len(notify_pred)),
                   "recall": _ratio(len(notify_true & notify_pred), len(notify_true)),
                   "missed": sorted(notify_true - notify_pred), "false_alarms": sorted(notify_pred - notify_true)},
        "review_codes": {"precision": _ratio(len(codes_true & codes_pred), len(codes_pred)),
                         "recall": _ratio(len(codes_true & codes_pred), len(codes_true)),
                         "unexpected": sorted(f"{c}:{k}" for c, k in codes_pred - codes_true)[:20],
                         "missed": sorted(f"{c}:{k}" for c, k in codes_true - codes_pred)[:20]},
        "accuracy_by_type": {t: f"{a}/{b}" for t, (a, b) in by_type.items()},
        "accuracy_by_action": {t: f"{a}/{b}" for t, (a, b) in sorted(by_action.items())},
        "confusion_expected_to_predicted": {f"{e} -> {p}": n for (e, p), n in sorted(confusion.items(),
                                            key=lambda x: (TIER_ORDER.index(x[0][0]), TIER_ORDER.index(x[0][1])))},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", help="file with API_URL and STACKAI_API_KEY, to let the LLM judge reworded text")
    args = ap.parse_args()

    events = load_events()
    by_id = {e.id: e for e in events}
    cases = synthetic.load(events)
    clients = load_clients()
    judge = TextJudge(args.env_file, use_llm=bool(args.env_file))
    histories = [(c, synthetic.case_event(by_id, c)) for c in cases]
    histories = [(c, e, replay(e)[1]) for c, e in histories]
    if judge.enabled:
        judge.prepare([r for _, e, v in histories for r in text_records(e, v)])

    use_llm = judge.enabled
    rows = []
    for c, e, v in histories:
        out = assess(e, v, clients, judge if use_llm else None)
        expected_review = [x for x in c["expected_review"] if not (use_llm and x == "text_not_assessed")]
        rows.append({"case_id": c["case_id"], "type": c["type"], "action": c["action"], "event_id": c["event_id"],
                     "expected": c["expected_tier_llm"] if use_llm else c["expected_tier"], "tier": out["tier"],
                     "expected_review": expected_review, "review": [x["code"] for x in out["review"]], "why": out["why"]})

    summary = {"mode": "rules + LLM" if use_llm else "rules only", **score(rows)}
    if use_llm:
        summary["llm"] = judge.stats
    out_dir = config.SYNTHETIC_DIR
    (out_dir / "evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({**r, "expected_review": "; ".join(r["expected_review"]), "review": "; ".join(r["review"])})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
