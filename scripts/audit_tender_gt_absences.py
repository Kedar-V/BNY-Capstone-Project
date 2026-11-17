#!/usr/bin/env python3
"""Audit / optionally repair LLM tender GT absence labels.

Absence labels such as ``No minimum tender condition`` are valid only with an
explicit supporting quotation in the ``passage`` column (see TENDER_OFFER_PROMPT).
Do **not** infer absence from silence.

Usage:
  .venv/bin/python scripts/audit_tender_gt_absences.py
  .venv/bin/python scripts/audit_tender_gt_absences.py --fix \\
      --out notebooks/evaluation/tender_offers_absences_fixed.csv

``--fix`` rewrites unsupported absence cells to ``N/A`` (prompt missing value).
Most current rows already have supporting quotes; this mainly catches regressions.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GT = ROOT / "notebooks/evaluation/tender_offers.csv"

# Canonical absence label -> regex that a supporting quote must match.
ABSENCE_SPECS: dict[str, tuple[str, re.Pattern[str]]] = {
    "minimum_tender_condition": (
        "No minimum tender condition",
        re.compile(
            r"(?is)("
            r"not\s+(?:be\s+)?conditioned\s+(?:up)?on\s+.{0,120}?minimum"
            r"|not\s+(?:be\s+)?contingent\s+(?:up)?on\s+.{0,120}?minimum"
            r"|no\s+(?:requirement|condition).{0,80}?minimum"
            r"|absence\s+of.{0,60}?minimum"
            r"|no\s+minimum\s+(?:tender|number|amount|condition)"
            r"|without\s+(?:any\s+)?minimum.{0,60}?(?:tender|share|unit|condition)"
            r"|there\s+is\s+no\s+minimum"
            r"|not\s+subject\s+to\s+(?:any\s+)?minimum"
            r"|minimum\s+(?:number|amount)\s+of\s+(?:shares|units|depositary\s+shares).{0,40}?being\s+tendered"
            r")"
        ),
    ),
    "proration_terms": (
        "No proration",
        re.compile(
            r"(?is)("
            r"\bno\s+proration\b"
            r"|without\s+proration"
            r"|not\s+subject\s+to\s+proration"
            r"|there\s+will\s+be\s+no\s+proration"
            r"|proration\s+will\s+not\s+apply"
            r")"
        ),
    ),
    "available_options": (
        "No holder election",
        re.compile(
            r"(?is)("
            r"no\s+holder\s+election"
            r"|no\s+election\s+(?:of\s+)?(?:form|type)\s+of\s+consideration"
            r"|holders?\s+(?:will|do)\s+not\s+(?:have\s+)?(?:an\s+)?elect"
            r")"
        ),
    ),
}


def _parse_passage(raw: object) -> dict:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    s = str(raw).strip()
    if not s:
        return {}
    try:
        val = ast.literal_eval(s)
    except Exception:
        try:
            val = json.loads(s)
        except Exception:
            return {}
    return val if isinstance(val, dict) else {}


def _field_quotes(passage: dict, field: str) -> list[str]:
    v = passage.get(field)
    out: list[str] = []
    if v is None:
        return out
    if isinstance(v, list):
        for item in v:
            if isinstance(item, dict):
                q = item.get("quote")
                out.append(str(q if q is not None else item))
            else:
                out.append(str(item))
    elif isinstance(v, dict):
        q = v.get("quote")
        out.append(str(q if q is not None else v))
    else:
        out.append(str(v))
    return [q for q in out if q and str(q).strip()]


def audit_row(row: pd.Series) -> list[dict]:
    passage = _parse_passage(row.get("passage"))
    issues: list[dict] = []
    for field, (label, pat) in ABSENCE_SPECS.items():
        val = str(row.get(field) or "").strip()
        if val != label:
            continue
        quotes = _field_quotes(passage, field)
        blob = "\n".join(quotes)
        ok = bool(pat.search(blob))
        if not ok:
            # Secondary: any quote anywhere in passage (mis-keyed field)
            dump = json.dumps(passage, ensure_ascii=False)
            ok = bool(pat.search(dump))
            where = "passage_elsewhere" if ok else "unsupported"
        else:
            where = "field_quote"
        if where == "unsupported":
            issues.append(
                {
                    "accession_number": row.get("accession_number"),
                    "event_id": row.get("event_id"),
                    "field": field,
                    "value": val,
                    "n_field_quotes": len(quotes),
                    "quote0": (quotes[0][:180] if quotes else ""),
                    "support": where,
                }
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gt", type=Path, default=DEFAULT_GT)
    p.add_argument(
        "--fix",
        action="store_true",
        help="Set unsupported absence labels to N/A and write --out",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV when using --fix (default: <gt> with _absences_fixed suffix)",
    )
    args = p.parse_args(argv)

    # Keep literal "N/A" (pandas would otherwise coerce it to NaN).
    df = pd.read_csv(args.gt, keep_default_na=False)
    all_issues: list[dict] = []
    for _, row in df.iterrows():
        all_issues.extend(audit_row(row))

    # Summary counts
    print(f"gt={args.gt} rows={len(df)}")
    for field, (label, _) in ABSENCE_SPECS.items():
        n_label = int((df[field].fillna("").astype(str).str.strip() == label).sum())
        n_bad = sum(1 for i in all_issues if i["field"] == field)
        print(f"  {field}: label={label!r} n={n_label} unsupported={n_bad}")

    if all_issues:
        print(f"\nunsupported examples ({min(10, len(all_issues))} of {len(all_issues)}):")
        for issue in all_issues[:10]:
            print(
                f"  {issue['accession_number']} {issue['field']}: "
                f"quotes={issue['n_field_quotes']} quote0={issue['quote0']!r}"
            )
    else:
        print("\nAll absence labels have a supporting quotation match.")

    if args.fix:
        if not all_issues:
            print("nothing to fix")
            return 0
        out = args.out
        if out is None:
            out = args.gt.with_name(args.gt.stem + "_absences_fixed.csv")
        bad_keys = {(i["event_id"], i["field"]) for i in all_issues}
        n_fixed = 0
        for idx, row in df.iterrows():
            for field, (label, _) in ABSENCE_SPECS.items():
                if (row.get("event_id"), field) in bad_keys and str(row.get(field) or "").strip() == label:
                    df.at[idx, field] = "N/A"
                    n_fixed += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"wrote {out} fixed_cells={n_fixed}")
        print(
            "Note: most 'No minimum…' labels are valid; unsupported ones lacked a "
            "matching passage quote. Re-run extract GT with the hardened prompt for new rows."
        )
    return 0 if not all_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
