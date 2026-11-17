#!/usr/bin/env python3
"""Re-run oneshot mismatches from a frozen eval with live 2-stage policies.

Compares baseline (checkpoint) vs 2-stage preds on the same (ei, field) jobs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.extract.dtos import FieldExtractRequest  # noqa: E402
from src.evaluation.extract.frozen import load_evidence_pack  # noqa: E402
from src.evaluation.extract.graph import build_extract_graph, run_field  # noqa: E402
from src.evaluation.extract.policies import FieldPolicy, Stage  # noqa: E402
from src.evaluation.extract.providers import ArtifactProvider  # noqa: E402
from src.evaluation.llm_backends import NativeOllamaBackend, load_dotenv, make_backend  # noqa: E402
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore  # noqa: E402


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_eval_unified_field_graph_probe", ROOT / "scripts/eval_unified_field_graph.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def _twostage_policy(field: str, *, validate: bool) -> FieldPolicy:
    """Field-aware 2-stage: narrow evidence first, broader fallback second."""
    v = validate
    if field == "offer_price":
        # hybrid prose first (NAV/formula); rules+hybrid fallback; no GLiNER par traps
        return FieldPolicy(
            stages=(
                Stage(
                    name="hybrid",
                    sources=("hybrid",),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=False,
                    validate=v,
                ),
                Stage(
                    name="rules_hybrid",
                    sources=("rules", "hybrid"),
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=v,
                ),
            ),
            stop_at_first_hit=True,
        )
    if field in ("expiration_date", "withdrawal_deadline"):
        return FieldPolicy(
            stages=(
                Stage(
                    name="temporal",
                    sources=("temporal",),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=False,
                    validate=v,
                ),
                Stage(
                    name="hybrid",
                    sources=("temporal", "hybrid"),
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=v,
                ),
            ),
            stop_at_first_hit=True,
        )
    if field == "effective_date":
        return FieldPolicy(
            stages=(
                Stage(
                    name="temporal",
                    sources=("temporal", "hybrid"),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=False,
                    validate=v,
                ),
                Stage(
                    name="span",
                    sources=("gliner", "temporal", "hybrid"),
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=v,
                ),
            ),
            stop_at_first_hit=True,
        )
    if field == "ticker":
        return FieldPolicy(
            stages=(
                Stage(
                    name="rules",
                    sources=("rules",),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=True,
                    validate=v,
                ),
                Stage(
                    name="span",
                    sources=("rules", "gliner", "hybrid"),
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=v,
                ),
            ),
            stop_at_first_hit=True,
        )
    if field == "currency":
        return FieldPolicy(
            stages=(
                Stage(
                    name="hybrid",
                    sources=("hybrid",),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=False,
                    validate=v,
                ),
                Stage(
                    name="mixed",
                    sources=("rules", "gliner", "hybrid"),
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=v,
                ),
            ),
            stop_at_first_hit=True,
        )
    # parties / default: rules first, then spans+hybrid
    return FieldPolicy(
        stages=(
            Stage(
                name="rules",
                sources=("rules",),
                prompt_mode="pick",
                on_empty="skip",
                pass_label="A",
                null_label=None,
                direct_from_rules=False,
                validate=v,
            ),
            Stage(
                name="span",
                sources=("rules", "gliner", "hybrid"),
                prompt_mode="pick",
                on_empty="ask",
                pass_label="B",
                null_label="B_null",
                direct_from_rules=False,
                validate=v,
            ),
        ),
        stop_at_first_hit=True,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument(
        "--baseline-run",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/frozen_qwen3_finance_oracle_heuristic"),
    )
    p.add_argument(
        "--evidence-pack",
        type=Path,
        default=Path("outputs/tender_eval/evidence_packs/tender_holdout_oracle_heuristic_hybrid"),
    )
    p.add_argument("--gt", type=Path, default=Path("notebooks/evaluation/tender_offers_clean.csv"))
    p.add_argument("--backend", default="ollama")
    p.add_argument("--model", default="qwen3-finance:latest")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--num-predict", type=int, default=400)
    p.add_argument("--limit", type=int, default=0, help="cap jobs (0=all oneshot mismatches)")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/tender_eval/experiments/runs/probe_mismatch_twostage_qwen3"),
    )
    args = p.parse_args(argv)

    manifest, records, _ = load_evidence_pack(args.evidence_pack)
    routing = json.loads((args.evidence_pack / "routing.json").read_text())
    shapes = {f: v["shape"] for f, v in routing["fields"].items()}
    gold = {(r.ei, r.field): (r.gold or "") for r in records}
    acc_by = {(r.ei, r.field): r.accession for r in records}
    eid_by = {(r.ei, r.field): r.event_id for r in records}
    key_by = {(r.ei, r.field): r.key for r in records}

    ckpt = [
        json.loads(l)
        for l in (args.baseline_run / "checkpoint.jsonl").read_text().splitlines()
        if l.strip()
    ]
    baseline: dict[tuple[int, str], dict[str, Any]] = {}
    jobs: list[tuple[int, str]] = []
    for row in ckpt:
        ei, field = int(row["ei"]), str(row["field"])
        if shapes.get(field) != "oneshot":
            continue
        pred = ((row.get("result") or {}).get("pred") or "")
        pred = pred.strip() if isinstance(pred, str) else (str(pred).strip() if pred else "")
        st = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        out = H._score_one(st, gold[(ei, field)], pred, field=field)
        baseline[(ei, field)] = {
            "pred": pred,
            "outcome": out,
            "pass_used": (row.get("result") or {}).get("pass_used"),
        }
        if out in ("mismatch", "fp_no_gt", "fn"):
            jobs.append((ei, field))
    jobs = sorted(set(jobs))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"oneshot mismatches to probe: {len(jobs)}", flush=True)
    if not jobs:
        return 0

    pack = get_pack(str(manifest.get("pack") or "tender"))
    fields_needed = sorted({f for _, f in jobs})
    policies = {
        f: _twostage_policy(f, validate=f in pack.validate_fields) for f in fields_needed
    }
    pack = replace(pack, policies={**pack.policies, **policies})

    # Reconstruct GT rows in evidence-pack ei order (manifest accessions, with dupes).
    from src.evaluation.tender import load_gt

    gt_rows = load_gt(args.gt)
    by_acc: dict[str, list[dict]] = {}
    for r in gt_rows:
        by_acc.setdefault(H._acc(r), []).append(r)
    rows: list[dict] = []
    used: dict[str, int] = {}
    for acc in manifest.get("accessions") or []:
        bucket = by_acc.get(acc) or []
        idx = used.get(acc, 0)
        if idx < len(bucket):
            rows.append(bucket[idx])
            used[acc] = idx + 1
        else:
            rows.append({"accession_number": acc})
    if len(rows) != int(manifest.get("n_rows") or len(rows)):
        print(f"warn: rebuilt rows={len(rows)} manifest n_rows={manifest.get('n_rows')}", flush=True)

    store = ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
    temporal_dir = Path("outputs/tender_eval/temporal_cache") / pack.name
    temporal_dir.mkdir(parents=True, exist_ok=True)
    _tagger_holder: dict[str, Any] = {"pipe": None}

    def _ensure_tagger():
        # Prefer disk cache hits; only load BERT on miss.
        if _tagger_holder["pipe"] is None:
            from transformers import pipeline

            print("loading temporal tagger…", flush=True)
            _tagger_holder["pipe"] = pipeline(
                "token-classification",
                model=H.TEMPORAL_MODEL,
                aggregation_strategy="simple",
                device=-1,
            )
        return _tagger_holder["pipe"]

    temporal_for = H.DiskTemporalCache(pack, temporal_dir, _ensure_tagger)
    row_keys = {id(r): f"{H._acc(r)}#{i}" for i, r in enumerate(rows)}
    acc_to_eid = H.gt_event_ids_from_corpus(
        {(r.get("accession_number") or "").strip() for r in rows},
        Path("data/processed/documents.parquet"),
    )

    def event_id_for(row: dict) -> str | None:
        a = H._acc(row)
        return acc_to_eid.get(a) or (row.get("event_id") or "").strip() or None

    provider = ArtifactProvider(
        pack,
        store,
        event_id_for=event_id_for,
        temporal_for=temporal_for,
        key_for=lambda r: row_keys[id(r)],
    )
    need_eis = sorted({ei for ei, _ in jobs if ei < len(rows)})
    prep_rows = [rows[ei] for ei in need_eis]
    print(f"preparing {len(prep_rows)} rows…", flush=True)
    keys = provider.prepare(prep_rows, tuple(fields_needed))
    ei_to_key = {ei: keys[i] for i, ei in enumerate(need_eis)}

    if args.backend in {"ollama", "native", "ollama_native"}:
        backend = NativeOllamaBackend(num_predict=int(args.num_predict))
    else:
        backend = make_backend(args.backend)
    backend.chat_json(
        system="Return JSON only.",
        user='Return {"ping": true}',
        model=args.model,
    )
    graph = build_extract_graph(pack, backend, provider)

    args.out.mkdir(parents=True, exist_ok=True)
    results: dict[tuple[int, str], dict[str, Any]] = {}
    t0 = time.time()

    def _run(ei: int, field: str):
        key = ei_to_key.get(ei) or key_by[(ei, field)]
        req = FieldExtractRequest(
            pack_name=pack.name,
            field=field,
            event_id=eid_by.get((ei, field)),
            accession=key,
            model=args.model,
            validate_enabled=field in pack.validate_fields,
            cascade=True,
        )
        result = run_field(graph, req)
        return (ei, field), result

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(_run, ei, field) for ei, field in jobs]
        done = 0
        for fut in as_completed(futs):
            key, result = fut.result()
            results[key] = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            done += 1
            if done % 5 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}", flush=True)

    # Compare
    improved = same = worse = still_bad = 0
    rows_out: list[dict[str, Any]] = []
    for ei, field in jobs:
        g = gold[(ei, field)]
        base = baseline[(ei, field)]
        new = results[(ei, field)]
        npred = (new.get("pred") or "")
        npred = npred.strip() if isinstance(npred, str) else (str(npred).strip() if npred else "")
        st1 = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        st2 = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        o1 = base["outcome"]
        o2 = H._score_one(st2, g, npred, field=field)
        ok1 = o1 == "tp" or o1 == "skip"
        ok2 = o2 == "tp" or o2 == "skip"
        if ok2 and not ok1:
            delta = "improved"
            improved += 1
        elif ok1 and not ok2:
            delta = "worse"
            worse += 1
        elif ok1 and ok2:
            delta = "still_ok"
            same += 1
        else:
            delta = "still_bad"
            still_bad += 1
        rows_out.append(
            {
                "ei": ei,
                "field": field,
                "accession": acc_by[(ei, field)],
                "gold": g,
                "baseline_pred": base["pred"],
                "baseline_outcome": o1,
                "baseline_pass": base["pass_used"],
                "twostage_pred": npred,
                "twostage_outcome": o2,
                "twostage_pass": new.get("pass_used"),
                "delta": delta,
            }
        )

    summary = {
        "n_jobs": len(jobs),
        "improved": improved,
        "still_bad": still_bad,
        "worse": worse,
        "still_ok": same,
        "wall_seconds": round(time.time() - t0, 1),
        "model": args.model,
        "fields": fields_needed,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "details.json").write_text(json.dumps(rows_out, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2), flush=True)

    # per-field deltas
    from collections import defaultdict

    by_f: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows_out:
        by_f[r["field"]][r["delta"]] += 1
    print("\nper field:", flush=True)
    for f, d in sorted(by_f.items()):
        print(f"  {f:28} {dict(d)}", flush=True)
    print("\nimproved examples:", flush=True)
    for r in rows_out:
        if r["delta"] != "improved":
            continue
        print(
            f"  {r['field']} …{r['accession'][-6:]}  "
            f"{r['baseline_outcome']}→{r['twostage_outcome']}  "
            f"pred={r['twostage_pred'][:80]!r}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
