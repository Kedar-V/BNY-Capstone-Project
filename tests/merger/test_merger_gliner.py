from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

from src.merger_gliner import export_spans_csv, extract_document, reference_coverage, run, run_reference_texts, select_windows


class FakeBackend:
    model_id = "fake-for-test"

    def predict(self, text, labels):
        term = "Acme Corp."
        pos = text.find(term)
        return ([{"label": "acquirer organization", "text": term,
                  "start": pos, "end": pos + len(term), "score": 0.9}]
                if pos >= 0 and "acquirer organization" in labels else [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_spans_keep_exact_source_offsets():
    text = "Cover text. " + "x" * 1200 + " Agreement and Plan of Merger: Acme Corp. will acquire Target Inc."
    assert select_windows(text)
    result = extract_document(text, FakeBackend())
    value = result["candidates"]["acquirer"][0]
    assert text[value["start"]:value["end"]] == "Acme Corp."
    assert text[value["quote_start"]:value["quote_end"]] == value["source_quote"]
    assert value["method"] == "gliner"


def test_rejects_identifier_noise_and_par_value():
    text = "mpb-20260101.htm Common Stock, $1.00 par value per share. Merger consideration is $539.22 for each share."

    class NoisyBackend:
        def predict(self, chunk, labels):
            output = []
            for label, value in (("stock ticker", "mpb-20260101"),
                                 ("cash consideration per share", "$1.00"),
                                 ("cash consideration per share", "$539.22")):
                start = chunk.find(value)
                if start >= 0:
                    output.append({"label": label, "start": start, "end": start + len(value), "score": 0.9})
            return output

    result = extract_document(text, NoisyBackend())
    assert "ticker" not in result["candidates"]
    assert [x["value"] for x in result["candidates"]["cash_consideration"]] == ["$539.22"]


def test_archive_run_and_reference_overlap(tmp_path: Path):
    text = "Acme Corp. entered into an Agreement and Plan of Merger with Target Inc."
    archive = tmp_path / "filings.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("documents/one.json", json.dumps({"text": text}))
    manifest = tmp_path / "manifest.csv"
    write_csv(manifest, ["accession_number", "filing_date", "form", "sec_source_url", "archive_path"],
              [{"accession_number": "0000000000-26-000001", "filing_date": "2026-01-02",
                "form": "8-K", "sec_source_url": "https://www.sec.gov/example", "archive_path": "documents/one.json"}])
    reference = tmp_path / "mergers.csv"
    from src.merger_gliner import REFERENCE_FIELDS
    fields = ["accession_number", "relevance", *sorted(REFERENCE_FIELDS)]
    write_csv(reference, fields, [
        {"accession_number": "0000000000-26-000001", "relevance": "candidate_not_verified"},
        {"accession_number": "0000000000-26-000001", "relevance": "candidate_not_verified"},
        {"accession_number": "0000000000-26-000002", "relevance": "candidate_not_verified"},
    ])
    output = tmp_path / "predictions.jsonl"
    summary = run(archive, manifest, output, FakeBackend(), reference_path=reference)
    assert summary["documents_processed"] == 1
    assert summary["reference_coverage"]["reference_rows"] == 3
    assert summary["reference_coverage"]["reference_accessions"] == 2
    assert summary["reference_coverage"]["reference_accessions_in_archive"] == 1
    assert summary["reference_coverage"]["reference_accessions_missing_from_archive"] == 1
    result = json.loads(output.read_text().strip())
    assert result["candidates"]["acquirer"][0]["value"] == "Acme Corp."
    assert all(value is None for value in result["canonical_fields"].values())
    span_result = export_spans_csv(output)
    with Path(span_result["span_csv"]).open(newline="", encoding="utf-8") as stream:
        span_rows = list(csv.DictReader(stream))
    assert span_result["span_rows"] == len(span_rows) == 1
    assert span_rows[0]["value"] == "Acme Corp."
    assert reference_coverage(reference, [], set())["reference_accessions_in_archive"] == 0


def test_reference_text_mode_uses_input_hash_and_unique_accession(tmp_path: Path):
    from src.merger_gliner import REFERENCE_FIELDS
    accession = "0000000000-26-000001"
    text = "Acme Corp. entered into a merger agreement with Target Inc."
    texts = tmp_path / "input_text"
    texts.mkdir()
    (texts / f"{accession}.txt").write_text(text, encoding="utf-8")
    reference = tmp_path / "mergers.csv"
    fields = ["accession_number", "input_hash", "filing_date", "form", "filing_index_url", *sorted(REFERENCE_FIELDS)]
    row = {"accession_number": accession, "input_hash": hashlib.sha256(text.encode()).hexdigest(),
           "filing_date": "2026-01-02", "form": "8-K", "filing_index_url": "https://www.sec.gov/example"}
    write_csv(reference, fields, [row, row])
    output = tmp_path / "reference_predictions.jsonl"
    summary = run_reference_texts(reference, texts, output, FakeBackend())
    assert summary["reference_rows"] == 2
    assert summary["documents_processed"] == 1
    assert json.loads(output.read_text())["reference_records"] == 2
    (texts / f"{accession}.txt").write_text(text + " changed", encoding="utf-8")
    try:
        run_reference_texts(reference, texts, output, FakeBackend())
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("changed source text was accepted")
