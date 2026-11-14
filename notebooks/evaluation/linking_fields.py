"""Columns that event linking needs, filled by code from SEC search metadata and the filing text (no LLM).

Each extraction notebook calls add_linking_fields() when it builds its results table, while the filing text is
still in memory. In production the documents are not kept, so these values have to be captured at that point.
"""
import ast
import hashlib
import json
import re
from datetime import datetime

import pandas as pd

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
FILE_NUMBER = re.compile(r"(?<![\d-])((?:333|001|000|005|811|814)-\d{5,6})(?!\d)")
AMENDMENT_NUMBER = re.compile(r"Amendment\s+No\.?\s*(\d{1,3})\b", re.IGNORECASE)
DATE = r"((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, ?\d{4})"
AMENDS_DATE = [
    re.compile(r"originally filed with the (?:U\.S\. )?(?:Securities and Exchange Commission|SEC|Commission)[^.]{0,40}? on " + DATE),
    re.compile(r"(?:Schedule TO|Tender Offer Statement|Schedule 13E-3|Registration Statement)[^.]{0,200}? filed[^.]{0,200}? on " + DATE),
]
# Filled by the model once the prompt includes them; their checks run only when the column is present.
PROMPT_LINKING_COLUMNS = [
    "agreement_name", "agreement_date", "offer_commencement_date", "original_filing_date",
    "related_entities", "security_identifiers",
]
CHECK_COLUMNS = ["security_identifiers_unverified", "original_filing_date_agrees"]
# Covers often print a CUSIP with a space, e.g. "48255N 100", and the model copies it as printed.
CUSIP_TOKEN = re.compile(r"\b([0-9A-Z]{6})[\s-]?([0-9A-Z]{2})[\s-]?([0-9])\b")
ISIN_TOKEN = re.compile(r"\b[A-Z]{2}[0-9A-Z]{9}[0-9]\b")
LINKING_COLUMNS = [
    "filer_ciks", "filer_names", "file_numbers", "is_amendment", "amendment_number", "amends_filing_date",
    "referenced_file_numbers", "evidence_verified", "evidence_unverified_fields",
]


def prompt_version(prompt):
    """A short fingerprint of the prompt text, so each row shows which prompt produced it."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def now_utc():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _literal(value):
    if not isinstance(value, str) or not value.strip():
        return value if isinstance(value, (list, dict)) else None
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(value)
        except (ValueError, SyntaxError):
            continue
    return None


def as_json(value):
    """Evidence and lists as valid JSON text, whether they arrived as JSON or as a Python literal."""
    parsed = _literal(value)
    return json.dumps(parsed, ensure_ascii=False) if parsed not in (None, "") else None


def load_search_metadata(path):
    """Every filer's CIK, name and file number, and the amendment flag, from the loader's selected_filings.csv.

    The extraction tables keep only one registrant per filing; the SEC search returns all of them.
    """
    hits = pd.read_csv(path, dtype=str)
    out = {}
    for accession, group in hits.groupby("accession"):
        ciks, names, numbers = [], [], []
        for _, row in group.iterrows():
            for cik in _literal(row.get("ciks")) or []:
                cik = str(int(cik)) if str(cik).strip().isdigit() else str(cik)
                if cik not in ciks:
                    ciks.append(cik)
            for name in _literal(row.get("display_names")) or []:
                name = name.split("  (")[0].strip()  # "NAME  (TICKERS)  (CIK 0001234567)"
                if name and name not in names:
                    names.append(name)
            for number in _literal(row.get("file_nums")) or []:
                if number and number not in numbers:
                    numbers.append(number)
        flag = str(group["is_amendment"].iloc[0]).strip().lower() if "is_amendment" in group else ""
        out[str(accession)] = {
            "filer_ciks": ciks,
            "filer_names": names,
            "file_numbers": numbers,
            "is_amendment": flag == "true" if flag in ("true", "false") else None,
        }
    return out


def _iso(text_date):
    month, rest = text_date.split(" ", 1)
    day, year = rest.replace(" ", "").split(",")
    return f"{year}-{MONTHS.index(month.lower()) + 1:02d}-{int(day):02d}"


def amendment_number(text):
    match = AMENDMENT_NUMBER.search(text[:20000])
    return int(match.group(1)) if match else None


def amends_filing_date(text):
    """The date of the filing an amendment amends, when the text states it ("originally filed … on December 1, 2025")."""
    head = re.sub(r"\s+", " ", text[:60000])
    head = re.sub(r"\bU\.\s?S\.", "US", head)  # "the U.S. Securities and Exchange Commission"
    for pattern in AMENDS_DATE:
        match = pattern.search(head)
        if match:
            return _iso(match.group(1))
    return None


def referenced_file_numbers(text, own_numbers):
    """SEC file numbers mentioned in the text, other than the filing's own."""
    found = []
    for number in FILE_NUMBER.findall(text[:300000]):
        if number not in own_numbers and number not in found:
            found.append(number)
    return found


def _norm(text):
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def unverified_fields(evidence, text):
    """Fields whose supporting quote cannot be found in the filing text (checked while the text is in memory)."""
    parsed = _literal(evidence)
    if not isinstance(parsed, dict):
        return None
    body = _norm(text)
    missing = []
    for field, items in parsed.items():
        for item in items or []:
            quote = _norm(str((item or {}).get("quote") or ""))
            if not quote:
                continue
            pieces = [p.strip(" .\"'") for p in re.split(r"\.\.\.|…", quote) if len(p.strip(" .\"'")) > 12]
            if pieces and not all(piece in body for piece in pieces):
                missing.append(field)
                break
    return missing


def identifiers_unverified(identifiers, text):
    """CUSIPs and ISINs in security_identifiers that do not appear in the filing text.

    Spaces and hyphens are ignored, because covers often print a CUSIP as "85817G 108".
    """
    if not isinstance(identifiers, str) or identifiers.strip().upper() in ("", "N/A", "NAN"):
        return None
    compact = re.sub(r"[\s-]", "", text.upper())
    upper = identifiers.upper()
    tokens = [t for t in ISIN_TOKEN.findall(upper)]
    cusips = ["".join(parts) for parts in CUSIP_TOKEN.findall(upper)]
    tokens += [t for t in cusips if any(c.isdigit() for c in t[:6]) and not any(t in i for i in tokens)]
    return [t for t in tokens if t not in compact]


def original_date_agrees(model_value, rule_iso):
    """Whether the model's original_filing_date (M/D/YYYY) matches the date the rule found; None if either is missing."""
    if not isinstance(model_value, str) or not rule_iso or not isinstance(rule_iso, str):
        return None
    match = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", model_value)
    if not match:
        return None
    month, day, year = (int(x) for x in match.groups())
    return f"{year}-{month:02d}-{day:02d}" == rule_iso


def add_linking_fields(frame, search_metadata, text_by_accession, evidence_column):
    """Add the linking columns to an extraction results table. Existing columns are left as they are."""
    if frame.empty:
        return frame
    frame = frame.copy()
    if evidence_column in frame:
        frame[evidence_column] = frame[evidence_column].map(as_json)
    rows = {}
    for accession, form in zip(frame["accession_number"].astype(str), frame.get("form", pd.Series([""] * len(frame)))):
        if accession in rows:
            continue
        meta = search_metadata.get(accession, {})
        text = text_by_accession.get(accession) or ""
        amendment = meta.get("is_amendment")
        if amendment is None:
            amendment = str(form).strip().endswith("/A")
        numbers = meta.get("file_numbers", [])
        rows[accession] = {
            "filer_ciks": json.dumps(meta.get("filer_ciks", [])),
            "filer_names": json.dumps(meta.get("filer_names", []), ensure_ascii=False),
            "file_numbers": json.dumps(numbers),
            "is_amendment": bool(amendment),
            "amendment_number": amendment_number(text) if amendment and text else None,
            "amends_filing_date": amends_filing_date(text) if amendment and text else None,
            "referenced_file_numbers": json.dumps(referenced_file_numbers(text, set(numbers))) if text else None,
        }
    for column in LINKING_COLUMNS[:7]:
        frame[column] = frame["accession_number"].astype(str).map(lambda a, c=column: rows[a][c])
    if "filing_date" in frame:
        # An original cannot be filed after its amendment; such a date is a typo in the filing, so it is not used.
        impossible = frame["amends_filing_date"].notna() & (frame["amends_filing_date"].astype(str) > frame["filing_date"].astype(str))
        frame.loc[impossible, "amends_filing_date"] = None
    if evidence_column in frame:
        checks = [
            unverified_fields(evidence, text_by_accession.get(str(accession)) or "")
            if text_by_accession.get(str(accession)) else None
            for evidence, accession in zip(frame[evidence_column], frame["accession_number"])
        ]
        frame["evidence_verified"] = [None if c is None else not c for c in checks]
        frame["evidence_unverified_fields"] = [None if c is None else json.dumps(c) for c in checks]
    if "security_identifiers" in frame:
        found = [
            identifiers_unverified(value, text_by_accession.get(str(accession)) or "")
            if text_by_accession.get(str(accession)) else None
            for value, accession in zip(frame["security_identifiers"], frame["accession_number"])
        ]
        frame["security_identifiers_unverified"] = [None if f is None else json.dumps(f) for f in found]
    if "original_filing_date" in frame:
        frame["original_filing_date_agrees"] = [
            original_date_agrees(model, rule) for model, rule in zip(frame["original_filing_date"], frame["amends_filing_date"])
        ]
    frame["amendment_number"] = frame["amendment_number"].astype("Int64")
    return frame
