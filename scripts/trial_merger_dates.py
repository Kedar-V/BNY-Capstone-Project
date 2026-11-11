#!/usr/bin/env python3
"""Trial date-context gating and SEC-text meeting-date candidate recovery.

Creates evidence-linked date candidates for review. It does not assign deals or
claim validated accuracy against the unverified Evaluation reference.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import statistics
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.eval_merger import CORE_FIELDS, normalized, soft_match
from scripts import tune_merger_gliner_v3 as v3

DATE_TEXT = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}/20\d{2}\b", re.I)
MEETING_CUE = re.compile(
    r"\b(?:special meeting|meeting of (?:the )?(?:stockholders|shareholders)|stockholders? meeting|shareholders? meeting)\b", re.I)
MEETING_LINK = re.compile(r"\b(?:held|scheduled|convene|take place|on|at)\b", re.I)
DATE_CUES = {
    "shareholder_vote_date": re.compile(
        r"\b(?:special meeting|annual meeting|shareholders? meeting|stockholders? meeting|meeting of (?:the )?stockholders|vote on|to vote|meeting will be held)\b", re.I),
    "effective_date": re.compile(
        r"\b(?:effective time|merger effective|become effective|effective date|certificate of merger)\b", re.I),
}
NEGATIVE_DATE_CONTEXT = re.compile(
    r"\b(?:agreement|plan of merger|dated|record date|expiration date|report|entered into|filed on|as of)\b", re.I)


def date_values(text: str) -> set[str]:
    values = set()
    for match in DATE_TEXT.finditer(text):
        for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y"):
            try:
                values.add(dt.datetime.strptime(match.group(), fmt).date().isoformat())
                break
            except ValueError:
                pass
    return values


def date_iso(raw: str) -> str | None:
    return next(iter(date_values(raw)), None)


def near_span(candidate: dict, width: int = 110) -> str:
    quote = candidate.get("source_quote", "")
    offset = int(candidate["start"]) - int(candidate["quote_start"])
    return quote[max(0, offset - width):offset + len(candidate["value"]) + width]


def gated_date(candidates: list[dict], field: str) -> dict | None:
    """Abstain unless a GLiNER date has field-specific nearby context."""
    eligible = []
    for candidate in candidates:
        if float(candidate.get("score") or 0) < v3.v2.THRESHOLD:
            continue
        context = near_span(candidate)
        if DATE_CUES[field].search(context) and not NEGATIVE_DATE_CONTEXT.search(context):
            eligible.append(candidate)
    return max(eligible, key=lambda x: float(x["score"])) if eligible else None


def meeting_candidates(text: str) -> list[dict]:
    """Find dates close to a meeting cue and a scheduling connector."""
    by_date: dict[str, dict] = {}
    for cue in MEETING_CUE.finditer(text):
        lo, hi = max(0, cue.start() - 80), min(len(text), cue.end() + 80)
        for match in DATE_TEXT.finditer(text, lo, hi):
            between = text[min(cue.end(), match.end()):max(cue.start(), match.start())]
            if not MEETING_LINK.search(between):
                continue
            iso = date_iso(match.group())
            if not iso:
                continue
            distance = min(abs(match.start() - cue.end()), abs(cue.start() - match.end()))
            strict = bool(re.search(r"\b(?:held|scheduled|convene|take place)\b", between, re.I)) and "." not in between and ";" not in between
            old = by_date.get(iso)
            if old is not None and (old["selection_tier"] == "strict", -old["cue_distance"]) >= (strict, -distance):
                continue
            qlo, qhi = max(0, min(cue.start(), match.start()) - 110), min(len(text), max(cue.end(), match.end()) + 140)
            by_date[iso] = {"date_iso": iso, "date_text": match.group(),
                            "date_start": match.start(), "date_end": match.end(),
                            "meeting_cue": cue.group(), "cue_distance": distance,
                            "selection_tier": "strict" if strict else "broad",
                            "source_quote": text[qlo:qhi], "quote_start": qlo, "quote_end": qhi}
    return sorted(by_date.values(), key=lambda x: (x["date_iso"], x["cue_distance"]))


def scored_fields(reference: list[dict], predictions: dict[str, dict], cohort: set[str], *, gate_dates: bool) -> dict:
    counts = {f: Counter() for f in CORE_FIELDS}
    for row in reference:
        accession = row["accession_number"].strip()
        if accession not in cohort:
            continue
        for field in CORE_FIELDS:
            values = predictions[accession]["candidates"].get(field, [])
            candidate = (gated_date(values, field) if gate_dates and field in DATE_CUES
                         else v3.select(values, field))
            pred = candidate["value"] if candidate else ""
            gold = row.get(field, "")
            if not normalized(pred) and not normalized(gold):
                continue
            count = counts[field]
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
    for count in counts.values():
        micro.update(count)
    return {"micro": metric(micro), "per_field": {f: metric(c) for f, c in counts.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.reference.open(newline="", encoding="utf-8-sig") as stream:
        reference = list(csv.DictReader(stream))
    with args.predictions.open(encoding="utf-8") as stream:
        docs = [json.loads(line) for line in stream if line.strip()]
    predictions = {d["accession_number"]: d for d in docs}
    if len(predictions) != len(docs):
        raise ValueError("Duplicate accession in predictions")
    overlap = {r["accession_number"].strip() for r in reference} & predictions.keys()
    dev = {a for a in overlap if int(hashlib.sha256(a.encode()).hexdigest(), 16) % 2 == 0}
    comparison = overlap - dev
    date_rows = []
    with zipfile.ZipFile(args.archive) as archive:
        for doc in docs:
            text = json.loads(archive.read(doc["archive_path"])).get("text") or ""
            for candidate in meeting_candidates(text):
                def nearby(field: str) -> str:
                    values = sorted(doc.get("candidates", {}).get(field, []),
                                    key=lambda v: abs(int(v["start"]) - candidate["date_start"]))
                    result = []
                    for value in values:
                        if abs(int(value["start"]) - candidate["date_start"]) > 900:
                            break
                        if value["value"] not in result:
                            result.append(value["value"])
                        if len(result) >= 3:
                            break
                    return " | ".join(result)

                date_rows.append({"accession_number": doc["accession_number"],
                                  "filing_date": doc.get("filing_date", ""),
                                  **candidate,
                                  "nearby_acquirer_mentions": nearby("acquirer"),
                                  "nearby_target_mentions": nearby("target"),
                                  "deal_id": "", "review_status": ""})
    with (args.out_dir / "meeting_date_candidates.csv").open("w", newline="", encoding="utf-8") as stream:
        columns = ("accession_number", "filing_date", "date_iso", "date_text", "date_start", "date_end", "meeting_cue", "cue_distance", "selection_tier", "nearby_acquirer_mentions", "nearby_target_mentions", "source_quote", "quote_start", "quote_end", "deal_id", "review_status")
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(date_rows)
    by_accession: dict[str, set[str]] = {}
    for row in date_rows:
        by_accession.setdefault(row["accession_number"], set()).add(row["date_iso"])
    populated = [r for r in reference if r["accession_number"].strip() in overlap and date_values(r.get("shareholder_vote_date", ""))]
    reference_hits = sum(bool(date_values(r["shareholder_vote_date"]) & by_accession.get(r["accession_number"], set())) for r in populated)
    gliner_hits = sum(any(date_values(c["value"]) & date_values(r["shareholder_vote_date"])
                          for c in predictions[r["accession_number"]]["candidates"].get("shareholder_vote_date", []))
                      for r in populated)
    strict_by_accession: dict[str, set[str]] = {}
    for row in date_rows:
        if row["selection_tier"] == "strict":
            strict_by_accession.setdefault(row["accession_number"], set()).add(row["date_iso"])
    strict_hits = sum(bool(date_values(r["shareholder_vote_date"]) & strict_by_accession.get(r["accession_number"], set())) for r in populated)
    summary = {
        "metric_type": "provisional_reference_agreement_and_candidate_recall",
        "reference_sha256": v3.v2.sha256(args.reference),
        "predictions_sha256": v3.v2.sha256(args.predictions),
        "archive_sha256": v3.v2.sha256(args.archive),
        "documents": len(docs), "meeting_date_candidates": len(date_rows),
        "strict_meeting_date_candidates": sum(r["selection_tier"] == "strict" for r in date_rows),
        "overlap_accessions": len(overlap),
        "meeting_date_candidate_recall": {"reference_rows_with_parseable_date": len(populated),
                                          "rows_hit_by_gliner_any_candidate": gliner_hits,
                                          "rows_hit_by_rule_candidate_set": reference_hits,
                                          "rows_hit_by_strict_rule_candidate_set": strict_hits,
                                          "median_distinct_candidate_dates_per_overlap_filing": statistics.median(len(by_accession.get(a, set())) for a in overlap),
                                          "median_strict_candidate_dates_per_overlap_filing": statistics.median(len(strict_by_accession.get(a, set())) for a in overlap)},
        "results": {name: {"current_assembly": scored_fields(reference, predictions, cohort, gate_dates=False),
                           "date_gated": scored_fields(reference, predictions, cohort, gate_dates=True)}
                    for name, cohort in (("development", dev), ("comparison", comparison), ("all_overlap", overlap))},
        "limitations": "Candidate-set recall is not precision, top-1 accuracy, or deal-level validation. Reference rows are unverified and often multi-deal. The comparison group was inspected previously. Meeting-date candidates need deal and party review; date gating abstains rather than recovering missing canonical dates.",
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"meeting_date_candidate_recall": summary["meeting_date_candidate_recall"],
                      "micro_f1": {k: {variant: x["micro"]["f1"] for variant, x in v.items()}
                                   for k, v in summary["results"].items()}}, indent=2))


if __name__ == "__main__":
    main()
