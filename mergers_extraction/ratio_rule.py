"""Exchange ratio: the fine-tuned GLiNER for fixed ratios, with two checks around it.

1. No stock in the deal -> no ratio. If the filing never says holders receive shares (no "Exchange Ratio", no "right
   to receive ... shares of"), the deal pays only cash or other property, so any number GLiNER returns is wrong.
2. Formula ratio -> the formula as the filing defines it, after GLiNER's fixed ratio when the filing also states one
   for some holders (SPAC holders 1-for-1, the operating company by formula). When "Exchange Ratio" is defined as a quotient, an average
   price or another calculation, there is no single number to copy, so the answer is
   "Formula: the quotient of $800,000,000 divided by ...", taken from the definition.
3. Otherwise the fine-tuned GLiNER's ratio (learned windows), e.g. "0.400 shares of Cliffs common stock per share".

Checks 1 and 2 were written and tuned on training filings only (classify() against the ground truth's consideration
type and ratio type; see main()). GLiNER's predictions come from gliner_finetuned_eval.py for the split.
"""
from __future__ import annotations

import re

import common

RATIO_TERM = r"(?:Exchange|Conversion|Share\s+Exchange)\s+Ratio"
# holders receive shares: a defined Exchange Ratio (capitalised, so not "did not specify any exchange ratio"), or
# "right to receive / converted into <a number> ... shares of" (a number of shares, not "for each share of ... you own")
STOCK = re.compile(r"(?<!Option )(?<!Award )(?<!Equity )\b(?:Exchange|Conversion|Share Exchange) Ratio\b|"
                   r"(?i:(?:right\s+to\s+receive|converted\s+(?:automatically\s+)?into|exchanged\s+for|in\s+exchange\s+for)"
                   r"\s+(?:\(\w+\)\s+)?(?:\d*\.\d+|\d+|one|a\s+number\s+of|that\s+number\s+of|the\s+number\s+of)\s+"
                   r"(?:\(\d+\)\s+)?[^.;$]{0,90}?\b(?:shares?|ordinary\s+shares?|ADSs?)\s+of\b(?!\s+(?:the\s+)?"
                   r"(?:common\s+stock\s+of\s+)?(?:the\s+)?surviving))")
# more ways filings say holders get shares (training-filing misses): the stock leg of a mixed deal, defined share
# names ("into one Purchaser Class A Ordinary Share"), and "receive / consist of / in the form of shares of Pubco"
STOCK_MORE = [
    re.compile(r"\(ii\)\s+(?:\d*\.\d+|\d+|one)\s+(?:\(\d+\)\s+)?(?:validly\s+issued[^.;]{0,50}?)?shares?\b", re.I),
    re.compile(r"(?i:\b(?:into|for|receive|receiving))\s+(?:the\s+right\s+to\s+receive\s+)?(?i:one|\d[\d,]*(?:\.\d+)?)\s+"
               r"(?:\(\d+\)\s+)?(?:[A-Z][\w’'-]*\s+){1,4}(?:Ordinary\s+|Common\s+)?Shares?\b(?!\s+of\s+(?:the\s+)?Surviving)"),
    re.compile(r"(?i:\b(?:receive|consist\s+of|in\s+the\s+form\s+of|paid\s+in|portion\s+of\s+[\d,]+))\s+"
               r"(?i:(?:a|the|that)\s+number\s+of\s+)?(?i:(?:ordinary\s+)?shares\s+of)\s+(?:the\s+)?[A-Z]"
               r"(?!\w*\s+(?:Surviving|Merger\s+Sub))"),
    re.compile(r"Shares?\s+on\s+a\s+(?:one|\d+)[- ]for[- ](?:one|\d+)\s+basis", re.I),
]
# a fixed number of shares stated for some holders: "converted into one Purchaser Class A Ordinary Share"
FIXED_CLAUSE = re.compile(r"(?i:\b(?:into|for|receive))\s+(?:the\s+right\s+to\s+receive\s+)?(?P<n>(?i:one|\d*\.\d+|\d+))\s+"
                          r"(?:\(\d+\)\s+)?(?:validly\s+issued[^.;]{0,50}?\s+)?(?:[A-Z][\w’'-]*\s+){0,4}(?i:ordinary\s+|common\s+)?"
                          r"(?i:shares?)\b|(?P<basis>(?i:one))[- ]for[- ]one\s+basis")
RATIO_NAME = (r"(?:[\w-]+\s+){0,3}(?:Exchange|Conversion)\s+Ratio|(?:[\w-]+\s+){0,4}Per\s+(?:[\w-]+\s+){0,3}Share\s+"
              r"(?:[\w-]+\s+){0,2}Consideration")
DEFINITION = re.compile(rf"(?:[“\"]\s*(?:{RATIO_NAME})\s*[”\"]|\bThe\s+(?:{RATIO_NAME})\b)\s*(?:shall\s+)?(?:means?|is|equals?|"
                        r"shall\s+(?:be|equal)|refers\s+to|will\s+(?:be|equal))\s*(?P<body>[^;]{10,420})")
FORMULA_WORDS = re.compile(r"quotient|divided\s+by|dividing|\baverage\b|vwap|volume[- ]weighted|\bformula\b|"
                           r"obtained\s+by|determined\s+by|calculated|\bproduct\s+of|\bsum\s+of|multiplied|"
                           r"ownership\s+percentage|equity\s+value|pro\s+rata|allocation", re.I)
FIXED_START = re.compile(r"^\W*\d*\.\d+|^\W*(?:one|two|three)\b", re.I)
# no defined ratio, but holders get "a number of shares equal to the quotient / product of ..." or a pro-rata
# portion of a share pool ("in the aggregate", "Pro Rata Share of")
NUMBER_EQUAL = re.compile(r"(?:right\s+to\s+receive|converted\s+into|entitled\s+to\s+receive)\s*,?\s*"
                          r"(?P<body>(?:(?:a\s+)?number\s+of\b[^.;]{0,120}?\bequal\s+to\s+(?:the\s+)?"
                          r"(?:quotient|product|sum|.{0,60}divided\s+by)|in\s+the\s+aggregate\s*,|(?:its|such\s+\w+(?:’s|'s)|"
                          r"the\s+applicable|a)\s+(?:pro\s+rata\s+(?:share|portion)|portion)\s+of)[^;]{0,300})", re.I)
# a pro-rata portion of cash, not of a share pool: SPAC redemptions, fees, "the Merger Consideration"
POOL_NOT_SHARES = re.compile(r"redemption|termination|\bfees?\b|\bcash\b|merger\s+consideration|escrow|earnout|"
                             r"proceeds|amount", re.I)
# equity awards are converted by formulas in every stock deal; they are not the holders' ratio
AWARDS = re.compile(r"\bRSUs?\b|\bPSUs?\b|option|award|warrant|restricted|deferred|incentive\s+units?|subject\s+to\s+such", re.I)


def classify(text: str) -> tuple[str, str]:
    """('none' | 'formula' | 'fixed', evidence) for the filing's stock consideration."""
    flat = re.sub(r"\s+", " ", text)
    if not STOCK.search(flat) and not any(p.search(flat) for p in STOCK_MORE):
        return "none", "no stock wording: no exchange ratio and no 'right to receive ... shares of'"
    fixed_seen = None
    for m in DEFINITION.finditer(flat):
        body = m.group("body").strip()
        term = m.group(0)[:m.group(0).find(body[:20])] if body else m.group(0)
        if AWARDS.search(term) or re.search(r"\bcash\b", body[:150], re.I):  # award ratios; "if ... exclusively of cash"
            continue
        if FIXED_START.search(body):
            fixed_seen = fixed_seen or m.group(0)
            continue
        if FORMULA_WORDS.search(body[:300]):
            return "formula", m.group(0)
    if fixed_seen:
        return "fixed", fixed_seen
    for m in NUMBER_EQUAL.finditer(flat):
        if not AWARDS.search(flat[max(0, m.start() - 300):m.end()]) and \
                not POOL_NOT_SHARES.search(m.group("body")[:120]):
            return "formula", m.group(0)
    return "fixed", ""


def formula_value(evidence: str) -> str:
    """'Formula: ' and the definition, cut to about 200 characters at a word boundary."""
    body = re.sub(rf"^(?:[“\"]\s*(?:{RATIO_NAME})\s*[”\"]|The\s+(?:{RATIO_NAME}))\s*(?:shall\s+)?(?:means?|is|equals?|shall\s+(?:be|equal)|refers\s+to|"
                  r"will\s+(?:be|equal))\s*", "", evidence, flags=re.I)
    body = body[:200].rsplit(" ", 1)[0] if len(body) > 200 else body
    return "Formula: " + body.strip(" ,")


def predict_all(accs: list[str], model: str, split: str) -> dict:
    from pipeline import gliner_predictions
    gliner = gliner_predictions(model, split)
    out = {}
    for acc in accs:
        kind, evidence = classify(common.filing_text(acc))
        if kind == "none":
            out[acc] = {"stock_exchange_ratio": ("", evidence)}
        elif kind == "formula":
            # two-ratio deals (SPAC holders 1-for-1, operating company by formula): keep GLiNER's fixed ratio when the
            # filing states that number of shares for some holders, and add the formula
            value = gliner.get(acc, {}).get("stock_exchange_ratio", "")
            got = common.numbers(value, words=True)
            stated = {common.numbers(m.group("n") or m.group("basis"), words=True)[0]
                      for m in FIXED_CLAUSE.finditer(re.sub(r"\s+", " ", common.filing_text(acc)))}
            keep = value if got and got[0] in stated else ""
            out[acc] = {"stock_exchange_ratio": ((keep + " | " if keep else "") + formula_value(evidence),
                                                 evidence[:400])}
        else:
            value = gliner.get(acc, {}).get("stock_exchange_ratio", "")
            out[acc] = {"stock_exchange_ratio": (value, "fine-tuned GLiNER" + (f"; definition: {evidence[:300]}"
                                                                             if evidence else ""))}
    return out


def main() -> None:
    """Development check on training filings: does classify() agree with the ground truth's types?"""
    import pandas as pd
    gt = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv")
    splits = pd.read_csv(common.SPLITS_PATH, dtype=str)
    train = set(splits.loc[splits["split"] == "train", "accession_number"]) - set(common.validation_accessions())
    gt = gt[gt["accession_number"].isin(train)].fillna("")
    rows = []
    for acc, g in gt.groupby("accession_number"):
        kind, _ = classify(common.filing_text(acc))
        types = set(g["stock_exchange_ratio_type"]) - {""}
        cons = set(g["consideration_type"])
        truth = ("formula" if "Formula" in types else "fixed" if types & {"Fixed", "Range"} else
                 "none" if cons and cons <= {"Cash", "Other", ""} else "unclear")
        rows.append({"accession_number": acc, "rule": kind, "ground_truth": truth})
    df = pd.DataFrame(rows)
    print(pd.crosstab(df["ground_truth"], df["rule"], margins=True))


if __name__ == "__main__":
    main()
