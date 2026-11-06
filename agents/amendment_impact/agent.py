"""Amendment impact agent: when a later filing changes a corporate action, decide whether holders need to know.

    python -m agents.amendment_impact.agent                      # every amendment in the extraction runs, rules only
    python -m agents.amendment_impact.agent --env-file .env      # also ask the LLM about reworded text
    python -m agents.amendment_impact.agent --event tender-005-91234-0   # one event, printed

Steps, each recorded in the output's trace:
  1. Event store   filings grouped into events (events/store.py, shared with the other agents)
  2. Diff          replay the event's filings and list what this one changed (events/versioning.py)
  3. Triage        rules give each change a tier; only reworded text goes to the LLM (triage.py, llm.py)
  4. Checks        reasons to hold the amendment for an operations reviewer (checks.py)
  5. Holders       simulated clients holding or watching the affected security (holders.py)
  6. Notice        template notice from the record, waiting for operations to approve (notice.py)
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter

from events.store import Event, load_events
from events.versioning import Version, replay

from . import config
from .checks import check_version
from .holders import affected, load_clients
from .llm import TextJudge
from .notice import draft, value_text
from .triage import TIER_ORDER, Judgment, change_tier, filing_tier


class QuoteCheckers:
    """Quote checks against several folders of filing text (one per action's loader output)."""

    def __init__(self, dirs: list[str]) -> None:
        from agents.client_briefing.verify import QuoteChecker

        self.checkers = [QuoteChecker(d) for d in dirs]

    def verified(self, accession: str, quote: str | None) -> bool | None:
        answers = [c.verified(accession, quote) for c in self.checkers]
        return True if True in answers else False if False in answers else None


def text_records(event: Event, v: Version) -> list[dict]:
    return [TextJudge.record(event.action, c.key, c.previous, c.current) for c in v.changes if c.kind == "text" and c.previous]


def _as_text(key: str, value) -> str | None:
    return value if value is None or isinstance(value, str) else value_text(key, value)


def assess(event: Event, v: Version, clients: list[dict], judge: TextJudge | None = None, quote_checker=None) -> dict:
    """Everything the agent decides about one later filing of an event."""
    judgments: dict[str, Judgment] = {}
    if judge is not None:
        for c in v.changes:
            if c.kind == "text" and c.previous:
                j = judge.judge(TextJudge.record(event.action, c.key, c.previous, c.current))
                if j is not None:
                    judgments[c.key] = j

    changes, tiers = [], []
    for c in v.changes:
        tier, reason = change_tier(c, judgments.get(c.key))
        tiers.append(tier)
        changes.append({"field": c.key, "kind": c.kind, "previous": _as_text(c.key, c.previous), "current": _as_text(c.key, c.current),
                        "tier": tier, "reason": reason, "quote": c.quote, "location": c.location,
                        "decided_by": judgments[c.key].source if c.kind == "text" and c.key in judgments else "rules",
                        "similarity": round(c.similarity, 2) if c.similarity is not None else None})
    tier = filing_tier(tiers)
    review = check_version(event.action, v, judgments, quote_checker)
    notified = [c for c, t in zip(v.changes, tiers) if t in {"action", "informational"}]
    holders = affected(event, {c.key for c in notified}, clients) if notified else []
    notice = draft(event, v, tier, notified, holders)

    f = v.filing
    if not v.changes:
        why = "Restates earlier terms with no change" if v.restated else "No holder-facing terms extracted from this filing"
    else:
        why = next(ch["reason"] for ch in changes if ch["tier"] == tier)
    return {
        "event_id": event.id, "action": event.action, "title": event.title, "accession": f.accession, "form": f.form,
        "filed": f.filed.isoformat(), "url": f.url, "version": v.index, "tier": tier, "why": why,
        "needs_review": bool(review), "review": review, "changes": changes, "restated": v.restated,
        "holders": holders, "notice": notice,
        "trace": [
            {"step": "Diff", "detail": f"Version {v.index + 1} of {len(event.filings)}: {len(v.changes)} change(s), "
                                       f"{len(v.restated)} field(s) restated"},
            {"step": "Triage", "detail": f"{tier}: {why}" + (f" ({len(judgments)} text change(s) judged by the LLM)" if judgments else "")},
            {"step": "Checks", "detail": ", ".join(r["code"] for r in review) or "none"},
            {"step": "Holders", "detail": f"{sum(not h['watch_only'] for h in holders)} holding, {sum(h['watch_only'] for h in holders)} watching"},
            {"step": "Notice", "detail": "drafted, waiting for operations to approve" if notice else "none"},
        ],
    }


def run(events: list[Event], judge: TextJudge | None = None, quote_checker=None) -> list[dict]:
    """Assess every filing after an event's first one."""
    clients = load_clients()
    histories = [(e, replay(e)) for e in events if len(e.filings) > 1]
    if judge is not None and judge.enabled:
        judge.prepare([r for e, versions in histories for v in versions[1:] for r in text_records(e, v)])
    return [assess(e, v, clients, judge, quote_checker) for e, versions in histories for v in versions[1:]]


def summarize(results: list[dict]) -> dict:
    by_action: dict[str, Counter] = {}
    for r in results:
        by_action.setdefault(r["action"], Counter())[r["tier"]] += 1
    return {
        "amendments": len(results),
        "by_tier": {t: sum(r["tier"] == t for r in results) for t in TIER_ORDER},
        "by_action": {a: {t: c[t] for t in TIER_ORDER} for a, c in sorted(by_action.items())},
        "held_for_review": sum(r["needs_review"] for r in results),
        "review_reasons": dict(Counter(x["code"] for r in results for x in r["review"]).most_common()),
        "notices_drafted": sum(r["notice"] is not None for r in results),
        "notices_with_recipients": sum(bool(r["notice"] and r["notice"]["recipients"]) for r in results),
    }


def write_outputs(results: list[dict], out_dir=config.OUTPUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    (out_dir / "amendment_queue.json").write_text(json.dumps({"summary": summary, "amendments": results}, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
    with open(out_dir / "amendment_queue.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "action", "title", "accession", "form", "filed", "tier", "why", "changed_fields", "review_codes",
                    "recipients"])
        for r in results:
            w.writerow([r["event_id"], r["action"], r["title"], r["accession"], r["form"], r["filed"], r["tier"], r["why"],
                        "; ".join(c["field"] for c in r["changes"]), "; ".join(x["code"] for x in r["review"]),
                        "; ".join(r["notice"]["recipients"]) if r["notice"] else ""])
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--actions", nargs="+", default=["tender_offer", "merger", "rights_issue"])
    ap.add_argument("--event", help="assess one event and print it")
    ap.add_argument("--env-file", help="file with API_URL and STACKAI_API_KEY; without it, reworded text goes to review")
    ap.add_argument("--text-dir", nargs="*", default=[], help="folders of <accession>.txt filing text, to check quotes")
    args = ap.parse_args()

    events = load_events(tuple(args.actions))
    judge = TextJudge(args.env_file, use_llm=bool(args.env_file))
    checker = QuoteCheckers(args.text_dir) if args.text_dir else None
    if args.event:
        events = [e for e in events if e.id == args.event]
        if not events:
            raise SystemExit(f"No event {args.event}")
        print(json.dumps(run(events, judge, checker), ensure_ascii=False, indent=1, default=str))
        return
    results = run(events, judge, checker)
    summary = write_outputs(results)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {config.OUTPUT_DIR / 'amendment_queue.json'} and amendment_queue.csv")
    if judge.enabled:
        print("LLM:", judge.stats)


if __name__ == "__main__":
    main()
