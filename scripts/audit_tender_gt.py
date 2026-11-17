"""Audit notebooks/evaluation/tender_offers.csv and list every problematic (row, field).

Output: outputs/tender_eval/tender_gt_problem_examples.csv
One line per (row_idx, field); `issues` lists every issue found for that field and
`explanation` describes what is wrong in that specific row.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "notebooks/evaluation/tender_offers.csv"
OUT = ROOT / "outputs/tender_eval/tender_gt_problem_examples.csv"

ABSENT = {"", "n/a", "none", "-"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b\d{{1,2}}/\d{{1,2}}/\d{{4}}\b|\b(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}}\b")
PASSAGE_KEY = {"currency": "offer_price_currency"}
QUOTE_CAP = 1500

PROMPT = {
    "settlement_date": (
        'GT prompt says settlement_date = "stated timing for acceptance for payment and payment"; '
        'if they differ "preserve both with labels, separated by \' | \'". Schema doc/eval treat it as a date.'
    ),
    "withdrawal_deadline": (
        'Prompt asks for "the last date and time holders may withdraw"; model also appended '
        "conditional withdrawal-right text that was not requested."
    ),
    "effective_date": (
        'Prompt: "when a transaction legally takes effect... only when the text states it" - '
        "no date-only requirement, so merger-effectiveness wording is copied as prose."
    ),
    "offer_price_bare": (
        'Prompt: "For a fixed price, return the numeric amount only, for example \'25.00\'". '
        'Schema doc says prefer "$18.75" / "$18.75 per share".'
    ),
    "offer_price_long": (
        'Prompt: formula -> "return the stated formula"; noncash/mixed -> "describe the consideration '
        'and any exchange ratio". No length cap.'
    ),
    "currency": (
        "Prompt key is offer_price_currency; eval column is currency. Blank here although a price exists "
        "(mapping/fill not traced)."
    ),
    "proration_terms": (
        "Prompt lists trigger, allocation method, purchase limit, odd-lot priority, conditional tenders "
        "and rounding with no length cap. Schema doc wants a short clause."
    ),
    "minimum_tender_condition": (
        "Prompt asks for calculation basis, bidder/affiliate share treatment and waivability, no length cap."
    ),
    "sentinel": (
        'Prompt: use "No minimum tender condition" / "No proration" only when explicitly stated. '
        "Eval absent-list is blank/N/A/none/-, so these count as real values."
    ),
    "bidder": 'Prompt: "Separate multiple names with \' | \'". Schema doc says multi-value uses "; ".',
    "dup": "Prompt returns one object per distinct offer/class; two objects emitted for the same security.",
}


_MONTHS = MONTHS.lower().split("|")


def date_set(text: str) -> set[tuple[int, int, int]]:
    """(year, month, day) tuples for M/D/YYYY and 'Month D, YYYY' dates in text."""
    out: set[tuple[int, int, int]] = set()
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        out.add((int(m[3]), int(m[1]), int(m[2])))
    for m in re.finditer(rf"\b({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text, re.I):
        out.add((int(m[3]), _MONTHS.index(m[1].lower()) + 1, int(m[2])))
    return out


def absent(v: str) -> bool:
    return v.strip().lower() in ABSENT


def dates_in(s: str) -> list[str]:
    return [m.group(0) for m in DATE.finditer(s)]


def main() -> None:
    d = pd.read_csv(SRC, dtype=str, keep_default_na=False)
    passages = [ast.literal_eval(p) if p else {} for p in d["passage"]]

    # (row_idx, field) -> {"issues": [...], "expl": [...], "cause": [...], "fix": [...]}
    found: dict[tuple[int, str], dict[str, list[str]]] = {}

    def flag(i: int, field: str, issue: str, expl: str, cause: str, fix: str) -> None:
        e = found.setdefault((i, field), {"issues": [], "expl": [], "cause": [], "fix": []})
        e["issues"].append(issue)
        e["expl"].append(expl)
        if cause not in e["cause"]:
            e["cause"].append(cause)
        if fix not in e["fix"]:
            e["fix"].append(fix)

    for i, r in d.iterrows():
        # ---- settlement_date
        v = r["settlement_date"]
        if not absent(v):
            ds = dates_in(v)
            parts = [p.strip() for p in v.split("|")]
            if not ds:
                flag(i, "settlement_date", "no_calendar_date",
                     f"Gold is a {len(v)}-char timing phrase with no calendar date ({v[:90]!r}...). "
                     "A date span can never match it, so this row is an unrecoverable false negative for a date extractor.",
                     PROMPT["settlement_date"], "Score as text, or split into acceptance/payment fields")
            if len(parts) > 1:
                flag(i, "settlement_date", "multi_part_blob",
                     f"Gold packs {len(parts)} labeled parts into one cell ({'; '.join(p[:40] for p in parts)}). "
                     f"Calendar dates present: {len(ds)}.",
                     PROMPT["settlement_date"], "Split on ' | ' into separate fields; score each")
            elif ds and len(v) > 60:
                flag(i, "settlement_date", "date_plus_text",
                     f"Gold has a date ({ds[0]}) embedded in {len(v)} chars of text.",
                     PROMPT["settlement_date"], "Keep the date; move the qualifier to a text field")

        # ---- withdrawal_deadline
        v = r["withdrawal_deadline"]
        if not absent(v):
            ds = dates_in(v)
            if not ds:
                flag(i, "withdrawal_deadline", "no_calendar_date",
                     f"Gold has no date ({v[:90]!r}).", PROMPT["withdrawal_deadline"], "Score as text")
            elif len(v) > 60:
                lead = v.split("|")[0].strip()
                flag(i, "withdrawal_deadline", "date_plus_conditional_rule",
                     f"Gold is {len(v)} chars: leading deadline {lead[:50]!r} followed by an extra conditional-withdrawal clause. "
                     "Expected a single date/time.",
                     PROMPT["withdrawal_deadline"], "Keep the date only; move the conditional right to a narrative field")

        # Not flagged (eval-side, see docs): bidder "|" lists (soft_match handles them), effective_date prose,
        # long minimum_tender_condition / proration_terms / NAV offer_price text (narrative -> text scoring),
        # bare-number offer_price, blank currency (backfilled in load_gt), repeated accessions (distinct offers).

        # ---- gold date disagrees with its own passage quote
        for f in ("expiration_date", "withdrawal_deadline", "settlement_date", "effective_date"):
            g = date_set(r[f])
            if not g:
                continue
            q = date_set(" ".join(x["quote"] for x in passages[i].get(f, [])))
            if q and not g <= q:
                flag(i, f, "gold_date_not_in_quote",
                     f"Gold date(s) {sorted(g)} are not among the dates in the field's own passage quote {sorted(q)}: "
                     "either the label is wrong or the quote is the wrong sentence.",
                     "Prompt requires a supporting quote per field; model returned a quote that does not support the value.",
                     "Re-check the filing and fix the gold or the quote")

    rows = []
    for (i, field), e in sorted(found.items()):
        r = d.loc[i]
        pkey = PASSAGE_KEY.get(field, field)
        ps = passages[i].get(pkey, [])
        quotes = [p["quote"] for p in ps]
        gold = str(r[field])
        norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[“”\"']", " ", s)).strip().lower()
        qn = norm(" ".join(quotes))
        if not quotes:
            in_p = "no_passage"
        elif norm(gold) and norm(gold) in qn:
            in_p = "yes"
        else:
            sub = [norm(x) for x in re.split(r"\s*\|\s*", gold) if x.strip()]
            sub = [re.sub(r"^[a-z ]+:\s*", "", x) for x in sub]
            in_p = "partial" if any(x and x in qn for x in sub) else "no"
        rows.append({
            "row_idx": i,
            "accession_number": r["accession_number"],
            "form": r["form"],
            "subject_company": r["subject_company"],
            "security_description": r["security_description"][:80],
            "field": field,
            "issues": "; ".join(e["issues"]),
            "gold_value": gold[:400],
            "explanation": " ".join(e["expl"]),
            "gt_passage_quotes": " ||| ".join(quotes)[:QUOTE_CAP],
            "gt_passage_location": " ||| ".join(str(p.get("location")) for p in ps),
            "gt_passage_count": len(quotes),
            "gold_value_in_passage": in_p,
            "quote_has_calendar_date": bool(dates_in(" ".join(quotes))) if field.endswith("_date") else "",
            "root_cause_in_gt_prompt": " | ".join(e["cause"]),
            "suggested_fix": " | ".join(e["fix"]),
        })
    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"{len(out)} (row, field) lines across {out.row_idx.nunique()} of {len(d)} GT rows")
    print(out.groupby("field").size().to_string())
    flat = out.assign(i=out.issues.str.split("; ")).explode("i")
    print(flat.groupby(["field", "i"]).size().to_string())


if __name__ == "__main__":
    main()
