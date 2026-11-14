#!/usr/bin/env python3
"""Run a non-GLiNER method on the merger filings and score it like the GLiNER runs.

    python mergers_extraction/eval_methods.py date_rules --split train     # develop on training filings
    python mergers_extraction/eval_methods.py date_rules                   # final score on the held-out filings

Methods: date_rules, temporal_ner, cash_filter, role_rule, ratio_rule, gliner_dates, gliner_roles, qwen. Held-out results go to
outputs/methods/<method>_holdout/ (per_field.csv, details.csv, summary.json, predictions.csv with evidence) and appear
in visualize_mergers_results.ipynb. Training-split runs go to outputs/methods/dev/ and are for development only.
"""
from __future__ import annotations

import argparse
import json
import time

import pandas as pd

import common

# field -> comparison kind for each method
FIELDS = {
    "date_rules": {"shareholder_vote_date": "date", "effective_date": "date", "election_deadline": "date_or_text"},
    "temporal_ner": {"shareholder_vote_date": "date", "effective_date": "date", "election_deadline": "date_or_text",
                     "expected_closing": "text"},
    "cash_filter": {"cash_consideration": "money"},
    "role_rule": {"acquirer": "name", "target": "name", "merger_subsidiary": "name"},
    "ratio_rule": {"stock_exchange_ratio": "number"},
    "gliner_roles": {"acquirer": "name", "target": "name", "merger_subsidiary": "name"},
    "gliner_dates": {"shareholder_vote_date": "date", "effective_date": "date", "election_deadline": "date_or_text"},
    "qwen": {"stock_exchange_ratio": "number", "election_deadline": "date_or_text", "shareholder_vote_date": "date",
             "effective_date": "date", "event_status": "label", "consideration_type": "label",
             "available_options": "text", "default_option": "text", "closing_conditions": "text",
             "cash_consideration_qualifications": "text", "stock_exchange_ratio_qualifications": "text",
             "other_consideration": "text", "event_status_details": "text"},
}
METHOD_NAMES = {"date_rules": "date rules", "temporal_ner": "temporal NER + date rules", "cash_filter":
                "fine-tuned GLiNER + cash filter", "role_rule": "merger-agreement role rule + GLiNER", "qwen": "Qwen3 4B",
                "ratio_rule": "fine-tuned GLiNER + no-stock and formula checks",
                "gliner_dates": "fine-tuned GLiNER + date checks", "gliner_roles": "fine-tuned GLiNER + role checks"}
READS = {"date_rules": "fulltext", "temporal_ner": "learned", "cash_filter": "learned", "role_rule": "fulltext",
         "qwen": "learned", "ratio_rule": "learned",
         "gliner_dates": "learned", "gliner_roles": "learned"}


def accessions(split: str, gt: pd.DataFrame) -> list[str]:
    if split == "validation":
        wanted = set(common.validation_accessions())
    else:
        splits = pd.read_csv(common.SPLITS_PATH, dtype=str)
        wanted = set(splits.loc[splits["split"] == split, "accession_number"])
    return [a for a in dict.fromkeys(gt["accession_number"]) if a in wanted]


def run(method: str, gt: pd.DataFrame, accs: list[str], **kw) -> dict[str, dict[str, tuple[str, str]]]:
    first = gt.drop_duplicates("accession_number").set_index("accession_number")
    forms = first["form"].to_dict()
    filed = {a: pd.Timestamp(d).date() for a, d in first["filing_date"].items()}
    if method == "date_rules":
        import date_rules
        return {a: date_rules.predict(common.filing_text(a), forms[a], filed[a]) for a in accs}
    if method == "temporal_ner":
        import temporal_dates
        return temporal_dates.predict_all(accs, forms, filed)
    if method == "cash_filter":
        import cash_filter
        return cash_filter.predict_all(accs, model=kw.get("model"))
    if method == "role_rule":
        import role_rule
        return role_rule.predict_all(accs, model=kw.get("model"))
    if method == "gliner_roles":
        import gliner_roles
        return gliner_roles.predict_all(accs, kw.get("model"))
    if method == "gliner_dates":
        import gliner_dates
        return gliner_dates.predict_all(accs, kw.get("model"), forms, filed)
    if method == "ratio_rule":
        import ratio_rule
        return ratio_rule.predict_all(accs, model=kw.get("model"), split=kw.get("split"))
    if method == "qwen":
        import qwen_fields
        return qwen_fields.predict_all(accs, forms, filed, list(FIELDS["qwen"]))
    raise SystemExit(f"unknown method {method}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("method", choices=list(FIELDS))
    ap.add_argument("--split", choices=["holdout", "validation", "train"], default="holdout")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="medium_500steps_573filings", help="fine-tuned GLiNER for cash_filter/role_rule")
    args = ap.parse_args()

    gt = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv")
    accs = accessions(args.split, gt)[: args.limit]
    gt = gt[gt["accession_number"].isin(accs)]
    started = time.time()
    raw = run(args.method, gt, accs, model=args.model, split=args.split)
    values = {a: {f: v[0] for f, v in fields.items()} for a, fields in raw.items()}
    mode = READS[args.method]
    per_field, micro, details = common.score_predictions(gt, values, FIELDS[args.method], mode)
    # GLiNER-based methods are named after their model, except the first fine-tuned model's runs
    tag = args.method if args.method not in ("cash_filter", "role_rule", "ratio_rule", "gliner_dates", "gliner_roles") or args.model == "medium_500steps_573filings" \
        else f"{args.method}_{args.model}"
    out = {"holdout": common.OUTPUTS / "methods" / f"{tag}_holdout",
           "validation": common.OUTPUTS / "methods" / "validation" / tag,
           "train": common.OUTPUTS / "methods" / "dev" / f"{tag}_train"}[args.split]
    common.write_results(out, per_field, micro, details, {
        "method": METHOD_NAMES[args.method], "model": args.model if tag != args.method else METHOD_NAMES[args.method],
        "split": args.split,
        "filings": len(accs), "records": len(gt), "reads": mode, "seconds": round(time.time() - started)})
    pd.DataFrame([{"accession_number": a, "field": f, "value": v[0], "evidence": v[1]}
                  for a, fields in raw.items() for f, v in fields.items()]).to_csv(out / "predictions.csv", index=False)
    pd.set_option("display.width", 220)
    show = per_field[["field", "tp", "fp", "fn", "gt_absence_values", f"{mode}_precision", f"{mode}_recall", f"{mode}_f1"]]
    print(show.to_string(index=False))
    print("micro", {k: round(v, 3) if isinstance(v, float) else v for k, v in micro[mode].items()}, "->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
