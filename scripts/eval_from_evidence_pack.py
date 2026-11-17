#!/usr/bin/env python3
"""Replay an SLM against a frozen evidence pack (no retrieval / temporal / hybrid rebuild).

  .venv/bin/python scripts/eval_from_evidence_pack.py \\
      --evidence-pack outputs/tender_eval/evidence_packs/tender_holdout_oneshot_hybrid \\
      --backend orin --model gemma4:26b --run-name gemma_on_frozen_holdout
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.extract.dtos import FieldExtractRequest  # noqa: E402
from src.evaluation.extract.frozen import FrozenEvidenceProvider, load_evidence_pack  # noqa: E402
from src.evaluation.extract.graph import build_extract_graph, run_field  # noqa: E402
from src.evaluation.extract.routing import load_routing_file, pack_with_recipes  # noqa: E402
from src.evaluation.llm_backends import (  # noqa: E402
    NativeOllamaBackend,
    load_dotenv,
    make_backend,
)


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_eval_unified_field_graph_for_replay", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Run an SLM on a frozen evidence pack")
    p.add_argument("--evidence-pack", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None, help="eval root for runs/ (default from harness)")
    p.add_argument(
        "--backend",
        default="orin",
        choices=("openrouter", "ollama", "free", "orin", "openai"),
    )
    p.add_argument("--model", default=None)
    p.add_argument("--run-name", default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--num-predict",
        type=int,
        default=400,
        help="Ollama native num_predict (default 400 for qwen3-finance)",
    )
    p.add_argument(
        "--pack",
        default=None,
        help="override ActionPack name (must match manifest unless you know what you're doing)",
    )
    args = p.parse_args(argv)

    try:
        manifest, records, by_key = load_evidence_pack(args.evidence_pack)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    pack_name = args.pack or str(manifest.get("pack") or "")
    try:
        pack = get_pack(pack_name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    if pack.name != manifest.get("pack"):
        print(
            f"manifest pack={manifest.get('pack')!r} != live pack={pack.name!r}",
            file=sys.stderr,
        )
        return 2

    fields = tuple(manifest.get("fields") or [])
    if not fields:
        print("manifest has no fields", file=sys.stderr)
        return 2
    cascade = bool(manifest.get("cascade"))
    validate = bool(manifest.get("validate"))
    pack_id = str(manifest.get("pack_id") or args.evidence_pack.name)

    # Refuse field set drift vs ActionPack (unknown fields)
    bad = [f for f in fields if f not in pack.field_defs and f not in pack.fields]
    if bad:
        print(f"manifest fields unknown to pack {pack.name}: {bad}", file=sys.stderr)
        return 2

    # Apply pack-build routing so resolve_policy matches frozen stage sources
    routing_path = args.evidence_pack / "routing.json"
    if routing_path.exists():
        recipes = load_routing_file(routing_path)
        pack = pack_with_recipes(pack, recipes, validate=validate)
        print(
            f"routing: loaded {len(recipes)} field recipes from {routing_path.name} "
            f"(router={manifest.get('router')})",
            flush=True,
        )

    cfg = H.HARNESS_CONFIGS.get(pack.name)
    if args.out is None:
        if cfg is None:
            print("pass --out (pack has no harness config)", file=sys.stderr)
            return 2
        args.out = ROOT / cfg.out
    party_fields = cfg.party_fields if cfg is not None else H.PARTY_FIELDS

    if not args.model:
        args.model = (
            "gemma4:26b"
            if args.backend in {"orin", "ollama", "openai"}
            else H.DEFAULT_MODEL
        )

    try:
        if args.backend in {"ollama", "native", "ollama_native"}:
            # Native path: think=False, temperature=0, format=json (required for Qwen3)
            backend = NativeOllamaBackend(num_predict=int(args.num_predict))
        else:
            backend = make_backend(args.backend)
    except Exception as e:  # noqa: BLE001
        print(str(e), file=sys.stderr)
        return 3
    try:
        backend.chat_json(
            system="Return JSON only.",
            user='Return {"ping": true}',
            model=args.model,
        )
    except Exception as e:  # noqa: BLE001
        print(f"LLM backend unreachable ({args.backend}/{args.model}): {e}", file=sys.stderr)
        return 3

    model_tag = args.model.replace("/", "_").replace(":", "_").replace(".", "")
    run = args.run_name or f"frozen_{pack_id}_{model_tag}"
    out_dir = args.out / "experiments" / "runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)

    # Ordered unique rows by ei
    by_ei: dict[int, dict[str, Any]] = {}
    for rec in records:
        by_ei.setdefault(rec.ei, {"accession": rec.accession, "event_id": rec.event_id})
    n_rows = len(by_ei)
    concurrency = max(1, int(args.concurrency))
    print(
        json.dumps(
            {
                "evidence_pack": str(args.evidence_pack),
                "evidence_pack_id": pack_id,
                "pack": pack.name,
                "backend": args.backend,
                "model": args.model,
                "cascade": cascade,
                "validate": validate,
                "concurrency": concurrency,
                "n_rows": n_rows,
                "n_fields": len(fields),
                "fields": list(fields),
                "run": run,
            },
            indent=2,
        ),
        flush=True,
    )

    provider = FrozenEvidenceProvider(by_key)
    graph = build_extract_graph(pack, backend, provider)

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    pass_counts: dict[str, int] = {}
    from tqdm import tqdm

    ckpt_path = out_dir / "checkpoint.jsonl"
    inputs_path = out_dir / "inputs.jsonl"
    results_by_job: dict[tuple[int, str], dict[str, Any]] = {}
    if ckpt_path.exists():
        with ckpt_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results_by_job[(int(rec["ei"]), str(rec["field"]))] = rec["result"]
        print(f"resume: loaded {len(results_by_job)} checkpointed field-calls", flush=True)
    else:
        inputs_path.write_text("", encoding="utf-8")

    jobs = [
        (rec.ei, rec.field, rec)
        for rec in records
        if (rec.ei, rec.field) not in results_by_job
    ]
    total = len(records)
    done = len(results_by_job)
    print(f"llm remaining={len(jobs)} done={done} total={total}", flush=True)

    def _run_job(ei: int, field: str, frozen_rec):
        req = FieldExtractRequest(
            pack_name=pack.name,
            field=field,
            event_id=frozen_rec.event_id,
            accession=frozen_rec.key,
            model=args.model,
            validate_enabled=validate,
            cascade=cascade,
        )
        result = run_field(graph, req)
        return (ei, field), req, result, frozen_rec.accession, frozen_rec.gold

    t0 = time.perf_counter()
    paused = False
    if jobs:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(_run_job, ei, field, rec) for ei, field, rec in jobs]
            pbar = tqdm(
                total=total,
                initial=done,
                desc="frozen_llm",
                unit="call",
                file=sys.stderr,
                dynamic_ncols=True,
            )
            try:
                with (
                    ckpt_path.open("a", encoding="utf-8") as ckpt_fh,
                    inputs_path.open("a", encoding="utf-8") as inputs_fh,
                ):
                    for fut in as_completed(futs):
                        key, req, full, acc, gold = fut.result()
                        result = H._result_dict(full)
                        results_by_job[key] = result
                        done += 1
                        ei, field = key
                        line = (
                            f"[{done}/{total}] {acc} {field} pass={result['pass_used']} "
                            f"GT={gold!r} pred={result['pred']!r}"
                        )
                        print(line, flush=True)
                        tqdm.write(line, file=sys.stderr)
                        ckpt_fh.write(
                            json.dumps(
                                {"ei": ei, "field": field, "accession": acc, "result": result}
                            )
                            + "\n"
                        )
                        ckpt_fh.flush()
                        inputs_fh.write(
                            json.dumps(
                                H._inputs_record(req, full, ei=ei, accession=acc, gold=gold)
                            )
                            + "\n"
                        )
                        inputs_fh.flush()
                        pbar.update(1)
            except KeyboardInterrupt:
                paused = True
                # Cancel queued work; in-flight calls may still finish and flush.
                for fut in futs:
                    fut.cancel()
                print(
                    f"\npaused at {done}/{total} field-calls — "
                    f"re-run the same command to resume.\ncheckpoint: {ckpt_path}",
                    file=sys.stderr,
                    flush=True,
                )
            finally:
                pbar.close()
    wall_s = time.perf_counter() - t0

    if paused:
        return 130

    # Score only cells present in the pack (subset packs are sparse across fields).
    missing = [(rec.ei, rec.field) for rec in records if (rec.ei, rec.field) not in results_by_job]
    if missing:
        print(
            f"incomplete run: missing {len(missing)} cells e.g. {missing[0]}; re-run to resume",
            file=sys.stderr,
        )
        return 1

    details_by_ei: dict[int, dict[str, Any]] = {}
    for rec in records:
        result = results_by_job[(rec.ei, rec.field)]
        gold = rec.gold
        outcome = H._score_one(
            stats[rec.field], gold, result["pred"], field=rec.field, party_fields=party_fields
        )
        pass_counts[result["pass_used"]] = pass_counts.get(result["pass_used"], 0) + 1
        row_d = details_by_ei.get(rec.ei)
        if row_d is None:
            meta = by_ei[rec.ei]
            row_d = {
                "accession": meta["accession"],
                "event_id": meta["event_id"],
                "fields": {},
            }
            details_by_ei[rec.ei] = row_d
        row_d["fields"][rec.field] = {
            "outcome": outcome,
            "gold": gold if H._gt_ok(gold) else None,
            **result,
        }
    details = [details_by_ei[ei] for ei in sorted(details_by_ei)]

    per_field = {
        f: {**stats[f], **H._prf(stats[f]["tp"], stats[f]["fp"], stats[f]["fn"])} for f in fields
    }
    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    micro = H._prf(tp, fp, fn)
    summary = {
        "pack": pack.name,
        "evidence_pack_id": pack_id,
        "evidence_pack": str(args.evidence_pack.resolve()),
        "backend": args.backend,
        "model": args.model,
        "mode": "cascade_v2" if cascade else "oneshot_v1",
        "validate": validate,
        "concurrency": concurrency,
        "reasoning_effort": "none",
        "wall_seconds": round(wall_s, 2),
        "n_rows": n_rows,
        "n_llm_jobs": total,
        "fields": list(fields),
        "micro": micro,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "pass_counts": pass_counts,
        "per_field": per_field,
        "baselines": {
            "hybrid_gliner_qwen_allspans_micro_f1": H.ALLSPANS_MICRO,
            "unified_prompt_v2_micro_f1": H.PROMPT_V2_MICRO,
            "oracle_routing_micro_f1": H.ORACLE_MICRO,
        },
        "accession_hash": manifest.get("accession_hash"),
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
            w.writerow({"field": field, **{k: row[k] for k in w.fieldnames if k != "field"}})

    print(json.dumps(summary, indent=2), flush=True)
    print(
        f"micro_f1={micro.get('f1')}  vs_oracle={H.ORACLE_MICRO}  wrote {out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
