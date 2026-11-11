#!/usr/bin/env python3
"""Experimental role-aware reranking of saved merger GLiNER spans.

Reference values are used only for evaluation, never to rank a document's candidates.
All scores are provisional agreement with unverified reference rows.
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

THRESHOLD = 0.4
FREQUENCY_BONUS = 0.12
FULL_NAME_BONUS = 0.08
GENERIC_PENALTY = 0.16
ADVISORY_PENALTY = 0.24
ORGANIZATION_SUFFIX = re.compile(r"\b(?:inc\.?|corp\.?|corporation|company|co\.?|llc|ltd\.?|plc|bancorp|holdings?|group|limited)\b", re.I)
ADVISORY_CONTEXT = re.compile(r"\b(?:advisory|underwriting|financial advisor|fairness opinion|financial point of view|investment bank|dealer manager|financial adviser)\b", re.I)
GENERIC_ROLES = {"parent", "company", "holdings", "merger sub", "purchaser", "acquirer", "buyer", "surviving corporation", "pubco"}


def select(values: list[dict], field: str, *, role_aware: bool) -> dict | None:
    eligible = [v for v in values if float(v.get("score") or 0) >= THRESHOLD]
    if not eligible:
        return None
    if not role_aware or field != "acquirer":
        return max(eligible, key=lambda v: float(v["score"]))
    groups: dict[str, list[dict]] = defaultdict(list)
    for value in eligible:
        key = normalized(value.get("value"))
        if key:
            groups[key].append(value)
    if not groups:
        return None

    def adjusted(mention: dict) -> float:
        return float(mention["score"]) - ADVISORY_PENALTY * bool(ADVISORY_CONTEXT.search(mention.get("source_quote", "")))

    def group_score(key: str) -> float:
        mentions = groups[key]
        name = mentions[0]["value"].strip()
        full_name = bool(ORGANIZATION_SUFFIX.search(name) and len(name) > 10)
        generic = len(name) < 8 or key in GENERIC_ROLES
        return (max(map(adjusted, mentions))
                + FREQUENCY_BONUS * math.log1p(len(mentions))
                + FULL_NAME_BONUS * full_name
                - GENERIC_PENALTY * generic)

    best_key = max(groups, key=group_score)
    return max(groups[best_key], key=adjusted)


def evaluate(reference: list[dict], predictions: dict[str, dict], cohort: set[str], *, role_aware: bool) -> dict:
    by_field = {field: Counter() for field in CORE_FIELDS}
    for row in reference:
        accession = row["accession_number"].strip()
        if accession not in cohort:
            continue
        for field in CORE_FIELDS:
            candidate = select(predictions[accession]["candidates"].get(field, []), field, role_aware=role_aware)
            predicted = candidate["value"] if candidate else ""
            expected = row.get(field, "")
            if not normalized(predicted) and not normalized(expected):
                continue
            counts = by_field[field]
            if predicted and expected and soft_match(predicted, expected):
                counts["tp"] += 1
            elif predicted and expected:
                counts["fp"] += 1
                counts["fn"] += 1
            elif predicted:
                counts["fp"] += 1
            else:
                counts["fn"] += 1

    def metrics(counts: Counter) -> dict:
        tp, fp, fn = (counts[k] for k in ("tp", "fp", "fn"))
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None,
                "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}

    micro = Counter()
    for counts in by_field.values():
        micro.update(counts)
    return {"micro": metrics(micro), "per_field": {field: metrics(counts) for field, counts in by_field.items()}}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    predictions = {doc["accession_number"]: doc for doc in docs}
    if len(predictions) != len(docs):
        raise ValueError("Duplicate prediction accession")
    overlap = {row["accession_number"].strip() for row in reference} & predictions.keys()
    development = {a for a in overlap if int(hashlib.sha256(a.encode()).hexdigest(), 16) % 2 == 0}
    comparison = overlap - development
    summary = {
        "metric_type": "provisional_unverified_reference_agreement",
        "reference_sha256": sha256(args.reference),
        "predictions_sha256": sha256(args.predictions),
        "selection": {"threshold": THRESHOLD, "frequency_bonus": FREQUENCY_BONUS,
                      "full_name_bonus": FULL_NAME_BONUS, "generic_penalty": GENERIC_PENALTY,
                      "advisory_context_penalty": ADVISORY_PENALTY},
        "split_rule": "SHA256(accession) mod 2: even=development, odd=comparison",
        "development_accessions": sorted(development),
        "comparison_accessions": sorted(comparison),
        "results": {name: {"baseline": evaluate(reference, predictions, cohort, role_aware=False),
                           "role_aware": evaluate(reference, predictions, cohort, role_aware=True)}
                    for name, cohort in (("development", development), ("comparison", comparison), ("all_overlap", overlap))},
        "limitations": "Unverified reference candidates; multiple deal rows reuse one filing prediction; relaxed matching; comparison cohort was inspected during previous tuning. These F1 scores are not validated accuracy or a clean held-out test.",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "ranked_top1.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("accession_number", "filing_date", "field", "value", "score", "selection_method", "source_quote"))
        writer.writeheader()
        for accession, doc in sorted(predictions.items()):
            for field in CORE_FIELDS:
                candidate = select(doc["candidates"].get(field, []), field, role_aware=True)
                if candidate:
                    writer.writerow({"accession_number": accession,
                                     "filing_date": doc.get("filing_date", ""),
                                     "field": field, "value": candidate["value"],
                                     "score": candidate["score"],
                                     "selection_method": "role_aware_acquirer" if field == "acquirer" else "max_score",
                                     "source_quote": candidate.get("source_quote", "")})
    for name, result in summary["results"].items():
        print(name, "micro F1", result["baseline"]["micro"]["f1"], "->", result["role_aware"]["micro"]["f1"])


if __name__ == "__main__":
    main()
