"""Shared pieces for the merger extraction experiments: paths, fields, value matching, deal split and scoring."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from src.merger_gliner import select_windows  # noqa: E402  keyword-anchored windows of the existing pipeline

DATA = ROOT / "notebooks/evaluation/data/merger_2026-01-01_2026-09-30"
GT_PATH = DATA / "mergers.csv"
TEXT_DIR = DATA / "input_text"
SELECTED_FILINGS = DATA / "selected_filings.csv"
OUTPUTS = HERE / "outputs"
TRAINING_DATA = OUTPUTS / "training_data"
SPLITS_PATH = TRAINING_DATA / "splits.csv"
MODELS = ROOT / "models/merger_gliner"  # gitignored (/models/)
BASE_MODEL = "urchade/gliner_medium-v2.1"

# Fields with a value that appears as a span in the filing: these are fine-tuned.
# field -> (GLiNER label, how the value is compared)
SPAN_FIELDS = {
    "acquirer": ("acquirer organization", "name"),
    "target": ("target organization", "name"),
    "merger_subsidiary": ("merger subsidiary", "name"),
    "security_description": ("affected security", "text"),
    "cash_consideration": ("cash consideration per share", "money"),
    "stock_exchange_ratio": ("stock exchange ratio", "number"),
    "shareholder_vote_date": ("shareholder vote date", "date"),
    "effective_date": ("merger effective date", "date"),
    "election_deadline": ("election deadline", "date"),
    "expected_closing": ("expected closing timing", "text"),
}

# Summary and status fields: zero-shot only, to see how far a span model gets. Not fine-tuned.
SUMMARY_FIELDS = {
    "event_status": ("merger event status", "category"),
    "event_status_details": ("merger milestone", "text"),
    "closing_conditions": ("merger closing condition", "text"),
    "available_options": ("shareholder election option", "text"),
    "default_option": ("default election option", "text"),
    "cash_consideration_qualifications": ("cash consideration adjustment", "text"),
    "stock_exchange_ratio_qualifications": ("exchange ratio adjustment", "text"),
    "other_consideration": ("contingent value right", "text"),
}
# Not run through GLiNER at all: ticker, cusip, isin (regex), consideration_type, stock_exchange_ratio_type and
# mandatory_voluntary_indicator (rules on other fields), and EDGAR metadata. See README.md.

MISSING = {"", "n/a", "na", "none", "null", "-", "—"}
NAME_SUFFIXES = r"\b(inc|incorporated|corp|corporation|co|company|llc|l\.l\.c|ltd|limited|plc|lp|l\.p|n\.v|s\.a|ag|se|sa|nv)\b\.?"
GENERIC_ROLES = {"parent", "merger sub", "merger sub i", "merger sub ii", "first merger sub", "second merger sub",
                 "company", "the company", "purchaser", "buyer", "acquiror", "acquirer", "target", "holdco",
                 "pubco", "spac", "surviving corporation", "surviving company", "newco"}
STOP = {"the", "of", "a", "an", "and", "or", "to", "in", "for", "on", "by", "with", "per", "each", "any", "its"}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(" + "|".join(m[:3] for m in MONTHS) +
                     r")[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
TOKEN_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")  # GLiNER's own word splitter


# ---------------------------------------------------------------- values
def blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip().lower() in MISSING


def absence(value: str) -> bool:
    """Stated absences such as "No holder election": a span model cannot output these."""
    return bool(re.match(r"\s*no\b", value, re.I))


def norm_name(value: str) -> str:
    value = re.sub(r"[“”\"'’(),.]", " ", value.lower())
    value = re.sub(NAME_SUFFIXES, " ", value)
    return re.sub(r"\s+", " ", value).strip()


WORD_NUMBERS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "six": 6.0, "seven": 7.0,
                "eight": 8.0, "nine": 9.0, "ten": 10.0}


def numbers(value: str, words: bool = False) -> list[float]:
    """Numbers in the text, in order. words=True also reads number words ("one (1) share" -> 1)."""
    pattern = r"\d[\d,]*(?:\.\d+)?" + (r"|\b(?:" + "|".join(WORD_NUMBERS) + r")\b" if words else "")
    return [WORD_NUMBERS[n.lower()] if n.lower() in WORD_NUMBERS else float(n.replace(",", ""))
            for n in re.findall(pattern, value, flags=re.I)]


def parse_dates(text: str) -> list[tuple[date, int, int]]:
    """Every calendar date in the text with its character offsets."""
    out = []
    for m in DATE_RE.finditer(text or ""):
        try:
            if m[1]:
                d = date(int(m[3]), int(m[1]), int(m[2]))
            else:
                d = date(int(m[6]), [x[:3] for x in MONTHS].index(m[4].lower()[:3]) + 1, int(m[5]))
        except ValueError:
            continue
        out.append((d, m.start(), m.end()))
    return out


def tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$.%]+", value.lower()) if t not in STOP}


def token_f1(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    common = len(x & y)
    return 0.0 if not common else 2 * common / (len(x) + len(y))


def match(kind: str, pred: str, gold: str) -> bool:
    """Is the predicted span the ground-truth value, allowing for formatting differences?"""
    if kind == "name":
        p, g = norm_name(pred), norm_name(gold)
        if p in GENERIC_ROLES:  # "Parent" or "Merger Sub" does not identify the legal entity
            return False
        return bool(p and g) and (p == g or (len(p) >= 4 and f" {p} " in f" {g} ") or (len(g) >= 4 and f" {g} " in f" {p} "))
    if kind == "money":
        g, p = numbers(gold), numbers(pred)
        return bool(g and p) and abs(p[0] - g[0]) < 1e-9
    if kind == "number":  # exchange ratio: the model may return "one" for "one (1) share"
        g = numbers(gold, words=True)
        return bool(g) and any(abs(n - g[0]) < 1e-9 for n in numbers(pred, words=True))
    if kind == "date":
        p, g = parse_dates(pred), parse_dates(gold)
        return bool(p and g) and p[0][0] == g[0][0]
    if kind == "date_or_text":  # a calendar date when both sides have one, otherwise the wording
        p, g = parse_dates(pred), parse_dates(gold)
        if p and g:
            return p[0][0] == g[0][0]
        return token_f1(pred, gold) >= 0.5
    if kind == "label":  # one of a fixed list of labels: exact, case-insensitive
        return pred.strip().lower() == gold.strip().lower()
    if kind == "category":  # GLiNER returns a phrase, so accept it when it contains the label's key word
        return gold.lower().split()[0] in pred.lower()
    return token_f1(pred, gold) >= 0.5  # free text: lenient token overlap


# ---------------------------------------------------------------- data
def load_ground_truth(path: Path = GT_PATH) -> pd.DataFrame:
    """Ground truth for filings the notebook has finished (it writes mergers.csv while it runs)."""
    gt = pd.read_csv(path, dtype=str, keep_default_na=False)
    log = path.with_name("merger_run_log.csv" if path.name == "mergers.csv" else path.stem.replace("mergers", "merger") + "_run_log.csv")
    if log.exists():
        done = set(pd.read_csv(log, dtype=str).query("status == 'ok'")["accession_number"])
        gt = gt[gt["accession_number"].isin(done)]
    return gt


def passages_of(row) -> dict:
    try:
        value = json.loads(row["passages"]) if row.get("passages") else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def filing_text(accession: str, text_dir: Path = TEXT_DIR) -> str:
    return (text_dir / f"{accession}.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------- deal split
def deal_groups(gt: pd.DataFrame) -> dict[str, str]:
    """accession -> deal group. Filings are joined when they share an SEC file number, a filer CIK or a target name,
    so every filing about one deal (425, S-4, proxy, 8-K) ends up on the same side of the split. Joining on CIK
    can also merge two deals by one company, which only makes the split more cautious."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    accessions = set(gt["accession_number"])
    if SELECTED_FILINGS.exists():
        sel = pd.read_csv(SELECTED_FILINGS, dtype=str, keep_default_na=False)
        for _, r in sel[sel["accession"].isin(accessions)].iterrows():
            for key in re.findall(r"[\w-]+", r["file_nums"]) + re.findall(r"\d{6,}", r["ciks"]):
                union(r["accession"], f"key:{key}")
    for _, r in gt.iterrows():
        target = norm_name(r.get("target", ""))
        if target and target not in GENERIC_ROLES:
            union(r["accession_number"], f"target:{target}")
    return {acc: find(acc) for acc in accessions}


def assign_splits(gt: pd.DataFrame, holdout_share: float = 0.2) -> pd.DataFrame:
    """Train/holdout by deal group. Earlier assignments in splits.csv are kept, so the holdout stays the same as
    more filings arrive; a group that contains any earlier holdout filing stays in the holdout."""
    groups = deal_groups(gt)
    earlier = {}
    if SPLITS_PATH.exists():
        earlier = dict(pd.read_csv(SPLITS_PATH, dtype=str)[["accession_number", "split"]].values)
    members = defaultdict(list)
    for acc, g in groups.items():
        members[g].append(acc)
    rows = []
    for g, accs in members.items():
        prior = {earlier[a] for a in accs if a in earlier}
        if "holdout" in prior:
            split = "holdout"
        elif prior:
            split = "train"
        else:
            bucket = int(hashlib.sha256(min(accs).encode()).hexdigest(), 16) % 100
            split = "holdout" if bucket < holdout_share * 100 else "train"
        rows += [{"accession_number": a, "deal_group": g, "split": split} for a in sorted(accs)]
    return pd.DataFrame(rows).sort_values("accession_number").reset_index(drop=True)


VALIDATION_PATH = TRAINING_DATA / "validation_accessions.txt"


def make_validation(share: float = 0.15) -> list[str]:
    """Carve a validation set out of the training deals (by deal group, with a different hash from the holdout), for
    choosing checkpoints, thresholds and methods. The 103 held-out filings are never used for those choices."""
    splits = pd.read_csv(SPLITS_PATH, dtype=str)
    train = splits[splits["split"] == "train"]
    chosen = []
    for group, rows in train.groupby("deal_group"):
        bucket = int(hashlib.sha256(("validation:" + group).encode()).hexdigest(), 16) % 100
        if bucket < share * 100:
            chosen += list(rows["accession_number"])
    VALIDATION_PATH.write_text("\n".join(sorted(chosen)) + "\n")
    return sorted(chosen)


def validation_accessions() -> list[str]:
    if not VALIDATION_PATH.exists():
        return make_validation()
    return [a for a in VALIDATION_PATH.read_text().split() if a]


def holdout_accessions() -> list[str]:
    if not SPLITS_PATH.exists():
        raise SystemExit(f"{SPLITS_PATH} not found: run mergers_extraction/build_training_data.py first")
    splits = pd.read_csv(SPLITS_PATH, dtype=str)
    return sorted(splits.loc[splits["split"] == "holdout", "accession_number"])


# ---------------------------------------------------------------- scoring
def oracle_windows(passages: list[dict], width: int = 900) -> list[tuple[int, str]]:
    """Ground-truth quotes, deduplicated and cut to GLiNER-sized pieces."""
    seen, out = set(), []
    for record in passages:
        for quotes in record.values():
            for q in quotes or []:
                text = (q or {}).get("quote") or "" if isinstance(q, dict) else ""
                for i in range(0, len(text), width):
                    piece = text[i:i + width]
                    if piece.strip() and piece not in seen:
                        seen.add(piece)
                        out.append((-1, piece))
    return out


def quote_coverage(text: str, windows: list[tuple[int, str]], passages: list[dict]) -> dict[str, list[int]]:
    """Per field: [quotes found in the filing, of those, quotes overlapping a pipeline window]."""
    spans = [(o, o + len(w)) for o, w in windows]
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in passages:
        for field, quotes in record.items():
            for q in quotes or []:
                quote = re.sub(r"\s+", " ", (q or {}).get("quote") or "" if isinstance(q, dict) else "").strip()[:200]
                pos = text.find(quote) if quote else -1
                if pos < 0:
                    continue
                out[field][0] += 1
                out[field][1] += any(lo < pos + len(quote) and pos < hi for lo, hi in spans)
    return out


def predict(model, windows: list[tuple[int, str]], fields: dict, threshold: float) -> dict[str, dict]:
    """Top-scoring span per field across the windows."""
    labels = [label for label, _ in fields.values()]
    label_to_field = {label: field for field, (label, _) in fields.items()}
    best: dict[str, dict] = {}
    for _, chunk in windows:
        for ent in model.predict_entities(chunk, labels, threshold=threshold):
            field = label_to_field.get(ent["label"])
            if field and (field not in best or ent["score"] > best[field]["score"]):
                best[field] = {"value": ent["text"], "score": float(ent["score"])}
    return best


def prf(c: Counter) -> dict:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "gt_absence_values": c["gt_absence"], "precision": p, "recall": r, "f1": f}


def evaluate(model, gt: pd.DataFrame, fields: dict, *, threshold: float = 0.4, max_windows: int = 12,
             text_dir: Path = TEXT_DIR, log=print, window_fn=None, window_name: str = "pipeline",
             oracle: bool = True) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Score one top span per field and filing against every ground-truth record of that filing, twice:
    with the chosen windows (default 'pipeline': the existing keyword windows) and 'oracle': the record's own
    supporting quotes. window_fn(text) -> [(offset, chunk)] replaces the pipeline windows."""
    window_fn = window_fn or (lambda text: select_windows(text, max_windows=max_windows))
    modes = (window_name, "oracle") if oracle else (window_name,)
    counts = {mode: defaultdict(Counter) for mode in modes}
    coverage: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    details = []
    accessions = list(dict.fromkeys(gt["accession_number"]))
    for n, acc in enumerate(accessions, 1):
        text = filing_text(acc, text_dir)
        records = gt[gt["accession_number"] == acc]
        passages = [passages_of(r) for _, r in records.iterrows()]
        windows = {window_name: window_fn(text)}
        if oracle:
            windows["oracle"] = oracle_windows(passages)
        for field, (found, covered) in quote_coverage(text, windows[window_name], passages).items():
            coverage[field][0] += found
            coverage[field][1] += covered
        for mode, wins in windows.items():
            preds = predict(model, wins, fields, threshold)
            for _, row in records.iterrows():
                for field, (_, kind) in fields.items():
                    gold = "" if blank(row.get(field)) else str(row[field]).strip()
                    pred = preds.get(field, {}).get("value", "")
                    c = counts[mode][field]
                    if not gold and not pred:
                        continue
                    if gold and absence(gold):
                        c["gt_absence"] += 1
                        outcome = "absence_value"
                        if pred:
                            c["fp"] += 1
                    elif gold and pred and match(kind, pred, gold):
                        c["tp"] += 1
                        outcome = "tp"
                    elif gold and pred:
                        c["fp"] += 1
                        c["fn"] += 1
                        outcome = "mismatch"
                    elif pred:
                        c["fp"] += 1
                        outcome = "fp_no_gt"
                    else:
                        c["fn"] += 1
                        outcome = "fn_no_pred"
                    details.append({"mode": mode, "accession_number": acc, "form": row["form"], "field": field,
                                    "gt": gold, "pred": pred, "score": preds.get(field, {}).get("score"),
                                    "outcome": outcome})
        log(f"{n}/{len(accessions)} {acc} ({len(windows[window_name])} {window_name} windows)")

    rows = []
    for field, (label, kind) in fields.items():
        found, covered = coverage.get(field, [0, 0])
        row = {"field": field, "label": label, "compare": kind,
               f"quotes_in_{window_name}_windows": f"{covered}/{found}" if found else ""}
        for mode in modes:
            for key, value in prf(counts[mode][field]).items():
                if key in ("f1", "precision", "recall"):
                    row[f"{mode}_{key}"] = None if value is None else round(value, 3)
                elif mode == window_name:
                    row[key] = value
        rows.append(row)
    micro = {mode: prf(sum((counts[mode][f] for f in fields), Counter())) for mode in modes}
    return pd.DataFrame(rows), micro, pd.DataFrame(details)


def score_predictions(gt: pd.DataFrame, predictions: dict[str, dict[str, str]], fields: dict[str, str],
                      mode: str) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Score any method's answers with the same rules as evaluate(): one answer per field and filing, compared with
    every ground-truth record of that filing. predictions: accession -> field -> value ("" = abstained).
    fields: field -> comparison kind. mode names the input the method read (e.g. "learned", "fulltext")."""
    counts: dict[str, Counter] = defaultdict(Counter)
    details = []
    for acc, records in gt.groupby("accession_number", sort=False):
        preds = predictions.get(acc, {})
        for _, row in records.iterrows():
            for field, kind in fields.items():
                gold = "" if blank(row.get(field)) else str(row[field]).strip()
                pred = "" if blank(preds.get(field)) else str(preds[field]).strip()
                c = counts[field]
                if not gold and not pred:
                    continue
                if gold and absence(gold):
                    c["gt_absence"] += 1
                    outcome = "absence_value"
                    if pred and not absence(pred):
                        c["fp"] += 1
                    elif pred:  # the method also stated the absence
                        outcome = "absence_matched"
                elif gold and pred and match(kind, pred, gold):
                    c["tp"] += 1
                    outcome = "tp"
                elif gold and pred:
                    c["fp"] += 1
                    c["fn"] += 1
                    outcome = "mismatch"
                elif pred:
                    c["fp"] += 1
                    outcome = "fp_no_gt"
                else:
                    c["fn"] += 1
                    outcome = "fn_no_pred"
                details.append({"mode": mode, "accession_number": acc, "form": row["form"], "field": field,
                                "gt": gold, "pred": pred, "score": "", "outcome": outcome})
    rows = []
    for field, kind in fields.items():
        scores = prf(counts[field])
        row = {"field": field, "label": "", "compare": kind}
        row.update({k: scores[k] for k in ("tp", "fp", "fn", "gt_absence_values")})
        for key in ("precision", "recall", "f1"):
            row[f"{mode}_{key}"] = None if scores[key] is None else round(scores[key], 3)
        rows.append(row)
    micro = {mode: prf(sum(counts.values(), Counter()))}
    return pd.DataFrame(rows), micro, pd.DataFrame(details)


def rescore(folder: Path) -> dict:
    """Recompute a saved run's scores from its details.csv with the current match(), without running the model.
    Used when the scorer changes. Rows with no prediction or no ground-truth value keep their outcome."""
    details = pd.read_csv(folder / "details.csv", keep_default_na=False)
    per_field = pd.read_csv(folder / "per_field.csv")
    summary = json.loads((folder / "summary.json").read_text())
    kinds = {f: k for f, (_, k) in {**SPAN_FIELDS, **SUMMARY_FIELDS}.items()}
    changed = 0
    for i, row in details.iterrows():
        if row["outcome"] in ("tp", "mismatch"):
            new = "tp" if match(kinds[row["field"]], str(row["pred"]), str(row["gt"])) else "mismatch"
            changed += new != row["outcome"]
            details.at[i, "outcome"] = new
    modes = list(dict.fromkeys(details["mode"])) or [window_mode_of(per_field)]
    counts = {mode: defaultdict(Counter) for mode in modes}
    effect = {"tp": {"tp": 1}, "mismatch": {"fp": 1, "fn": 1}, "fp_no_gt": {"fp": 1}, "fn_no_pred": {"fn": 1}}
    for _, row in details.iterrows():
        c = counts[row["mode"]][row["field"]]
        if row["outcome"] in ("absence_value", "absence_matched"):
            c["gt_absence"] += 1
            c["fp"] += row["outcome"] == "absence_value" and bool(str(row["pred"]))
        else:
            for key, n in effect[row["outcome"]].items():
                c[key] += n
    window_name = next(m for m in modes if m != "oracle")
    for i, row in per_field.iterrows():
        for mode in modes:
            scores = prf(counts[mode][row["field"]])
            for key in ("precision", "recall", "f1"):
                per_field.at[i, f"{mode}_{key}"] = None if scores[key] is None else round(scores[key], 3)
            if mode == window_name:
                for key in ("tp", "fp", "fn", "gt_absence_values"):
                    per_field.at[i, key] = scores[key]
    fields = list(per_field["field"])
    summary["micro"] = {mode: prf(sum((counts[mode][f] for f in fields), Counter())) for mode in modes}
    details.to_csv(folder / "details.csv", index=False)
    per_field.to_csv(folder / "per_field.csv", index=False)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    return {"run": str(folder.relative_to(OUTPUTS)), "outcomes_changed": changed,
            **{f"micro_f1_{m}": round(summary["micro"][m]["f1"] or 0, 3) for m in modes}}


def window_mode_of(per_field: pd.DataFrame) -> str:
    return next(c[:-3] for c in per_field.columns if c.endswith("_f1") and c != "oracle_f1")


def write_results(out: Path, per_field: pd.DataFrame, micro: dict, details: pd.DataFrame, meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    per_field.to_csv(out / "per_field.csv", index=False)
    details.to_csv(out / "details.csv", index=False)
    summary = {**meta, "micro": micro,
               "note": "Agreement with unverified LLM ground truth. Category fields accept a span containing the "
                       "label's key word; free-text fields use token F1 >= 0.5. Stated absences ('No ...') are "
                       "counted apart because a span model cannot produce them."}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
