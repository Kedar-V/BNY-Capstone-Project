#!/usr/bin/env python3
"""Experimental merger top-1 assembly: role-aware parties and cash amounts.

Uses only saved GLiNER candidates and source quotes for selection. Reference rows
are consulted after prediction for provisional diagnostics, never for assembly.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.eval_merger import CORE_FIELDS, normalized, soft_match
from scripts import tune_merger_gliner_v2 as v2


def select(values: list[dict], field: str) -> dict | None:
    """Select one candidate without consulting reference values."""
    if field == "acquirer":
        return v2.select(values, field, role_aware=True)
    eligible = [v for v in values if float(v.get("score") or 0) >= v2.THRESHOLD]
    if not eligible:
        return None
    if field == "target":
        groups: dict[str, list[dict]] = defaultdict(list)
        for value in eligible:
            key = normalized(value.get("value"))
            if key:
                groups[key].append(value)
        if not groups:
            return None

        def group_score(key: str) -> float:
            mentions = groups[key]
            name = mentions[0]["value"].strip()
            full_name = bool(v2.ORGANIZATION_SUFFIX.search(name) and len(name) > 10)
            generic = len(name) < 8 or key in v2.GENERIC_ROLES
            return (max(float(v["score"]) for v in mentions)
                    + 0.12 * math.log1p(len(mentions))
                    + 0.08 * full_name - 0.16 * generic)

        best = max(groups, key=group_score)
        return max(groups[best], key=lambda v: float(v["score"]))
    if field == "cash_consideration":
        # This GLiNER label asks for per-share cash. Reject descriptive labels
        # and scaled transaction totals such as "$360 million"; abstain when
        # no plausible unit-sized currency amount was proposed.
        amounts = [v for v in eligible
                   if re.search(r"\$\s*\d", v["value"])
                   and not re.search(r"\b(?:million|billion)\b", v["value"], re.I)]
        return max(amounts, key=lambda v: float(v["score"])) if amounts else None
    return max(eligible, key=lambda v: float(v["score"]))


def evaluate(reference: list[dict], predictions: dict[str, dict], cohort: set[str], *, enhanced: bool) -> dict:
    by_field = {field: Counter() for field in CORE_FIELDS}
    for row in reference:
        accession = row["accession_number"].strip()
        if accession not in cohort:
            continue
        for field in CORE_FIELDS:
            values = predictions[accession]["candidates"].get(field, [])
            candidate = select(values, field) if enhanced else v2.select(values, field, role_aware=False)
            pred = candidate["value"] if candidate else ""
            gold = row.get(field, "")
            if not normalized(pred) and not normalized(gold):
                continue
            count = by_field[field]
            if pred and gold and soft_match(pred, gold):
                count["tp"] += 1
            elif pred and gold:
                count["fp"] += 1
                count["fn"] += 1
            elif pred:
                count["fp"] += 1
            else:
                count["fn"] += 1

    def metric(count: Counter) -> dict:
        tp, fp, fn = (count[k] for k in ("tp", "fp", "fn"))
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None,
                "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}

    micro = Counter()
    for count in by_field.values():
        micro.update(count)
    return {"micro": metric(micro), "per_field": {f: metric(c) for f, c in by_field.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    with args.reference.open(newline="", encoding="utf-8-sig") as stream:
        reference = list(csv.DictReader(stream))
    with args.predictions.open(encoding="utf-8") as stream:
        docs = [json.loads(line) for line in stream if line.strip()]
    predictions = {d["accession_number"]: d for d in docs}
    if len(predictions) != len(docs):
        raise ValueError("Duplicate prediction accession")
    overlap = {r["accession_number"].strip() for r in reference} & predictions.keys()
    development = {a for a in overlap if int(hashlib.sha256(a.encode()).hexdigest(), 16) % 2 == 0}
    comparison = overlap - development
    summary = {
        "metric_type": "provisional_unverified_reference_agreement",
        "method": "v2 acquirer + target consensus/full-name + abstaining on non-unit cash amounts",
        "reference_sha256": v2.sha256(args.reference),
        "predictions_sha256": v2.sha256(args.predictions),
        "split_rule": "SHA256(accession) mod 2: even=development, odd=comparison",
        "development_accessions": sorted(development),
        "comparison_accessions": sorted(comparison),
        "results": {name: {"baseline": evaluate(reference, predictions, cohort, enhanced=False),
                           "enhanced": evaluate(reference, predictions, cohort, enhanced=True)}
                    for name, cohort in (("development", development), ("comparison", comparison), ("all_overlap", overlap))},
        "limitations": "Reference rows are unverified, some filings have multiple deals, and the comparison cohort has been inspected in prior experiments. Scores are not validated accuracy.",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "ranked_top1.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("accession_number", "filing_date", "field", "value", "score", "selection_method", "source_quote"))
        writer.writeheader()
        for accession, doc in sorted(predictions.items()):
            for field in CORE_FIELDS:
                candidate = select(doc["candidates"].get(field, []), field)
                if candidate:
                    writer.writerow({"accession_number": accession, "filing_date": doc.get("filing_date", ""),
                                     "field": field, "value": candidate["value"], "score": candidate["score"],
                                     "selection_method": ("role_aware_acquirer" if field == "acquirer" else
                                                          "target_consensus" if field == "target" else
                                                          "explicit_cash_amount" if field == "cash_consideration" else "max_score"),
                                     "source_quote": candidate.get("source_quote", "")})
    for name, result in summary["results"].items():
        print(name, result["baseline"]["micro"]["f1"], "->", result["enhanced"]["micro"]["f1"])


if __name__ == "__main__":
    main()
