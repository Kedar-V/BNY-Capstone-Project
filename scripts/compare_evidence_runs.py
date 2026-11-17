#!/usr/bin/env python3
"""Compare micro / per-field F1 across runs that share an evidence_pack_id.

  .venv/bin/python scripts/compare_evidence_runs.py \\
      outputs/tender_eval/experiments/runs/frozen_..._gemma \\
      outputs/tender_eval/experiments/runs/frozen_..._qwen \\
      --out outputs/tender_eval/experiments/runs/compare_gemma_qwen.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


def _load_summary(run: Path) -> dict[str, Any]:
    path = run / "summary.json"
    if not path.exists():
        raise SystemExit(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare frozen-evidence SLM runs")
    p.add_argument("runs", nargs="+", type=Path, help="run dirs with summary.json")
    p.add_argument("--out", type=Path, default=None, help="write compare.csv here")
    args = p.parse_args(argv)
    if len(args.runs) < 2:
        print("need at least two run dirs", file=sys.stderr)
        return 2

    summaries = [(run, _load_summary(run)) for run in args.runs]
    pack_ids = {s.get("evidence_pack_id") for _, s in summaries}
    if None in pack_ids:
        print(
            "warning: one or more runs lack evidence_pack_id (not from eval_from_evidence_pack)",
            file=sys.stderr,
        )
    pack_ids.discard(None)
    if len(pack_ids) > 1:
        print(
            f"runs use different evidence_pack_id values: {sorted(pack_ids)}",
            file=sys.stderr,
        )
        return 2

    # Union of fields in order of the first run
    fields = list(summaries[0][1].get("fields") or [])
    for _, s in summaries[1:]:
        for f in s.get("fields") or []:
            if f not in fields:
                fields.append(f)

    labels = []
    for run, s in summaries:
        labels.append(s.get("model") or run.name)

    # Header
    print(f"evidence_pack_id={next(iter(pack_ids), None)}")
    header = ["metric", *labels]
    rows: list[dict[str, Any]] = []

    micro_row = {"metric": "micro_f1"}
    for lab, (_, s) in zip(labels, summaries):
        micro_row[lab] = (s.get("micro") or {}).get("f1")
    rows.append(micro_row)
    print("\t".join(str(micro_row.get(h, "")) for h in header))

    for field in fields:
        row = {"metric": field}
        for lab, (_, s) in zip(labels, summaries):
            pf = (s.get("per_field") or {}).get(field) or {}
            row[lab] = pf.get("f1")
        rows.append(row)
        print("\t".join(str(row.get(h, "")) for h in header))

    out = args.out
    if out is None:
        out = summaries[0][0] / "compare.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
