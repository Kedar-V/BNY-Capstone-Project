"""Evidence-preserving GLiNER candidates for SEC merger filings.

The Evaluation branch's mergers.csv defines the field vocabulary, but its
unverified model outputs are never used to select text or tune predictions.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# GLiNER is a span detector; these are candidate spans, not resolved deal facts.
LABEL_TO_FIELD = {
    "acquirer organization": "acquirer",
    "target organization": "target",
    "cash consideration per share": "cash_consideration",
    "stock exchange ratio": "stock_exchange_ratio",
    "shareholder vote date": "shareholder_vote_date",
    "merger closing condition": "closing_conditions",
    "merger event status": "event_status",
    "affected security": "security_description",
    "stock ticker": "ticker",
    "CUSIP identifier": "cusip",
    "ISIN identifier": "isin",
    "merger effective date": "effective_date",
    "shareholder election option": "available_options",
    "default election option": "default_option",
    "election deadline": "election_deadline",
}

TICKER_RE = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?")
CUSIP_RE = re.compile(r"[0-9A-Z]{9}")
ISIN_RE = re.compile(r"[A-Z]{2}[0-9A-Z]{10}")

REFERENCE_FIELDS = frozenset(LABEL_TO_FIELD.values()) | {
    "consideration_type", "mandatory_voluntary_indicator"
}

SPAN_CSV_FIELDS = (
    "accession_number", "filing_date", "form", "sec_source_url", "field",
    "value", "score", "start", "end", "source_quote", "quote_start",
    "quote_end", "window_id", "method", "model", "text_sha256",
)

# Text selection is independent of reference values/passages. Cover varied
# merger terms while limiting model work on very long SEC documents.
ANCHORS = (
    r"agreement and plan of merger|merger agreement|business combination agreement",
    r"merger consideration|cash consideration|per share",
    r"exchange ratio|stock consideration|right to receive",
    r"special meeting|shareholder vote|stockholder vote",
    r"effective time|effective date|completed the merger",
    r"closing conditions|conditions to closing|regulatory approval",
    r"election deadline|cash election|stock election|default option",
    r"CUSIP|ISIN|ticker symbol",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def select_windows(text: str, *, window_chars: int = 900, max_windows: int = 12) -> list[tuple[int, str]]:
    """Return offsets and source substrings without using ground-truth content."""
    if not text.strip() or max_windows < 1 or window_chars < 100:
        return []
    starts = [0]
    for pattern in ANCHORS:
        matches = list(re.finditer(pattern, text, re.I))
        # First and last mentions help cover summaries and later terms.
        for match in (matches[:1] + matches[-1:]):
            start = max(0, min(match.start() - 180, len(text) - window_chars))
            if start not in starts and all(not (old <= match.start() < old + window_chars - 150) for old in starts):
                starts.append(start)
                if len(starts) >= max_windows:
                    break
        if len(starts) >= max_windows:
            break
    return [(start, text[start:start + window_chars]) for start in starts[:max_windows]]


def extract_document(text: str, backend: Any, *, max_windows: int = 12) -> dict[str, Any]:
    """Run GLiNER and return all source-linked candidates, without gold leakage."""
    labels = list(LABEL_TO_FIELD)
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int, int]] = set()
    windows = select_windows(text, max_windows=max_windows)
    for window_id, (offset, chunk) in enumerate(windows):
        for pred in backend.predict(chunk, labels):
            label = pred.get("label")
            if label not in LABEL_TO_FIELD:
                continue
            start = offset + int(pred.get("start", -1))
            end = offset + int(pred.get("end", -1))
            if start < offset or end > offset + len(chunk) or end <= start:
                continue
            value = text[start:end].strip()
            field = LABEL_TO_FIELD[label]
            if field == "ticker" and not TICKER_RE.fullmatch(value):
                continue
            if field == "cusip" and not CUSIP_RE.fullmatch(value):
                continue
            if field == "isin" and not ISIN_RE.fullmatch(value):
                continue
            if field == "cash_consideration":
                nearby = text[max(0, start - 35):min(len(text), end + 45)]
                if re.search(r"par\s+value|exercise\s+price|market\s+price", nearby, re.I):
                    continue
            key = (label, start, end)
            if key in seen:
                continue
            seen.add(key)
            lo, hi = max(0, start - 220), min(len(text), end + 220)
            candidates[field].append({
                "value": text[start:end],
                "label": label,
                "score": float(pred.get("score", 0.0)),
                "start": start,
                "end": end,
                "source_quote": text[lo:hi],
                "quote_start": lo,
                "quote_end": hi,
                "window_id": window_id,
                "method": "gliner",
            })
    for values in candidates.values():
        values.sort(key=lambda item: (-item["score"], item["start"]))
    return {"windows_scored": len(windows), "candidates": dict(candidates)}


def reference_coverage(reference_path: Path, inventory: list[dict[str, str]], selected: set[str]) -> dict[str, Any]:
    reference = read_csv(reference_path)
    if not reference or not REFERENCE_FIELDS.issubset(reference[0]):
        raise ValueError("Reference CSV is empty or lacks expected merger fields")
    by_accession: dict[str, int] = Counter(row["accession_number"].strip() for row in reference)
    available = {row["accession_number"] for row in inventory}
    overlap = set(by_accession) & available
    return {
        "reference_rows": len(reference),
        "reference_accessions": len(by_accession),
        "reference_accessions_in_archive": len(overlap),
        "reference_accessions_selected": len(set(by_accession) & selected),
        "reference_accessions_missing_from_archive": len(set(by_accession) - available),
        "reference_statuses": dict(Counter(row.get("relevance", "") for row in reference)),
        "overlapping_accessions": sorted(overlap),
        "note": "Coverage only. Evaluation CSV labels are unverified; no accuracy metric is computed.",
    }


def run(
    archive_path: Path,
    manifest_path: Path,
    output_path: Path,
    backend: Any,
    *,
    reference_path: Path | None = None,
    limit: int | None = None,
    max_windows: int = 12,
) -> dict[str, Any]:
    inventory = read_csv(manifest_path)
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if max_windows < 1:
        raise ValueError("max_windows must be positive")
    if len({r["accession_number"] for r in inventory}) != len(inventory):
        raise ValueError("Duplicate accession in manifest")
    selected = inventory[:limit] if limit is not None else inventory
    coverage = reference_coverage(reference_path, inventory, {r["accession_number"] for r in selected}) if reference_path else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = output_path.with_suffix(".partial.jsonl")
    by_form: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    completed: list[dict[str, Any]] = []
    if checkpoint.exists():
        completed = [json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(completed) > len(selected):
            raise ValueError("Checkpoint has more records than selected input")
        for index, record in enumerate(completed):
            if record["accession_number"] != selected[index]["accession_number"] or record["model"] != getattr(backend, "model_id", "unknown"):
                raise ValueError("Checkpoint does not match this input/model; choose a new output path")
            by_form[record["form"]] += 1
            candidate_counts.update({field: len(values) for field, values in record["candidates"].items()})
    with zipfile.ZipFile(archive_path) as source, checkpoint.open("a" if completed else "w", encoding="utf-8") as target:
            names = set(source.namelist())
            for index, item in enumerate(selected[len(completed):], len(completed) + 1):
                path = item["archive_path"]
                if path not in names:
                    raise ValueError(f"Missing source document: {path}")
                document = json.loads(source.read(path))
                text = document.get("text") or ""
                if not text or document.get("error"):
                    raise ValueError(f"Missing text: {item['accession_number']}")
                result = extract_document(text, backend, max_windows=max_windows)
                record = {
                    "accession_number": item["accession_number"],
                    "filing_date": item["filing_date"],
                    "form": item["form"],
                    "sec_source_url": item["sec_source_url"],
                    "archive_path": path,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "model": getattr(backend, "model_id", "unknown"),
                    **result,
                    "canonical_fields": {field: None for field in sorted(REFERENCE_FIELDS)},
                    "requires_review": True,
                }
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
                target.flush()
                by_form[item["form"]] += 1
                candidate_counts.update({field: len(values) for field, values in result["candidates"].items()})
                if index % 10 == 0 or index == len(selected):
                    print(f"GLiNER {index}/{len(selected)} filings", flush=True)
    checkpoint.replace(output_path)
    summary = {
        "documents_processed": len(selected),
        "by_form": dict(by_form),
        "candidate_spans_by_field": dict(candidate_counts),
        "model": getattr(backend, "model_id", "unknown"),
        "model_threshold": getattr(backend, "threshold", None),
        "max_windows_per_document": max_windows,
        "output": str(output_path),
        "reference_coverage": coverage,
        "note": "Unreviewed GLiNER spans; canonical merger fields remain null.",
    }
    output_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def run_reference_texts(
    reference_path: Path,
    text_dir: Path,
    output_path: Path,
    backend: Any,
    *,
    limit: int | None = None,
    max_windows: int = 12,
) -> dict[str, Any]:
    """Process Evaluation input_text/<accession>.txt when those files exist.

    Reference values are used only to identify input files and metadata, never
    to choose windows or generate a candidate.
    """
    reference = read_csv(reference_path)
    if not reference or not REFERENCE_FIELDS.issubset(reference[0]):
        raise ValueError("Reference CSV is empty or lacks expected merger fields")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if max_windows < 1:
        raise ValueError("max_windows must be positive")
    by_accession: dict[str, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    for row in reference:
        accession = row["accession_number"].strip()
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError(f"Invalid accession: {accession}")
        counts[accession] += 1
        previous = by_accession.setdefault(accession, row)
        if previous["input_hash"] != row["input_hash"]:
            raise ValueError(f"Multiple input hashes for {accession}")
    chosen = list(by_accession.items())[:limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    missing: list[str] = []
    processed = 0
    try:
        with temporary.open("w", encoding="utf-8") as target:
            for accession, meta in chosen:
                path = text_dir / f"{accession}.txt"
                if not path.is_file():
                    missing.append(accession)
                    continue
                text = path.read_text(encoding="utf-8")
                if not text.strip():
                    raise ValueError(f"Empty reference text: {path}")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                expected = meta.get("input_hash", "")
                if expected and digest != expected:
                    raise ValueError(f"Reference input hash mismatch: {accession}")
                result = extract_document(text, backend, max_windows=max_windows)
                record = {
                    "accession_number": accession,
                    "filing_date": meta["filing_date"],
                    "form": meta["form"],
                    "sec_source_url": meta["filing_index_url"],
                    "text_path": str(path),
                    "text_sha256": digest,
                    "reference_records": counts[accession],
                    "model": getattr(backend, "model_id", "unknown"),
                    **result,
                    "canonical_fields": {field: None for field in sorted(REFERENCE_FIELDS)},
                    "requires_review": True,
                }
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
                processed += 1
        temporary.replace(output_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    summary = {
        "reference_rows": len(reference),
        "reference_accessions": len(by_accession),
        "selected_accessions": len(chosen),
        "documents_processed": processed,
        "missing_text_accessions": missing,
        "model": getattr(backend, "model_id", "unknown"),
        "model_threshold": getattr(backend, "threshold", None),
        "max_windows_per_document": max_windows,
        "output": str(output_path),
        "note": "Unreviewed GLiNER spans; reference values are not adjudicated gold.",
    }
    output_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def export_spans_csv(jsonl_path: Path, csv_path: Path | None = None) -> dict[str, Any]:
    """Flatten candidate spans for review without promoting them to facts."""
    csv_path = csv_path or jsonl_path.with_suffix(".spans.csv")
    temporary = csv_path.with_suffix(".csv.tmp")
    count = 0
    with jsonl_path.open(encoding="utf-8") as source, temporary.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=SPAN_CSV_FIELDS)
        writer.writeheader()
        for line in source:
            record = json.loads(line)
            for field, candidates in record["candidates"].items():
                for candidate in candidates:
                    writer.writerow({
                        "accession_number": record["accession_number"],
                        "filing_date": record["filing_date"],
                        "form": record["form"],
                        "sec_source_url": record["sec_source_url"],
                        "field": field,
                        **{key: candidate[key] for key in (
                            "value", "score", "start", "end", "source_quote",
                            "quote_start", "quote_end", "window_id", "method")},
                        "model": record["model"],
                        "text_sha256": record["text_sha256"],
                    })
                    count += 1
    temporary.replace(csv_path)
    return {"span_csv": str(csv_path), "span_rows": count}
