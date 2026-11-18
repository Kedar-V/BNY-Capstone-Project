#!/usr/bin/env python3
"""Re-run every balanced200 cell of selected merger fields with current prompts.

Compares each pred against the current stacked pred, so ``worse`` rows expose
prompt regressions on cells that were already right. tqdm + checkpoint/resume.

Example:
  python scripts/probe_merger_fields.py --fields target,security_description,consideration_type \\
      --out outputs/merger_eval/experiments/runs/probe_merger_target_sec
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tqdm import tqdm  # noqa: E402

from src.evaluation.action_packs import get_pack  # noqa: E402
from src.evaluation.action_packs.merger import VALIDATE_FIELDS  # noqa: E402
from src.evaluation.extract.dtos import FieldExtractRequest  # noqa: E402
from src.evaluation.extract.frozen import FrozenEvidenceProvider, load_evidence_pack  # noqa: E402
from src.evaluation.extract.graph import build_extract_graph, run_field  # noqa: E402
from src.evaluation.extract.routing import load_routing_file, pack_with_recipes  # noqa: E402
from src.evaluation.llm_backends import NativeOllamaBackend, load_dotenv  # noqa: E402


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("_stack_merger", "scripts/stack_merger_preds.py")
OK = ("tp", "skip")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--fields", default="target,security_description,consideration_type")
    p.add_argument("--evidence-pack", type=Path, default=S.PACK)
    p.add_argument("--model", default="qwen3-finance:latest")
    p.add_argument("--num-predict", type=int, default=500)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fresh", action="store_true", help="discard the checkpoint")
    args = p.parse_args(argv)

    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    _, records, by_key = load_evidence_pack(args.evidence_pack)
    rec_by = {(r.ei, r.field): r for r in records}
    gold = {(r.ei, r.field): (r.gold or "") for r in records}
    stack = S.build_stack(*S.load_gold())

    jobs = sorted((r.ei, r.field) for r in records if r.field in fields)
    print(f"jobs: {len(jobs)} {dict(Counter(f for _, f in jobs))}", flush=True)

    pack = pack_with_recipes(
        get_pack("merger"), load_routing_file(args.evidence_pack / "routing.json"), validate=None
    )
    graph = build_extract_graph(
        pack, NativeOllamaBackend(num_predict=args.num_predict), FrozenEvidenceProvider(by_key)
    )

    args.out.mkdir(parents=True, exist_ok=True)
    ckpt = args.out / "checkpoint.jsonl"
    if args.fresh and ckpt.exists():
        ckpt.unlink()
    done: dict[tuple[int, str], dict] = {}
    if ckpt.exists():
        for line in ckpt.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[(int(r["ei"]), str(r["field"]))] = r
        print(f"resume: {len(done)} checkpointed", flush=True)

    pending = [j for j in jobs if j not in done]
    with ckpt.open("a", encoding="utf-8") as fh:
        for ei, field in tqdm(pending, total=len(pending), desc="probe", unit="call", file=sys.stderr):
            rec = rec_by[(ei, field)]
            res = run_field(graph, FieldExtractRequest(
                pack_name="merger", field=field, event_id=rec.event_id, accession=rec.key,
                model=args.model, validate_enabled=field in VALIDATE_FIELDS, cascade=True,
            ))
            pred = (res.pred or "").strip()
            g = gold[(ei, field)]
            out, base_pred = S.outcome(g, pred, field), stack.get((ei, field), "")
            base_out = S.outcome(g, base_pred, field)
            row = {
                "ei": ei, "field": field, "accession": rec.accession, "gold": g,
                "baseline_pred": base_pred, "baseline_outcome": base_out,
                "pred": pred, "outcome": out, "pass_used": res.pass_used,
                "delta": (
                    "improved" if out in OK and base_out not in OK
                    else "worse" if base_out in OK and out not in OK
                    else "still_ok" if out in OK else "still_bad"
                ),
            }
            done[(ei, field)] = row
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()

    rows = [done[j] for j in jobs if j in done]
    summary = {
        "n_jobs": len(rows),
        "delta": dict(Counter(r["delta"] for r in rows)),
        "by_field": {f: dict(Counter(r["delta"] for r in rows if r["field"] == f)) for f in fields},
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "details.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2), flush=True)
    for kind in ("improved", "worse"):
        print(f"\n{kind}:", flush=True)
        for r in rows:
            if r["delta"] == kind:
                print(f"  {r['field']:22} ei={r['ei']:<4} {r['baseline_outcome']}→{r['outcome']}  "
                      f"pred={r['pred'][:60]!r}  gold={r['gold'][:45]!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
