"""Score tender Concise Reps against notebooks/evaluation/tender_offers.csv.

Join key: accession_number (GT) ↔ source_accession / doc_inventory.accession (pred).
Do not join on event_id — GT uses tender_offer_{accession}; preprocess uses file numbers.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.preprocess.contracts import LABEL_TO_FIELD_HINT

# Full GT schema (coverage / reporting). Narrative fields are not GLiNER-owned.
GT_VALUE_FIELDS: tuple[str, ...] = (
    "subject_company",
    "bidder",
    "parent",
    "acquisition_subsidiary",
    "dealer_manager",
    "depositary",
    "information_agent",
    "other_parties",
    "security_description",
    "ticker",
    "cusip",
    "isin",
    "event_status",
    "event_status_details",
    "mandatory_voluntary_indicator",
    "offer_price_type",
    "offer_price",
    "currency",
    "offer_price_basis",
    "offer_price_qualifications",
    "expiration_date",
    "withdrawal_deadline",
    "settlement_date",
    "effective_date",
    "minimum_tender_condition",
    "proration_terms",
    "tendering_conditions",
    "available_options",
    "default_option",
    "financial_terms",
    "conditions_restrictions",
)

# Business + GLiNER-friendly fields (default scored set when --fields core).
CORE_GT_FIELDS: tuple[str, ...] = (
    "subject_company",
    "bidder",
    "security_description",
    "cusip",
    "isin",
    "ticker",
    "offer_price",
    "currency",
    "expiration_date",
    "withdrawal_deadline",
    "settlement_date",
    "effective_date",
    "minimum_tender_condition",
    "proration_terms",
)

# GT column → Concise Rep field_hint (top-1).
GT_TO_HINT: dict[str, str] = {
    "subject_company": "target",
    "bidder": "offeror",
    "parent": "parent",
    "acquisition_subsidiary": "purchaser",
    "dealer_manager": "dealer_manager",
    "depositary": "depositary",
    "information_agent": "information_agent",
    "other_parties": "other_parties",
    "security_description": "security_description",
    "ticker": "ticker",
    "cusip": "cusip",
    "isin": "isin",
    "event_status": "event_status",
    "event_status_details": "event_status_details",
    "mandatory_voluntary_indicator": "mandatory_voluntary_indicator",
    "offer_price_type": "offer_price_type",
    "offer_price": "offer_price",
    "currency": "currency",
    "offer_price_basis": "offer_price_basis",
    "offer_price_qualifications": "offer_price_qualifications",
    "expiration_date": "expiration_date",
    "withdrawal_deadline": "withdrawal_deadline",
    "settlement_date": "settlement_date",
    "effective_date": "effective_date",
    "minimum_tender_condition": "minimum_tender_condition",
    "proration_terms": "proration_terms",
    "tendering_conditions": "tendering_conditions",
    "available_options": "available_option",
    "default_option": "default_option",
    "financial_terms": "financial_terms",
    "conditions_restrictions": "conditions_restrictions",
}

_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—"})
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DIGITS = re.compile(r"\d+")


def field_coverage() -> dict[str, Any]:
    """Assert every GT value field has a pipeline hint backed by LABEL_TO_FIELD_HINT."""
    hints = set(LABEL_TO_FIELD_HINT.values())
    missing_map = [f for f in GT_VALUE_FIELDS if f not in GT_TO_HINT]
    unbacked = [f for f, h in GT_TO_HINT.items() if h not in hints]
    return {
        "ok": not missing_map and not unbacked,
        "n_gt_fields": len(GT_VALUE_FIELDS),
        "missing_gt_to_hint": missing_map,
        "hints_not_in_pipeline": unbacked,
        "gt_to_hint": dict(GT_TO_HINT),
    }


def normalize(value: str | None) -> str:
    if value is None:
        return ""
    s = _WS.sub(" ", str(value).strip().lower())
    return "" if s in _NA else s


def _money_amounts(s: str) -> list[float]:
    """Extract comparable dollar/number magnitudes from a string."""
    out: list[float] = []
    for m in re.finditer(r"\$?\s*([\d,]+(?:\.\d+)?)", s):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return out


def _money_close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.05, 0.05 * max(abs(a), abs(b)))


def soft_match(pred: str | None, gold: str | None) -> bool:
    """True if normalized strings match, contain each other, or share date/money tokens.

    Money: magnitudes must be within 5% (or $0.05) so par value $0.001 ≠ NAV text.
    """
    p, g = normalize(pred), normalize(gold)
    if not p or not g:
        return False
    pm, gm = _money_amounts(p), _money_amounts(g)
    moneyish = (
        "$" in (pred or "")
        or "$" in (gold or "")
        or "per share" in p
        or "per share" in g
        or "nav" in p
        or "nav" in g
    )
    if pm and gm and moneyish:
        return any(_money_close(a, b) for a in pm for b in gm)

    if p == g or p in g or g in p:
        return True
    p_tok, g_tok = _NON_ALNUM.sub(" ", p), _NON_ALNUM.sub(" ", g)
    if p_tok in g_tok or g_tok in p_tok:
        return True
    pd, gd = set(_DIGITS.findall(p)), set(_DIGITS.findall(g))
    if pd and gd and (pd <= gd or gd <= pd):
        return True
    return False


def _top1_fact(facts: list[dict[str, Any]], hint: str) -> dict[str, Any] | None:
    items = [f for f in facts if (f.get("field_hint") or "") == hint]
    if not items:
        return None
    return max(items, key=lambda f: float(f.get("rank_score") or f.get("confidence") or 0))


def _top1(facts: list[dict[str, Any]], hint: str) -> str | None:
    best = _top1_fact(facts, hint)
    if not best:
        return None
    raw = best.get("raw")
    return str(raw) if raw is not None else None


def _evidence_from_fact(fact: dict[str, Any] | None) -> dict[str, Any] | None:
    """Per-field extraction evidence (segment + offsets + source doc)."""
    if not fact:
        return None
    value = fact.get("raw")
    segment = fact.get("segment_text") or fact.get("passage") or ""
    return {
        "value": str(value) if value is not None else None,
        "source_accession": fact.get("source_accession"),
        "source_filename": fact.get("source_filename"),
        "doc_role": fact.get("doc_role"),
        "segment_id": fact.get("segment_id"),
        "segment_text": segment,
        "char_start": fact.get("char_start"),
        "char_end": fact.get("char_end"),
        "segment_char_start": fact.get("segment_char_start"),
        "segment_char_end": fact.get("segment_char_end"),
        "char_span": fact.get("char_span"),
        "confidence": fact.get("confidence"),
        "rank_score": fact.get("rank_score"),
        "faq_question": fact.get("faq_question"),
        "section": fact.get("section"),
    }


def accessions_from_rep(rep: dict[str, Any]) -> set[str]:
    accs: set[str] = set()
    for d in rep.get("doc_inventory") or []:
        a = (d.get("accession") or "").strip()
        if a:
            accs.add(a)
    for f in rep.get("candidate_facts") or []:
        a = (f.get("source_accession") or "").strip()
        if a:
            accs.add(a)
    return accs


def load_gt(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_preds(
    preprocess_root: Path, path_name: str = "tender"
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (by_accession, by_event_id) top-1 prediction maps.

    Pipeline events are file-number cohorts; GT rows are per accession. Eval joins
    accession → event_id when the Concise Rep was built from a sibling filing.
    """
    events_root = preprocess_root / path_name / "events"
    by_acc: dict[str, dict[str, Any]] = {}
    by_eid: dict[str, dict[str, Any]] = {}
    if not events_root.exists():
        return by_acc, by_eid
    for ed in sorted(events_root.iterdir()):
        rep_path = ed / "concise" / "event_rep.json"
        if not rep_path.exists():
            continue
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        facts = list(rep.get("candidate_facts") or [])
        hints = set(GT_TO_HINT.values())
        evidence: dict[str, Any] = {}
        pred: dict[str, Any] = {}
        for hint in hints:
            fact = _top1_fact(facts, hint)
            if fact is None:
                pred[hint] = None
                continue
            raw = fact.get("raw")
            pred[hint] = str(raw) if raw is not None else None
            evidence[hint] = _evidence_from_fact(fact)
        pred["_evidence"] = evidence
        eid = str(rep.get("event_id") or ed.name)
        pred["_event_id"] = eid
        pred["_n_facts"] = len(facts)
        pred["_rep_accessions"] = sorted(accessions_from_rep(rep))
        by_eid[eid] = pred
        for acc in accessions_from_rep(rep):
            prev = by_acc.get(acc)
            if prev is None or int(pred["_n_facts"]) >= int(prev.get("_n_facts") or 0):
                by_acc[acc] = pred
    return by_acc, by_eid


def gt_event_ids_from_corpus(
    accessions: set[str],
    documents_parquet: Path,
) -> dict[str, str]:
    """accession → preprocess event_id from corpus documents."""
    import pandas as pd

    docs = pd.read_parquet(documents_parquet, columns=["accession", "event_id"])
    docs = docs[docs["accession"].astype(str).isin(accessions)]
    out: dict[str, str] = {}
    for acc, eid in zip(docs["accession"].astype(str), docs["event_id"].astype(str)):
        out.setdefault(acc, eid)
    return out


def _gold_by_accession(gt_rows: list[dict[str, str]]) -> dict[str, dict[str, set[str]]]:
    """Union gold values per accession (legacy / coverage helpers)."""
    gold: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in gt_rows:
        acc = (row.get("accession_number") or "").strip()
        if not acc:
            continue
        for col in GT_VALUE_FIELDS:
            v = normalize(row.get(col))
            if v:
                gold[acc][col].add(row.get(col) or "")
    return gold


def _gold_rows(gt_rows: list[dict[str, str]]) -> list[tuple[str, str, dict[str, set[str]]]]:
    """One scored unit per GT CSV row: (row_id, accession, fields→{value})."""
    out: list[tuple[str, str, dict[str, set[str]]]] = []
    for i, row in enumerate(gt_rows):
        acc = (row.get("accession_number") or "").strip()
        if not acc:
            continue
        fields: dict[str, set[str]] = {}
        for col in GT_VALUE_FIELDS:
            v = normalize(row.get(col))
            if v:
                fields[col] = {row.get(col) or ""}
        row_id = f"{i}:{acc}"
        out.append((row_id, acc, fields))
    return out


def _empty_per_field() -> dict[str, dict[str, int]]:
    return {
        f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0, "scored": 0}
        for f in GT_VALUE_FIELDS
    }


def _micro_from_per_field(per_field: dict[str, dict[str, int]]) -> dict[str, Any]:
    micro_tp = sum(s["tp"] for s in per_field.values())
    micro_fp = sum(s["fp"] for s in per_field.values())
    micro_fn = sum(s["fn"] for s in per_field.values())
    micro_scored = sum(s["scored"] for s in per_field.values())
    micro_gt = sum(s["gt_present"] for s in per_field.values())
    micro_p = micro_tp / (micro_tp + micro_fp) if (micro_tp + micro_fp) else None
    micro_r = micro_tp / (micro_tp + micro_fn) if (micro_tp + micro_fn) else None
    micro_f1 = (
        (2 * micro_p * micro_r / (micro_p + micro_r))
        if micro_p is not None and micro_r is not None and (micro_p + micro_r)
        else None
    )
    # accuracy = share of scored (accession, field) cells that are TP
    accuracy = micro_tp / micro_scored if micro_scored else None
    # accuracy_when_gt = match rate among cells with a GT value
    accuracy_when_gt = micro_tp / micro_gt if micro_gt else None
    return {
        "tp": micro_tp,
        "fp": micro_fp,
        "fn": micro_fn,
        "scored": micro_scored,
        "gt_present": micro_gt,
        "precision": micro_p,
        "recall": micro_r,
        "f1": micro_f1,
        "accuracy": accuracy,
        "accuracy_when_gt": accuracy_when_gt,
    }


def _finalize_field_metrics(
    per_field: dict[str, dict[str, int]], accessions_scored: int
) -> dict[str, Any]:
    field_metrics = {}
    for col, s in per_field.items():
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        scored, gt_present = s["scored"], s["gt_present"]
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            (2 * prec * rec / (prec + rec))
            if prec is not None and rec is not None and (prec + rec)
            else None
        )
        field_metrics[col] = {
            **s,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "accuracy": (tp / scored) if scored else None,
            "accuracy_when_gt": (tp / gt_present) if gt_present else None,
            "pred_fill_rate": (s["pred_present"] / accessions_scored) if accessions_scored else 0.0,
        }
    return field_metrics


def score_accession(
    acc: str,
    fields: dict[str, set[str]],
    preds_by_accession: dict[str, dict[str, Any]],
    accession_to_event_id: dict[str, str],
    preds_by_event_id: dict[str, dict[str, Any]],
    per_field: dict[str, dict[str, int]],
    *,
    score_fields: tuple[str, ...] | None = None,
    gt_row_id: str | None = None,
) -> dict[str, Any]:
    """Score one GT row (or legacy accession bag); mutates per_field counters."""
    cols = score_fields or GT_VALUE_FIELDS
    pred = preds_by_accession.get(acc)
    join = "accession"
    if pred is None:
        eid = accession_to_event_id.get(acc)
        if eid and eid in preds_by_event_id:
            pred = preds_by_event_id[eid]
            join = "event_id"
    if pred is None:
        for col in fields:
            if col not in per_field:
                continue
            per_field[col]["fn"] += 1
            per_field[col]["gt_present"] += 1
            per_field[col]["scored"] += 1
        return {
            "gt_row_id": gt_row_id or acc,
            "accession_number": acc,
            "status": "missing_prediction",
            "event_id": accession_to_event_id.get(acc),
            "fields": {},
            "_counts": {"scored": 0, "missing": 1, "via_event": 0},
        }

    via_event = 1 if join == "event_id" else 0
    # Prefer predictions whose Concise Rep inventory includes this accession
    if join == "event_id" and acc in (pred.get("_rep_accessions") or []):
        join = "accession_via_event"
        via_event = 0
    field_detail: dict[str, Any] = {}
    for col in cols:
        hint = GT_TO_HINT[col]
        pval = pred.get(hint)
        gvals = fields.get(col) or set()
        stats = per_field[col]
        if gvals:
            stats["gt_present"] += 1
        if normalize(pval):
            stats["pred_present"] += 1
        if not gvals and not normalize(pval):
            continue
        stats["scored"] += 1
        hit = any(soft_match(pval, g) for g in gvals) if gvals and normalize(pval) else False
        if hit:
            stats["tp"] += 1
            outcome = "tp"
        elif normalize(pval) and not gvals:
            stats["fp"] += 1
            outcome = "fp_no_gt"
        elif normalize(pval) and gvals:
            stats["fp"] += 1
            stats["fn"] += 1
            outcome = "mismatch"
        else:
            stats["fn"] += 1
            outcome = "fn"
        ev = (pred.get("_evidence") or {}).get(hint)
        field_detail[col] = {
            "outcome": outcome,
            "pred": pval,
            "gold": sorted(gvals),
            "hint": hint,
            "evidence": ev,
        }
    return {
        "gt_row_id": gt_row_id or acc,
        "accession_number": acc,
        "status": "scored",
        "join": join,
        "event_id": pred.get("_event_id"),
        "rep_accessions": pred.get("_rep_accessions"),
        "n_facts": pred.get("_n_facts"),
        "fields": field_detail,
        "_counts": {"scored": 1, "missing": 0, "via_event": via_event},
    }


def evaluate_tender(
    gt_rows: list[dict[str, str]],
    preds_by_accession: dict[str, dict[str, Any]],
    *,
    accession_to_event_id: dict[str, str] | None = None,
    preds_by_event_id: dict[str, dict[str, Any]] | None = None,
    out_dir: Path | None = None,
    resume: bool = True,
    show_progress: bool = True,
    score_fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Per-field micro metrics + per-accession detail. Checkpointable when out_dir set."""
    cols = score_fields or GT_VALUE_FIELDS
    cov = field_coverage()
    # Core scoring only requires core fields to be mapped
    if score_fields is not None:
        hints = set(LABEL_TO_FIELD_HINT.values())
        missing = [f for f in cols if f not in GT_TO_HINT or GT_TO_HINT[f] not in hints]
        if missing:
            raise ValueError(f"core fields not mapped: {missing}")
    elif not cov["ok"]:
        raise ValueError(f"pipeline does not cover all GT fields: {cov}")
    accession_to_event_id = accession_to_event_id or {}
    preds_by_event_id = preds_by_event_id or {}
    gold_rows = _gold_rows(gt_rows)
    gold_by_id = {rid: (acc, fields) for rid, acc, fields in gold_rows}

    per_field = {
        f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0, "scored": 0} for f in cols
    }
    details: list[dict[str, Any]] = []
    accessions_scored = 0
    accessions_missing_pred = 0
    accessions_joined_via_event = 0
    done: set[str] = set()

    ckpt_path = live_path = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = out_dir / "checkpoint.jsonl"
        live_path = out_dir / "live_metrics.json"
        if resume and ckpt_path.exists():
            with ckpt_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    detail = json.loads(line)
                    rid = detail.get("gt_row_id") or detail.get("accession_number")
                    if not rid or rid in done or rid not in gold_by_id:
                        continue
                    done.add(rid)
                    acc, fields = gold_by_id[rid]
                    if detail.get("fields"):
                        counts = {
                            "scored": 1,
                            "missing": 0,
                            "via_event": 1 if detail.get("join") == "event_id" else 0,
                        }
                        for col, fd in detail["fields"].items():
                            if col not in per_field:
                                continue
                            stats = per_field[col]
                            outcome = fd.get("outcome")
                            gvals = fields.get(col) or set()
                            if gvals:
                                stats["gt_present"] += 1
                            if normalize(fd.get("pred")):
                                stats["pred_present"] += 1
                            if outcome in {None, ""} and not gvals and not normalize(fd.get("pred")):
                                continue
                            stats["scored"] += 1
                            if outcome == "tp":
                                stats["tp"] += 1
                            elif outcome == "fp_no_gt":
                                stats["fp"] += 1
                            elif outcome == "mismatch":
                                stats["fp"] += 1
                                stats["fn"] += 1
                            elif outcome == "fn":
                                stats["fn"] += 1
                        accessions_scored += counts["scored"]
                        accessions_joined_via_event += counts["via_event"]
                    else:
                        accessions_missing_pred += 1
                        for col in cols:
                            gvals = fields.get(col) or set()
                            if not gvals:
                                continue
                            per_field[col]["fn"] += 1
                            per_field[col]["gt_present"] += 1
                            per_field[col]["scored"] += 1
                    details.append({k: v for k, v in detail.items() if k != "_counts"})

    remaining = [rid for rid, _, _ in gold_rows if rid not in done]
    from src.preprocess.progress import stage_progress

    pbar = stage_progress(
        remaining, desc="eval", total=len(remaining), unit="row", show=show_progress
    )
    ckpt_f = ckpt_path.open("a", encoding="utf-8") if ckpt_path else None
    try:
        for rid in pbar:
            acc, fields = gold_by_id[rid]
            detail = score_accession(
                acc,
                fields,
                preds_by_accession,
                accession_to_event_id,
                preds_by_event_id,
                per_field,
                score_fields=cols,
                gt_row_id=rid,
            )
            counts = detail.pop("_counts")
            accessions_scored += counts["scored"]
            accessions_missing_pred += counts["missing"]
            accessions_joined_via_event += counts["via_event"]
            details.append(detail)
            if ckpt_f is not None:
                ckpt_f.write(json.dumps(detail) + "\n")
                ckpt_f.flush()
            micro = _micro_from_per_field(per_field)
            live = {
                "n_done": len(details),
                "n_total": len(gold_rows),
                "n_gt_rows": len(gold_rows),
                "n_accessions_scored": accessions_scored,
                "n_accessions_missing_prediction": accessions_missing_pred,
                "n_accessions_joined_via_event_id": accessions_joined_via_event,
                "micro": micro,
            }
            if live_path is not None:
                live_path.write_text(json.dumps(live, indent=2), encoding="utf-8")
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(
                    {
                        "P": f"{micro['precision']:.2f}" if micro["precision"] is not None else "—",
                        "R": f"{micro['recall']:.2f}" if micro["recall"] is not None else "—",
                        "F1": f"{micro['f1']:.2f}" if micro["f1"] is not None else "—",
                        "miss": accessions_missing_pred,
                    },
                    refresh=False,
                )
    finally:
        if ckpt_f is not None:
            ckpt_f.close()

    n_unique_acc = len({acc for _, acc, _ in gold_rows})
    return {
        "coverage": cov,
        "n_gt_rows": len(gold_rows),
        "n_gt_accessions": n_unique_acc,
        "n_accessions_scored": accessions_scored,
        "n_accessions_missing_prediction": accessions_missing_pred,
        "n_accessions_joined_via_event_id": accessions_joined_via_event,
        "micro": _micro_from_per_field(per_field),
        "per_field": _finalize_field_metrics(per_field, accessions_scored),
        "details": details,
    }


def write_prediction_csvs(
    result: dict[str, Any],
    gt_rows: list[dict[str, str]],
    out_dir: Path,
) -> tuple[Path, Path, Path]:
    """Write predictions, vs-GT, and per-field evidence CSVs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    details_by_row = {
        d["gt_row_id"]: d
        for d in result.get("details") or []
        if d.get("gt_row_id")
    }
    # Fallback for older checkpoints keyed only by accession
    details_by_acc = {
        d["accession_number"]: d for d in result.get("details") or [] if d.get("accession_number")
    }

    # Wide: one row per GT CSV row with pred_* columns
    pred_path = out_dir / "pipeline_predictions.csv"
    with pred_path.open("w", newline="", encoding="utf-8") as f:
        cols = [
            "gt_row_id",
            "accession_number",
            "event_id",
            "join",
            "status",
            "n_facts",
            *GT_VALUE_FIELDS,
        ]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, row in enumerate(gt_rows):
            acc = (row.get("accession_number") or "").strip()
            if not acc:
                continue
            rid = f"{i}:{acc}"
            detail = details_by_row.get(rid) or details_by_acc.get(acc) or {}
            out_row: dict[str, Any] = {
                "gt_row_id": rid,
                "accession_number": acc,
                "event_id": detail.get("event_id") or "",
                "join": detail.get("join") or "",
                "status": detail.get("status") or "",
                "n_facts": detail.get("n_facts") if detail.get("n_facts") is not None else "",
            }
            fields = detail.get("fields") or {}
            for col in GT_VALUE_FIELDS:
                fd = fields.get(col) or {}
                out_row[col] = fd.get("pred") if fd.get("pred") is not None else ""
            w.writerow(out_row)

    # Long: every (gt_row, field) with GT | pred | match for inspection
    cmp_path = out_dir / "pipeline_vs_gt.csv"
    with cmp_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "gt_row_id",
                "accession_number",
                "event_id",
                "join",
                "field",
                "gt",
                "pred",
                "match",
                "outcome",
            ]
        )
        for i, row in enumerate(gt_rows):
            acc = (row.get("accession_number") or "").strip()
            if not acc:
                continue
            rid = f"{i}:{acc}"
            detail = details_by_row.get(rid) or details_by_acc.get(acc) or {}
            fields = detail.get("fields") or {}
            for col in GT_VALUE_FIELDS:
                gt_val = row.get(col) or ""
                if normalize(gt_val) == "":
                    gt_val = ""
                fd = fields.get(col) or {}
                pred_val = fd.get("pred")
                if pred_val is None:
                    if not gt_val and col not in fields:
                        continue
                    pred_val = ""
                outcome = fd.get("outcome") or (
                    "fn"
                    if gt_val and not normalize(str(pred_val))
                    else ("fp_no_gt" if normalize(str(pred_val)) and not gt_val else "")
                )
                matched = bool(gt_val and pred_val and soft_match(str(pred_val), gt_val))
                if outcome == "tp":
                    matched = True
                w.writerow(
                    [
                        rid,
                        acc,
                        detail.get("event_id") or "",
                        detail.get("join") or "",
                        col,
                        gt_val,
                        pred_val,
                        matched,
                        outcome or ("tp" if matched else ""),
                    ]
                )

    # Per-field extraction evidence (segment + offsets + source doc)
    ev_path = out_dir / "pipeline_field_evidence.csv"
    with ev_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "gt_row_id",
                "accession_number",
                "field",
                "hint",
                "value",
                "source_accession",
                "source_filename",
                "doc_role",
                "segment_id",
                "segment_text",
                "char_start",
                "char_end",
                "segment_char_start",
                "segment_char_end",
                "confidence",
                "rank_score",
                "faq_question",
                "section",
            ]
        )
        seen_rows: set[str] = set()
        for d in result.get("details") or []:
            rid = d.get("gt_row_id") or d.get("accession_number") or ""
            if not rid or rid in seen_rows:
                continue
            seen_rows.add(rid)
            for col, fd in (d.get("fields") or {}).items():
                ev = fd.get("evidence") or {}
                if not ev and not fd.get("pred"):
                    continue
                w.writerow(
                    [
                        rid,
                        d.get("accession_number") or "",
                        col,
                        fd.get("hint") or "",
                        ev.get("value") if ev.get("value") is not None else fd.get("pred") or "",
                        ev.get("source_accession") or "",
                        ev.get("source_filename") or "",
                        ev.get("doc_role") or "",
                        ev.get("segment_id") or "",
                        ev.get("segment_text") or "",
                        ev.get("char_start") if ev.get("char_start") is not None else "",
                        ev.get("char_end") if ev.get("char_end") is not None else "",
                        ev.get("segment_char_start") if ev.get("segment_char_start") is not None else "",
                        ev.get("segment_char_end") if ev.get("segment_char_end") is not None else "",
                        ev.get("confidence") if ev.get("confidence") is not None else "",
                        ev.get("rank_score") if ev.get("rank_score") is not None else "",
                        ev.get("faq_question") or "",
                        ev.get("section") or "",
                    ]
                )
    return pred_path, cmp_path, ev_path


def write_report(
    result: dict[str, Any],
    out_dir: Path,
    *,
    gt_rows: list[dict[str, str]] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {k: v for k, v in result.items() if k != "details"}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.jsonl").write_text(
        "\n".join(json.dumps(d) for d in result["details"]) + ("\n" if result["details"] else ""),
        encoding="utf-8",
    )
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "field",
                "tp",
                "fp",
                "fn",
                "gt_present",
                "pred_present",
                "scored",
                "precision",
                "recall",
                "f1",
                "accuracy",
                "accuracy_when_gt",
                "pred_fill_rate",
            ]
        )
        for col, m in result["per_field"].items():
            w.writerow(
                [
                    col,
                    m["tp"],
                    m["fp"],
                    m["fn"],
                    m["gt_present"],
                    m["pred_present"],
                    m["scored"],
                    m["precision"],
                    m["recall"],
                    m["f1"],
                    m["accuracy"],
                    m["accuracy_when_gt"],
                    m["pred_fill_rate"],
                ]
            )
    if gt_rows is not None:
        write_prediction_csvs(result, gt_rows, out_dir)


def demo() -> None:
    """Minimal self-check: coverage + soft_match + toy score."""
    cov = field_coverage()
    assert cov["ok"], cov
    assert soft_match("$18.75 per share", "18.75 per Share")
    assert soft_match("February 19, 2020", "2/19/2020")
    assert not soft_match("Eli Lilly", "Dermira, Inc.")

    gt = [
        {
            "accession_number": "A1",
            "subject_company": "Dermira, Inc.",
            "bidder": "Eli Lilly and Company",
            "offer_price": "$18.75 per share",
            "expiration_date": "February 19, 2020",
            **{f: "N/A" for f in GT_VALUE_FIELDS if f not in {"subject_company", "bidder", "offer_price", "expiration_date"}},
        }
    ]
    pred_row = {
        "target": "Dermira, Inc.",
        "offeror": "Eli Lilly and Company",
        "offer_price": "$18.75",
        "expiration_date": "February 19, 2020",
        **{h: None for h in set(GT_TO_HINT.values()) - {"target", "offeror", "offer_price", "expiration_date"}},
        "_event_id": "005-1",
        "_n_facts": 4,
    }
    res = evaluate_tender(gt, {"A1": pred_row})
    assert res["micro"]["tp"] >= 4, res["micro"]
    assert res["per_field"]["offer_price"]["tp"] == 1
    # event_id fallback when accession not on Concise Rep
    res2 = evaluate_tender(
        gt,
        {},
        accession_to_event_id={"A1": "005-1"},
        preds_by_event_id={"005-1": pred_row},
    )
    assert res2["n_accessions_joined_via_event_id"] == 1
    assert res2["per_field"]["bidder"]["tp"] == 1
    print("demo ok", res["micro"])


if __name__ == "__main__":
    demo()
