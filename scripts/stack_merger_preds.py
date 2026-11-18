#!/usr/bin/env python3
"""Rebuild the stacked merger preds on balanced200 and score them.

Layers, in order: frozen baseline → C_drop oneshot restore → date-FP abstain →
prompt-fix / still-bad / few-shot / packfix probe overlays → any ``--extra``
probe runs (improved rows only) → optional cross-field rules.

Example:
  python scripts/stack_merger_preds.py --extra probe_merger_target_sec --cross-field
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs.merger import apply_cross_field_rules  # noqa: E402
from src.evaluation.extract.frozen import load_evidence_pack  # noqa: E402
from src.evaluation.tender import soft_match  # noqa: E402

RUNS = ROOT / "outputs/merger_eval/experiments/runs"
BASE_RUN = RUNS / "frozen_qwen3_finance_merger_balanced200"
PACK = ROOT / "outputs/merger_eval/evidence_packs/merger_holdout_heuristic_balanced200"
DATE_FIELDS = {"election_deadline", "effective_date", "shareholder_vote_date"}


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_eval_ufg_stack", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def _blank() -> dict[str, int]:
    return {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}


def outcome(gold: str, pred: str, field: str) -> str:
    return H._score_one(_blank(), gold, pred, field=field, party_fields=H.PARTY_FIELDS)


def _clean(pred) -> str:
    if pred is None:
        return ""
    return pred.strip() if isinstance(pred, str) else str(pred).strip()


def _parse_oneshot(raw: str, field: str) -> str | None:
    m = re.search(r"oneshot:(\{[\s\S]*?\})\s*(?:\||$)", raw or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    v = obj.get(field) or obj.get("value")
    v = _clean(v)
    return None if not v or v.lower() in {"null", "none", "n/a"} else v


def load_gold():
    _, records, _ = load_evidence_pack(PACK)
    return records, {(r.ei, r.field): (r.gold or "") for r in records}


def score(preds: dict, gold: dict):
    st = _blank()
    by: dict[str, dict] = defaultdict(_blank)
    for (ei, f), g in gold.items():
        p = preds.get((ei, f), "")
        H._score_one(st, g, p, field=f, party_fields=H.PARTY_FIELDS)
        H._score_one(by[f], g, p, field=f, party_fields=H.PARTY_FIELDS)

    def f1(s):
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "p": p, "r": r,
                "f1": 0.0 if p + r == 0 else 2 * p * r / (p + r)}

    return f1(st), {k: f1(v) for k, v in by.items()}


def build_stack(records, gold, extra: list[str] = (), cross_field: bool = False, steps=None):
    """``steps``: optional list; gets ``(layer, preds_copy)`` after each layer."""

    def mark(layer: str) -> None:
        if steps is not None:
            steps.append((layer, dict(preds)))

    preds: dict[tuple[int, str], str] = {}
    acc_field_ei: dict[tuple[str, str], int] = {}
    for line in (BASE_RUN / "checkpoint.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ei = int(row["ei"])
        preds[(ei, str(row["field"]))] = _clean((row.get("result") or {}).get("pred"))
        acc_field_ei[(row["accession"], row["field"])] = ei
    mark("base")

    for row in json.loads((BASE_RUN / "details.json").read_text()):
        for field, d in row["fields"].items():
            if "C_drop" not in (d.get("pass_used") or ""):
                continue
            ei = acc_field_ei.get((row["accession"], field))
            pre = _parse_oneshot(d.get("raw_llm") or "", field)
            g = d.get("gold") or ""
            if ei is None or not pre or not g:
                continue
            match = H._party_soft_match if field in H.PARTY_FIELDS else soft_match
            if match(pre, g):
                preds[(ei, field)] = pre
    mark("cdrop_restore")

    for (ei, f), g in gold.items():
        if f in DATE_FIELDS and outcome(g, preds.get((ei, f), ""), f) == "fp_no_gt":
            preds[(ei, f)] = ""
    mark("date_abstain")

    for r in json.loads((RUNS / "probe_merger_prompt_fixes/details.json").read_text()):
        if r["delta"] == "improved":
            preds[(r["ei"], r["field"])] = r.get("pred") or ""

    for r in json.loads((RUNS / "probe_merger_qwen_stillbad_v2/details.json").read_text()):
        if r["delta_vs_prior"] == "improved" or (
            r["prior_outcome"] == "mismatch" and r["outcome"] in ("fn", "skip")
        ):
            preds[(r["ei"], r["field"])] = r.get("pred") or ""

    for name in ("probe_merger_fewshot_noval", "probe_merger_fewshot_v2"):
        det = RUNS / name / "details.json"
        if not det.exists():
            continue
        for r in json.loads(det.read_text()):
            k = (r["ei"], r["field"])
            if r.get("outcome") == "tp" and outcome(gold[k], preds.get(k, ""), r["field"]) != "tp":
                preds[k] = r.get("pred") or ""
    mark("prompt_fewshot")

    for spec in ("probe_merger_packfix_ticker_ratio", *extra):
        name, _, only = spec.partition(":")
        keep = set(only.split(",")) if only else None
        det = RUNS / name / "details.json"
        if not det.exists():
            print(f"skip missing overlay {name}", file=sys.stderr)
            continue
        for r in json.loads(det.read_text()):
            if r.get("delta") == "improved" and (keep is None or r["field"] in keep):
                preds[(r["ei"], r["field"])] = r.get("pred") or ""
        mark(name)

    if cross_field:
        acc_of = {r.ei: r.accession for r in records}
        preds = apply_cross_field_rules(preds, acc_of)
        mark("cross_field")
    return preds


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--extra", action="append", default=[],
        help="extra probe run dir name, optionally run:field1,field2 to overlay only those fields",
    )
    p.add_argument("--cross-field", action="store_true")
    p.add_argument("--out", type=Path, default=None, help="write stacked preds + summary here")
    args = p.parse_args(argv)

    records, gold = load_gold()
    preds = build_stack(records, gold, args.extra, args.cross_field)
    m, by = score(preds, gold)
    print(f"micro F1={m['f1']:.4f} P={m['p']:.3f} R={m['r']:.3f} tp={m['tp']} fp={m['fp']} fn={m['fn']}")
    for f in sorted(by, key=lambda k: -by[k]["f1"]):
        b = by[f]
        print(f"  {f:24} {b['f1']:.3f}  tp={b['tp']} fp={b['fp']} fn={b['fn']}")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "stacked_preds.json").write_text(json.dumps(
            [{"ei": ei, "field": f, "pred": v, "gold": gold.get((ei, f), "")}
             for (ei, f), v in sorted(preds.items()) if (ei, f) in gold],
            indent=2, ensure_ascii=False))
        (args.out / "stack_summary.json").write_text(json.dumps({"micro": m, "by_field": by}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
