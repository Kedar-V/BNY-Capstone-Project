#!/usr/bin/env python3
"""Recompute the scores of every saved run under outputs/ with the current scorer (common.match), from each run's
details.csv. No model is run. Use after changing how values are compared, then rerun make_figures.py and the
results notebook.

    python mergers_extraction/rescore_all.py
"""
from __future__ import annotations

import json

import pandas as pd

import common

if __name__ == "__main__":
    rows = []
    for summary in sorted(common.OUTPUTS.rglob("summary.json")):
        folder = summary.parent
        if (folder / "details.csv").exists() and (folder / "per_field.csv").exists():
            rows.append(common.rescore(folder))
    print(pd.DataFrame(rows).to_string(index=False))
    for folder in common.OUTPUTS.glob("gliner_finetuned_*_holdout/*_windows"):  # refresh side-by-side tables
        parts = []
        for tag in ("finetuned", "zero_shot"):
            if (folder / tag / "per_field.csv").exists():
                pf = pd.read_csv(folder / tag / "per_field.csv").set_index("field")
                mode = common.window_mode_of(pf.reset_index())
                micro = json.loads((folder / tag / "summary.json").read_text())["micro"]
                overall = pd.DataFrame({f"{mode}_f1": [micro[mode]["f1"]], "oracle_f1": [micro["oracle"]["f1"]]},
                                       index=["MICRO"])
                parts.append(pd.concat([pf[[f"{mode}_f1", "oracle_f1"]], overall]).add_prefix(f"{tag}_"))
        if parts:
            pd.concat(parts, axis=1).astype(float).round(3).to_csv(folder / "comparison.csv")
