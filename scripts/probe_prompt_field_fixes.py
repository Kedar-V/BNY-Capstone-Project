#!/usr/bin/env python3
"""Re-run selected field misses with current prompts (frozen evidence).

Progress bar + checkpoint/resume required.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.extract.dtos import FieldExtractRequest  # noqa: E402
from src.evaluation.extract.frozen import FrozenEvidenceProvider, load_evidence_pack  # noqa: E402
from src.evaluation.extract.graph import build_extract_graph, run_field  # noqa: E402
from src.evaluation.extract.routing import load_routing_file, pack_with_recipes  # noqa: E402
from src.evaluation.llm_backends import NativeOllamaBackend, load_dotenv  # noqa: E402


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_eval_ufg_probe_fields", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument(
        "--baseline-run",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/frozen_qwen3_finance_oracle_heuristic"),
    )
    p.add_argument(
        "--twostage-details",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/probe_mismatch_twostage_qwen3/details.json"),
    )
    p.add_argument(
        "--prior-prompt-ckpt",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/probe_prompt_fixes_f1/checkpoint.jsonl"),
        help="earlier bidder/date prompt-fix preds to layer under this probe",
    )
    p.add_argument(
        "--evidence-pack",
        type=Path,
        default=Path("outputs/tender_eval/evidence_packs/tender_holdout_oracle_heuristic_hybrid"),
    )
    p.add_argument(
        "--fields",
        default="offer_price,security_description,proration_terms",
        help="comma-separated fields whose current misses to refresh",
    )
    p.add_argument("--model", default="qwen3-finance:latest")
    p.add_argument("--num-predict", type=int, default=400)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/probe_prompt_offer_sec_proration"),
    )
    args = p.parse_args(argv)

    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    _, records, by_key = load_evidence_pack(args.evidence_pack)
    gold = {(r.ei, r.field): (r.gold or "") for r in records}
    rec_by = {(r.ei, r.field): r for r in records}

    preds: dict[tuple[int, str], str] = {}
    for row in [
        json.loads(l)
        for l in (args.baseline_run / "checkpoint.jsonl").read_text().splitlines()
        if l.strip()
    ]:
        pred = ((row.get("result") or {}).get("pred") or "")
        pred = pred.strip() if isinstance(pred, str) else (str(pred).strip() if pred else "")
        preds[(int(row["ei"]), str(row["field"]))] = pred
    if args.twostage_details.exists():
        for r in json.loads(args.twostage_details.read_text()):
            tp = r.get("twostage_pred")
            preds[(r["ei"], r["field"])] = "" if tp in (None, "∅") else str(tp).strip()
    if args.prior_prompt_ckpt.exists():
        for line in args.prior_prompt_ckpt.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            preds[(r["ei"], r["field"])] = r.get("pred") or ""

    jobs: list[tuple[int, str]] = []
    for (ei, field), pred in preds.items():
        if field not in fields:
            continue
        st = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        out = H._score_one(st, gold[(ei, field)], pred, field=field)
        if out in ("mismatch", "fp_no_gt", "fn"):
            jobs.append((ei, field))
    jobs = sorted(set(jobs))
    print(f"jobs to refresh: {len(jobs)} fields={fields}", flush=True)

    pack = pack_with_recipes(
        get_pack("tender"),
        load_routing_file(args.evidence_pack / "routing.json"),
        validate=True,
    )
    graph = build_extract_graph(
        pack, NativeOllamaBackend(num_predict=int(args.num_predict)), FrozenEvidenceProvider(by_key)
    )

    args.out.mkdir(parents=True, exist_ok=True)
    ckpt_path = args.out / "checkpoint.jsonl"
    done: dict[tuple[int, str], dict] = {}
    if ckpt_path.exists():
        for line in ckpt_path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            done[(int(r["ei"]), str(r["field"]))] = r
        print(f"resume: {len(done)} checkpointed", flush=True)

    from tqdm import tqdm

    pending = [j for j in jobs if j not in done]
    with ckpt_path.open("a", encoding="utf-8") as fh:
        for ei, field in tqdm(pending, total=len(pending), desc="prompt_fix", unit="call", file=sys.stderr):
            r = rec_by[(ei, field)]
            res = run_field(
                graph,
                FieldExtractRequest(
                    pack_name="tender",
                    field=field,
                    event_id=r.event_id,
                    accession=r.key,
                    model=args.model,
                    validate_enabled=field in pack.validate_fields or True,
                    cascade=True,
                ),
            )
            pred = (res.pred or "").strip()
            st = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
            out = H._score_one(st, gold[(ei, field)], pred, field=field)
            base_out = H._score_one(
                {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0},
                gold[(ei, field)],
                preds[(ei, field)],
                field=field,
            )
            rec = {
                "ei": ei,
                "field": field,
                "accession": r.accession,
                "gold": gold[(ei, field)],
                "baseline_pred": preds[(ei, field)],
                "baseline_outcome": base_out,
                "pred": pred,
                "outcome": out,
                "pass_used": res.pass_used,
                "delta": (
                    "improved"
                    if out in ("tp", "skip") and base_out not in ("tp", "skip")
                    else (
                        "worse"
                        if base_out in ("tp", "skip") and out not in ("tp", "skip")
                        else ("still_ok" if out in ("tp", "skip") else "still_bad")
                    )
                ),
            }
            done[(ei, field)] = rec
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

    rows = [done[j] for j in jobs if j in done]
    from collections import Counter, defaultdict

    summary = {
        "n_jobs": len(jobs),
        "delta": dict(Counter(r["delta"] for r in rows)),
        "by_field": {
            f: dict(Counter(r["delta"] for r in rows if r["field"] == f)) for f in fields
        },
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "details.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2), flush=True)
    print("\nimproved:", flush=True)
    for r in rows:
        if r["delta"] != "improved":
            continue
        print(
            f"  {r['field']:24} …{r['accession'][-6:]}  "
            f"{r['baseline_outcome']}→{r['outcome']}  pred={r['pred'][:80]!r}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
