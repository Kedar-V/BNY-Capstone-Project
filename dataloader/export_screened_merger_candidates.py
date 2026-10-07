#!/usr/bin/env python3
"""Export screened merger-language filings from a SEC candidate archive.

This creates a reviewable candidate set, not a confirmed mergers-only set.
Use merger_research/scripts/build_mergers_only.py export for reviewed labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/mergers/sec_2026"
DEFAULT_ARCHIVE = SOURCE / "sec_merger_downloads_2026_Jan_Sep.zip"
DEFAULT_MANIFEST = SOURCE / "sec_merger_downloads_2026_Jan_Sep_manifest.csv"
DEFAULT_QUEUE = SOURCE / "review_queue.csv"
DEFAULT_OUTPUT = SOURCE / "screened_merger_candidates_2026_Jan_Sep.zip"
STATUS = "merger_event_language_found"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def export(archive_path: Path, manifest_path: Path, queue_path: Path, output_path: Path) -> dict:
    inventory = rows(manifest_path)
    queue = rows(queue_path)
    by_accession = {row["accession_number"]: row for row in inventory}
    if len(by_accession) != len(inventory):
        raise ValueError("Duplicate accessions in source manifest")
    if len(queue) != len(inventory):
        raise ValueError("Review queue and source manifest have different row counts")
    if {row["accession_number"] for row in queue} != set(by_accession):
        raise ValueError("Review queue and source manifest have different accessions")

    selected = [row for row in queue if row["screen_status"] == STATUS]
    selected.sort(key=lambda row: (row["filing_date"], row["accession_number"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    exported = []
    try:
        with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
            names = set(source.namelist())
            for row in selected:
                item = by_accession[row["accession_number"]]
                for field in ("archive_path", "filing_date", "form", "cik", "sec_source_url"):
                    if row[field] != item[field]:
                        raise ValueError(f"Stale queue metadata for {row['accession_number']}: {field}")
                path = item["archive_path"]
                if path not in names:
                    raise ValueError(f"Missing archive member: {path}")
                raw = source.read(path)
                document = json.loads(raw)
                text = document.get("text") or ""
                if not text or document.get("error"):
                    raise ValueError(f"Missing text for {row['accession_number']}")
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["text_sha256"]:
                    raise ValueError(f"Stale source text for {row['accession_number']}")
                if document.get("screen_status") != STATUS or not document.get("evidence"):
                    raise ValueError(f"Missing merger-event screening evidence for {row['accession_number']}")
                target.writestr(path, raw)
                exported.append({**item, "screen_status": row["screen_status"],
                                 "suggested_priority": row["suggested_priority"],
                                 "evidence_types": row["evidence_types"],
                                 "suggested_evidence": row["suggested_evidence"],
                                 "text_sha256": row["text_sha256"],
                                 "review_label": row["review_label"]})

            fields = list(exported[0]) if exported else list(inventory[0]) + [
                "screen_status", "suggested_priority", "evidence_types",
                "suggested_evidence", "text_sha256", "review_label"]
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(exported)
            target.writestr("screened_manifest.csv", buffer.getvalue())
            target.writestr("README.txt", "Screened SEC filing candidates, not confirmed mergers or unique deals.\n"
                            "Filing dates are not necessarily announcement or completion dates.\n"
                            "Review every filing and supporting evidence before using as ground truth.\n")
        temporary.replace(output_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    summary = {
        "source_documents": len(inventory),
        "screened_candidates": len(exported),
        "candidate_dates": [min((r["filing_date"] for r in exported), default=""),
                            max((r["filing_date"] for r in exported), default="")],
        "priority_counts": dict(Counter(r["suggested_priority"] for r in exported)),
        "confirmed_mergers": sum(r["review_label"].strip().lower() == "merger" for r in exported),
        "archive": str(output_path),
    }
    manifest_output = output_path.with_suffix(".manifest.csv")
    manifest_temporary = manifest_output.with_suffix(".csv.tmp")
    with manifest_temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(exported)
    manifest_temporary.replace(manifest_output)
    summary["manifest"] = str(manifest_output)
    output_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(export(args.archive, args.manifest, args.queue, args.output), indent=2))


if __name__ == "__main__":
    main()
