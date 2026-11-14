#!/usr/bin/env python3
"""Classify every wrong field-call of a graph run by the quality of the model's inputs.

Reads ``<run>/inputs.jsonl`` (written by ``scripts/eval_unified_field_graph.py``) and
scores each call with the harness's own ``_score_one``. A call is wrong when the outcome
is ``fp_no_gt``, ``mismatch`` or ``fn``; each wrong call gets one category:

  gold blank, model gave a value   fp_no_gt
  evidence empty                   no evidence was shown to the model
  answer in a listed candidate     gold matches a value=/date= literal (clause: the excerpt)
  answer only in surrounding text  gold is in the evidence, but not as a listed candidate
  answer not in evidence           gold appears nowhere in the evidence

Date fields use a strict month/day/year comparison to decide whether the gold date is
present (soft_match's digit-subset rule would count "2026" inside "May 1, 2026" as a hit).

  .venv/bin/python scripts/analyze_input_quality.py --run <out>/experiments/runs/<run>
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.extract.providers import CLAUSE_PREFIX, NO_EVIDENCE  # noqa: E402
from src.evaluation.tender import normalize  # noqa: E402

DATE_FIELDS = frozenset({"expiration_date", "withdrawal_deadline", "settlement_date", "effective_date"})
WRONG = ("fp_no_gt", "mismatch", "fn")
CATEGORIES = (
    "gold blank, model gave a value",
    "evidence empty",
    "answer not in evidence",
    "answer in a listed candidate",
    "answer only in surrounding text",
)
_CAND = re.compile(r"""(?:value|date)=(['"])(.*?)\1(?= |$)""", re.M)
_CTX = re.compile(r"""(?:context|window)=(['"])(.*?)\1(?= |$)""", re.S)
_MON = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split()
)}
_MDY_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MDY_TXT = re.compile(r"\b(" + "|".join(_MON) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "eval_unified_field_graph", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def strict_dates(text: str | None) -> set[tuple[int, int, int]]:
    """(year, month, day) for every M/D/YYYY or 'Month D, YYYY' in ``text``."""
    s = (text or "").lower()
    out = {(int(y), int(m), int(d)) for m, d, y in _MDY_NUM.findall(s)}
    out |= {(int(y), _MON[mo], int(d)) for mo, d, y in _MDY_TXT.findall(s)}
    return out


def categorize(rec: dict, outcome: str, match) -> str:
    field, gold, ev = rec["request"]["field"], (rec["gold"] or "").strip(), rec["evidence"] or ""
    if outcome == "fp_no_gt":
        return CATEGORIES[0]
    if not ev.strip() or ev == NO_EVIDENCE:
        return CATEGORIES[1]
    clause = ev.startswith(CLAUSE_PREFIX)
    cands = [ev[len(CLAUSE_PREFIX):]] if clause else [v for _, v in _CAND.findall(ev)]
    gold_dates = strict_dates(gold) if field in DATE_FIELDS else set()
    if gold_dates:
        if any(gold_dates & strict_dates(c) for c in cands):
            return CATEGORIES[3]
        return CATEGORIES[4] if gold_dates & strict_dates(ev) else CATEGORIES[2]
    if any(match(c, gold) for c in cands):
        return CATEGORIES[3]
    ctxs = [v for _, v in _CTX.findall(ev)]
    if any(match(c, gold) for c in ctxs) or normalize(gold) in normalize(ev):
        return CATEGORIES[4]
    return CATEGORIES[2]


def analyze(run: Path) -> tuple[Counter, dict[str, Counter]]:
    H = _load_harness()
    by_call: dict[tuple[str, str], dict] = {}
    for line in (run / "inputs.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            req = rec["request"]  # request.accession is the per-row key; a resumed re-run wins
            by_call[(req["accession"], req["field"])] = rec
    totals: Counter = Counter()
    per_field: dict[str, Counter] = defaultdict(Counter)
    for rec in by_call.values():
        field = rec["request"]["field"]
        cfg = H.HARNESS_CONFIGS.get(rec["request"]["pack_name"])
        party = cfg.party_fields if cfg else frozenset()
        stats = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        gold = (rec["gold"] or "").strip()
        outcome = H._score_one(stats, gold, rec["pred"], field=field, party_fields=party)
        per_field[field]["calls"] += 1
        if outcome not in WRONG:
            continue
        match = H._party_soft_match if field in party else H.soft_match
        cat = categorize(rec, outcome, match)
        per_field[field]["wrong"] += 1
        per_field[field][cat] += 1
        totals[cat] += 1
    return totals, per_field


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", type=Path, required=True, help="run dir containing inputs.jsonl")
    args = p.parse_args(argv)
    if not (args.run / "inputs.jsonl").exists():
        print(f"no inputs.jsonl in {args.run}", file=sys.stderr)
        return 2
    totals, per_field = analyze(args.run)
    n_wrong = sum(totals.values())
    print(f"WRONG CALLS BY INPUT QUALITY ({n_wrong} wrong of {sum(c['calls'] for c in per_field.values())})")
    for cat in CATEGORIES:
        print(f"  {totals[cat]:5d}  {cat}")
    short = ("gold_blank", "ev_empty", "not_in_ev", "in_cand", "ctx_only")
    print("\n" + f"{'field':28s}{'calls':>6s}{'wrong':>6s}" + "".join(f"{s:>11s}" for s in short))
    for field, c in per_field.items():
        cols = "".join(f"{c[cat]:>11d}" for cat in CATEGORIES)
        print(f"{field:28s}{c['calls']:>6d}{c['wrong']:>6d}{cols}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
