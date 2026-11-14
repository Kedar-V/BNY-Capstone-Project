#!/usr/bin/env python3
"""The combined merger pipeline: for each field, the method that scored best on the validation deals, then one
score on the held-out filings.

Candidates per field: fine-tuned GLiNER (learned windows), date rules, temporal NER, the cash filter, the role rule,
the ratio rule, GLiNER + date checks, GLiNER + role checks and Qwen3 4B. They are compared on the validation deals only (common.validation_accessions), never on the held-out
filings. Date fields are compared by F0.5, which weighs precision twice as much as recall, because a wrong date is
worse than a blank; other fields by F1. Ties go to higher precision, then to fewer wrong answers.

    python mergers_extraction/pipeline.py --model medium_val_2300steps

Writes outputs/pipeline/combined_<model>_holdout/ (scores, details, routing.csv, predictions.csv); the run appears
in visualize_mergers_results.ipynb as "combined pipeline".
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import common
from eval_methods import FIELDS as METHOD_FIELDS

DATE_FIELDS = {"shareholder_vote_date", "effective_date", "election_deadline"}
KINDS = {**{f: kind for f, (_, kind) in common.SPAN_FIELDS.items()}, **METHOD_FIELDS["qwen"],
         "election_deadline": "date_or_text"}


def gliner_predictions(model: str, split: str) -> dict[str, dict[str, str]]:
    path = common.OUTPUTS / f"gliner_finetuned_{model}_{split}" / "learned_windows" / "finetuned" / "details.csv"
    details = pd.read_csv(path, dtype=str, keep_default_na=False)
    details = details[details["mode"] == "learned"]
    out: dict[str, dict[str, str]] = {}
    for _, row in details.iterrows():
        out.setdefault(row["accession_number"], {})[row["field"]] = row["pred"]
    return out


def method_predictions(folder: Path) -> dict[str, dict[str, str]]:
    preds = pd.read_csv(folder / "predictions.csv", dtype=str, keep_default_na=False)
    out: dict[str, dict[str, str]] = {}
    for _, row in preds.iterrows():
        out.setdefault(row["accession_number"], {})[row["field"]] = row["value"]
    return out


def candidates(model: str, split: str) -> dict[str, dict[str, dict[str, str]]]:
    """method name -> accession -> field -> value, for one split."""
    root = common.OUTPUTS / "methods"
    folders = {"date rules": "date_rules", "temporal NER": "temporal_ner", "Qwen3 4B": "qwen",
               "cash filter": f"cash_filter_{model}", "role rule": f"role_rule_{model}",
               "ratio rule": f"ratio_rule_{model}", "GLiNER + date checks": f"gliner_dates_{model}",
               "GLiNER + role checks": f"gliner_roles_{model}"}
    out = {"fine-tuned GLiNER": gliner_predictions(model, split)}
    for name, tag in folders.items():
        folder = root / "validation" / tag if split == "validation" else root / f"{tag}_holdout"
        if (folder / "predictions.csv").exists():
            out[name] = method_predictions(folder)
        else:
            print(f"missing {folder}; {name} is not a candidate")
    return out


def f_beta(p, r, beta):
    if not p or not r:
        return 0.0
    return (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="fine-tuned GLiNER run under models/merger_gliner/")
    args = ap.parse_args()

    gt_all = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv")
    gt_val = gt_all[gt_all["accession_number"].isin(common.validation_accessions())]
    gt_test = gt_all[gt_all["accession_number"].isin(common.holdout_accessions())]
    val, test = candidates(args.model, "validation"), candidates(args.model, "holdout")

    routing, chosen = [], {}
    for field, kind in KINDS.items():
        beta = 0.5 if field in DATE_FIELDS else 1.0
        best = None
        for name, preds in val.items():
            if not any(field in p for p in preds.values()) or name not in test:
                continue
            pf, _, _ = common.score_predictions(gt_val, preds, {field: kind}, "v")
            r = pf.iloc[0]
            score = f_beta(r["v_precision"], r["v_recall"], beta)
            routing.append({"field": field, "method": name, "validation_precision": r["v_precision"],
                            "validation_recall": r["v_recall"], "validation_f1": r["v_f1"],
                            f"validation_score (F{beta:g})": round(score, 3), "wrong_answers": r["fp"]})
            # ties: higher precision, then fewer wrong answers (abstaining beats guessing)
            key = (score, r["v_precision"] or 0, -r["fp"])
            if best is None or key > best[1]:
                best = (name, key)
        if best:
            chosen[field] = best[0]
    routing = pd.DataFrame(routing)
    routing["chosen"] = [chosen.get(f) == m for f, m in zip(routing["field"], routing["method"])]

    combined: dict[str, dict[str, str]] = {}
    for field, name in chosen.items():
        for acc, values in test[name].items():
            combined.setdefault(acc, {})[field] = values.get(field, "")
    per_field, micro, details = common.score_predictions(gt_test, combined, {f: KINDS[f] for f in chosen}, "combined")
    per_field["method_used"] = per_field["field"].map(chosen)
    out = common.OUTPUTS / "pipeline" / f"combined_{args.model}_holdout"
    common.write_results(out, per_field, micro, details, {
        "method": "combined pipeline", "model": args.model, "split": "holdout",
        "filings": int(gt_test["accession_number"].nunique()), "records": len(gt_test), "routing": chosen,
        "routing_chosen_on": f"{gt_val['accession_number'].nunique()} validation filings"})
    routing.to_csv(out / "routing.csv", index=False)
    pd.DataFrame([{"accession_number": a, "field": f, "value": v, "method": chosen[f]}
                  for a, vals in combined.items() for f, v in vals.items()]).to_csv(out / "predictions.csv", index=False)
    pd.set_option("display.width", 220)
    print(per_field[["field", "method_used", "tp", "fp", "fn", "combined_precision", "combined_recall", "combined_f1"]]
          .to_string(index=False))
    print("micro", {k: round(v, 3) if isinstance(v, float) else v for k, v in micro["combined"].items()}, "->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
