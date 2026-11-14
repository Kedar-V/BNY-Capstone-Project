#!/usr/bin/env python3
"""Score every saved checkpoint of a fine-tuned GLiNER run on the validation deals (learned windows, span fields) and
make the best one the run's model (models/merger_gliner/<name>/final; the last step is kept as last/). The 103
held-out filings are not used, so the held-out score of the chosen checkpoint stays an honest test.

    python mergers_extraction/select_checkpoint.py --name medium_val_2300steps
"""
from __future__ import annotations

import argparse
import json
import re
import shutil

import pandas as pd

import common
from window_selection import Selector


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--limit", type=int, help="first N validation filings only (for a quick test)")
    args = ap.parse_args()

    run = common.MODELS / args.name
    gt = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv")
    gt = gt[gt["accession_number"].isin(common.validation_accessions()[: args.limit])]
    selector = Selector.load()
    window_fn = lambda text: selector.select(text, per_field=5, max_windows=50)  # noqa: E731
    candidates = sorted((p for p in run.glob("checkpoint-*") if p.is_dir()), key=lambda p: int(p.name.split("-")[1]))
    candidates.append(run / "final")

    from gliner import GLiNER
    rows = []
    for path in candidates:
        _, micro, _ = common.evaluate(GLiNER.from_pretrained(str(path)), gt, common.SPAN_FIELDS, window_fn=window_fn,
                                      window_name="learned", oracle=False, log=lambda *_: None)
        step = int(path.name.split("-")[1]) if path.name.startswith("checkpoint") else "final"
        rows.append({"checkpoint": path.name, "step": step, **{k: micro["learned"][k] for k in ("precision", "recall", "f1")}})
        print(rows[-1], flush=True)
    table = pd.DataFrame(rows)
    table.to_csv(run / "checkpoint_selection.csv", index=False)
    best = table.loc[table["f1"].idxmax()]
    if best["checkpoint"] != "final":  # the last step is kept as last/, the best becomes final/
        if (run / "last").exists():
            shutil.rmtree(run / "last")
        (run / "final").rename(run / "last")
        shutil.copytree(run / best["checkpoint"], run / "final")
    meta_path = run / "train_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta["checkpoint_selection"] = {"chosen": str(best["checkpoint"]), "validation_f1": float(best["f1"]),
                                    "validation_filings": int(gt["accession_number"].nunique()), "table": rows}
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    print(table.round(3).to_string(index=False))
    print("chosen:", best["checkpoint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
