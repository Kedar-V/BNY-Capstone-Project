#!/usr/bin/env python3
"""Resume verify_c4_reasoning_none_limit20 and print live throughput vs prior baseline."""
from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "eval_unified_field_qwen", ROOT / "scripts" / "eval_unified_field_qwen.py"
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

from src.evaluation.action_packs import get_pack
from src.evaluation.experiments import ensure_holdout
from src.evaluation.llm_backends import load_dotenv, make_backend
from src.evaluation.tender import gt_event_ids_from_corpus, load_gt
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

# Pre-optimization c=4 pace from this same run's first segment
PRIOR_CALLS_PER_MIN = 16.6
PRIOR_SEC_PER_CALL_WALL = 3.6


def main() -> int:
    load_dotenv()
    run = "verify_c4_reasoning_none_limit20"
    log_path = ROOT / "outputs/tender_eval/experiments" / f"{run}.log"
    out_dir = ROOT / "outputs/tender_eval/experiments/runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    concurrency = 4

    pack = get_pack("tender")
    fields = tuple(pack.fields)
    backend = make_backend("orin")
    model = "gemma4:26b"

    from transformers import pipeline

    print("loading temporal tagger on cpu…", flush=True)
    tagger = pipeline(
        "token-classification",
        model=mod.TEMPORAL_MODEL,
        aggregation_strategy="simple",
        device="cpu",
    )

    store = ArtifactStore("tender", DEFAULT_PREPROCESS_ROOT)
    gt_rows = load_gt(ROOT / "notebooks/evaluation/tender_offers.csv")
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(ROOT / "outputs/tender_eval", accessions, n=20))
    rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout][:20]
    docs = ROOT / "data/processed/documents.parquet"
    acc_to_eid = (
        gt_event_ids_from_corpus(
            {(r.get("accession_number") or "").strip() for r in rows},
            docs,
        )
        if docs.exists()
        else {}
    )

    prepared: list[dict] = []
    for row in rows:
        acc = (row.get("accession_number") or "").strip()
        eid = acc_to_eid.get(acc) or (row.get("event_id") or "").strip() or None
        rep = mod._load_rep(pack.name, eid) if eid else {}
        spans = mod._load_spans(pack.name, eid) if eid else []
        excerpts = mod._excerpts(store, eid) if eid else ""
        if not spans or not excerpts:
            passages = mod._passages_obj(row.get("passages"))
            if not spans and passages:
                spans = mod._spans_from_passages(passages)
            if not excerpts and passages:
                excerpts = mod._excerpts_from_passages(passages)
        prepared.append(
            {
                "row": row,
                "accession": acc,
                "event_id": eid,
                "rep": rep,
                "spans": spans,
                "excerpts": excerpts,
            }
        )

    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    # Ignore later resume injections if any
    for marker in ("\nloading temporal tagger", '\n"missing":', "\nBENCHMARK"):
        cut = log_text.find(marker)
        if cut > 0:
            log_text = log_text[:cut]
            break
    pat = re.compile(r"^\[(\d+)/280\] (\S+) (\S+) pass=(\S+) pred=(.*)$", re.M)
    first_log: dict[tuple[str, str], dict] = {}
    for m in pat.finditer(log_text):
        acc, field, pass_u, pred_s = m.group(2), m.group(3), m.group(4), m.group(5).strip()
        key = (acc, field)
        if key in first_log:
            continue
        if pred_s == "None":
            pred = None
        else:
            try:
                pred = eval(pred_s)  # noqa: S307
            except Exception:
                pred = pred_s.strip("'")
        first_log[key] = {
            "pred": pred,
            "pass_used": pass_u,
            "n_evidence_chars": 0,
            "n_rules": 0,
            "raw_llm": "from_log",
        }

    results: dict[tuple[int, str], dict] = {}
    consumed: set[tuple[str, str]] = set()
    missing: list[tuple[int, str]] = []
    for ei in range(len(prepared)):
        acc = prepared[ei]["accession"]
        for field in fields:
            key = (acc, field)
            if key in first_log and key not in consumed:
                results[(ei, field)] = first_log[key]
                consumed.add(key)
            else:
                missing.append((ei, field))

    total = len(prepared) * len(fields)
    print(
        json.dumps(
            {
                "run": run,
                "concurrency": concurrency,
                "from_log": len(results),
                "missing": len(missing),
                "total": total,
                "prior_baseline_calls_per_min": PRIOR_CALLS_PER_MIN,
                "prior_baseline_sec_per_call_wall": PRIOR_SEC_PER_CALL_WALL,
            },
            indent=2,
        ),
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            "\nBENCHMARK_RESUME "
            + json.dumps(
                {
                    "from_log": len(results),
                    "missing": len(missing),
                    "concurrency": concurrency,
                }
            )
            + "\n"
        )

    def _run_job(ei: int, field: str) -> tuple[tuple[int, str], dict]:
        ev = prepared[ei]
        try:
            result = mod.extract_field(
                pack=pack,
                backend=backend,
                model=model,
                field=field,
                rep=ev["rep"],
                spans=ev["spans"],
                excerpts=ev["excerpts"],
                tagger=tagger,
                cascade=False,
                validate=False,
            )
        except Exception as e:  # noqa: BLE001
            result = {
                "pred": None,
                "pass_used": "error",
                "n_evidence_chars": 0,
                "n_rules": 0,
                "raw_llm": str(e)[:400],
            }
        return (ei, field), result

    t0 = time.perf_counter()
    done_resume = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(_run_job, ei, field) for ei, field in missing]
        for fut in as_completed(futs):
            key, result = fut.result()
            results[key] = result
            done_resume += 1
            ei, field = key
            n = len(results)
            elapsed = time.perf_counter() - t0
            rate = done_resume / elapsed * 60 if elapsed > 0 else 0
            speedup = rate / PRIOR_CALLS_PER_MIN if PRIOR_CALLS_PER_MIN else 0
            line = (
                f"[{n}/{total}] {prepared[ei]['accession']} {field} "
                f"pass={result['pass_used']} pred={result['pred']!r:.80}"
            )
            print(line, flush=True)
            if done_resume % 10 == 0 or done_resume == len(missing):
                print(
                    f"BENCH resume {done_resume}/{len(missing)} "
                    f"{rate:.1f}/min ({elapsed/done_resume:.2f}s/call wall) "
                    f"vs prior {PRIOR_CALLS_PER_MIN}/min → {speedup:.2f}x",
                    flush=True,
                )
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    wall_resume = time.perf_counter() - t0
    rate = len(missing) / wall_resume * 60 if wall_resume and missing else 0

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    pass_counts: dict[str, int] = {}
    details: list[dict] = []
    for ei, ev in enumerate(prepared):
        row = ev["row"]
        row_d: dict = {
            "accession": ev["accession"],
            "event_id": ev["event_id"],
            "n_spans": len(ev["spans"]),
            "n_excerpt_chars": len(ev["excerpts"]),
            "fields": {},
        }
        for field in fields:
            result = results[(ei, field)]
            gold = (row.get(field) or "").strip()
            outcome = mod._score_one(stats[field], gold, result["pred"])
            pass_counts[result["pass_used"]] = pass_counts.get(result["pass_used"], 0) + 1
            row_d["fields"][field] = {
                "outcome": outcome,
                "gold": gold if mod._gt_ok(gold) else None,
                **result,
            }
        details.append(row_d)

    per_field = {
        f: {**stats[f], **mod._prf(stats[f]["tp"], stats[f]["fp"], stats[f]["fn"])} for f in fields
    }
    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    micro = mod._prf(tp, fp, fn)
    summary = {
        "pack": pack.name,
        "backend": "orin",
        "model": model,
        "mode": "oneshot_v1",
        "validate": False,
        "concurrency": concurrency,
        "reasoning_effort": "none",
        "wall_seconds_resume": round(wall_resume, 2),
        "resume_calls_per_min": round(rate, 2),
        "resume_sec_per_call_wall": round(wall_resume / len(missing), 3) if missing else None,
        "prior_calls_per_min": PRIOR_CALLS_PER_MIN,
        "throughput_speedup_vs_prior": round(rate / PRIOR_CALLS_PER_MIN, 3) if PRIOR_CALLS_PER_MIN else None,
        "n_rows": len(rows),
        "n_llm_jobs": total,
        "n_from_log": total - len(missing),
        "n_resumed": len(missing),
        "fields": list(fields),
        "micro": micro,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "pass_counts": pass_counts,
        "per_field": per_field,
        "baselines": {
            "hybrid_gliner_qwen_allspans_micro_f1": mod.ALLSPANS_MICRO,
            "unified_prompt_v2_micro_f1": mod.PROMPT_V2_MICRO,
            "oracle_routing_micro_f1": mod.ORACLE_MICRO,
        },
        "resumed_from_log": True,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "field",
                "tp",
                "fp",
                "fn",
                "gt_present",
                "pred_present",
                "precision",
                "recall",
                "f1",
            ],
        )
        w.writeheader()
        for field in fields:
            row = per_field[field]
            w.writerow(
                {
                    "field": field,
                    "tp": row["tp"],
                    "fp": row["fp"],
                    "fn": row["fn"],
                    "gt_present": row["gt_present"],
                    "pred_present": row["pred_present"],
                    "precision": row["precision"],
                    "recall": row["recall"],
                    "f1": row["f1"],
                }
            )

    print(
        f"DONE micro_f1={micro.get('f1')} tp={tp} fp={fp} fn={fn} "
        f"resume={len(missing)} in {wall_resume:.1f}s → {rate:.1f}/min "
        f"({wall_resume/len(missing) if missing else 0:.2f}s/call) "
        f"vs prior {PRIOR_CALLS_PER_MIN}/min → {rate/PRIOR_CALLS_PER_MIN if PRIOR_CALLS_PER_MIN else 0:.2f}x",
        flush=True,
    )
    print(f"saved={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
