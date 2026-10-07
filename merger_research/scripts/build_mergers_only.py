#!/usr/bin/env python3
"""Review SEC merger candidates and export only confirmed filing documents.

Run ``screen`` to create a review CSV for every archived document. Reviewers fill
review_label, reviewer, reviewed_at, and confirmed_evidence. Run ``export`` to
build a ZIP and manifest containing only valid, reviewed merger rows.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
DATA = PROJECT / 'data/mergers/sec_2025'
OUTPUT = PROJECT / 'merger_research/outputs/mergers/sec_2025'
ARCHIVE = DATA / 'sec_merger_downloads_2025.zip'
MANIFEST = DATA / 'sec_merger_downloads_2025_manifest.csv'
QUEUE = OUTPUT / 'review_queue.csv'
EXPORT = OUTPUT / 'confirmed_merger_filings.zip'
FIELDS = [
    'accession_number', 'filing_date', 'reporting_filer', 'cik', 'form',
    'sec_source_url', 'archive_path', 'text_sha256', 'screen_status',
    'suggested_priority', 'evidence_types', 'suggested_evidence',
    'review_label', 'reviewer', 'reviewed_at', 'confirmed_evidence',
    'deal_id', 'review_note',
]
LABELS = {'', 'merger', 'not_merger', 'uncertain'}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def priority(source: dict, filing_date: str) -> str:
    """Rank review effort; this is never a merger label."""
    evidence = source.get('evidence') or []
    snippets = [str(e.get('excerpt', '')) for e in evidence]
    types = {str(e.get('event_type', '')) for e in evidence}
    year = filing_date[:4]
    current = any(re.search(r'\b' + re.escape(year) + r'\b', s) for s in snippets)
    if current and types & {'merger_agreement_signed', 'merger_completed'}:
        return 'high'
    if evidence:
        return 'medium'
    return 'low'


def screen(archive_path: Path, manifest_path: Path, queue_path: Path) -> dict:
    inventory = read_csv(manifest_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve completed reviews when rebuilding the queue, but reject a stale
    # decision if its source text changed.
    previous = {r['accession_number']: r for r in read_csv(queue_path)} if queue_path.exists() else {}
    rows = []
    counts = Counter()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        seen = set()
        for item in inventory:
            accession = item['accession_number']
            if accession in seen:
                raise ValueError(f'Duplicate accession: {accession}')
            seen.add(accession)
            path = item['archive_path']
            if path not in names:
                raise ValueError(f'Missing archive member: {path}')
            source = json.loads(archive.read(path))
            text = source.get('text') or ''
            if not text or source.get('error'):
                raise ValueError(f'Missing document text: {accession}')
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            evidence = source.get('evidence') or []
            snippets = [str(e.get('excerpt', '')) for e in evidence]
            row = {k: item.get(k, '') for k in FIELDS}
            row.update({
                'text_sha256': digest,
                'screen_status': str(source.get('screen_status') or ''),
                'suggested_priority': priority(source, item['filing_date']),
                'evidence_types': ';'.join(sorted({str(e.get('event_type', '')) for e in evidence})),
                'suggested_evidence': next((s[:1200] for s in snippets if s), ''),
            })
            old = previous.get(accession)
            if old and old.get('text_sha256') == digest:
                for key in ('review_label', 'reviewer', 'reviewed_at', 'confirmed_evidence', 'deal_id', 'review_note'):
                    row[key] = old.get(key, '')
            rows.append(row)
            counts[row['suggested_priority']] += 1
    # No partial queue on an invalid archive. A temporary file is replaced only
    # after all documents have been checked.
    temp = queue_path.with_suffix('.csv.tmp')
    write_csv(temp, rows, FIELDS)
    temp.replace(queue_path)
    return {'screened': len(rows), 'priority_counts': dict(counts), 'review_queue': str(queue_path)}


def export(archive_path: Path, manifest_path: Path, queue_path: Path, output_path: Path) -> dict:
    inventory = {r['accession_number']: r for r in read_csv(manifest_path)}
    rows = read_csv(queue_path)
    seen = set()
    approved = []
    counts = Counter()
    for row in rows:
        accession = row['accession_number']
        if accession in seen:
            raise ValueError(f'Duplicate review row: {accession}')
        seen.add(accession)
        if accession not in inventory:
            raise ValueError(f'Unknown accession in review queue: {accession}')
        label = row['review_label'].strip().lower()
        if label not in LABELS:
            raise ValueError(f'Invalid review label for {accession}: {label}')
        counts[label or 'unreviewed'] += 1
        if label == 'merger':
            approved.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix('.zip.tmp')
    exported = []
    try:
        with zipfile.ZipFile(archive_path) as source_zip, zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as target_zip:
            for row in approved:
                accession = row['accession_number']
                item = inventory[accession]
                if any(row.get(key, '') != item.get(key, '') for key in ('filing_date', 'reporting_filer', 'cik', 'form', 'sec_source_url', 'archive_path')):
                    raise ValueError(f'Manifest metadata changed for {accession}; rebuild review queue')
                reviewer = row['reviewer'].strip()
                quote = row['confirmed_evidence'].strip()
                if not reviewer or len(quote) < 20:
                    raise ValueError(f'Confirmed merger needs reviewer and evidence quote: {accession}')
                try:
                    date.fromisoformat(row['reviewed_at'].strip())
                except ValueError as exc:
                    raise ValueError(f'Confirmed merger needs ISO review date: {accession}') from exc
                raw = source_zip.read(item['archive_path'])
                doc = json.loads(raw)
                text = doc.get('text') or ''
                if hashlib.sha256(text.encode('utf-8')).hexdigest() != row['text_sha256']:
                    raise ValueError(f'Source text changed for {accession}; rebuild review queue')
                if quote not in text:
                    raise ValueError(f'Confirmed evidence not found in source text: {accession}')
                target_zip.writestr(item['archive_path'], raw)
                exported.append({
                    **{k: item[k] for k in ('accession_number', 'filing_date', 'reporting_filer', 'cik', 'form', 'sec_source_url', 'archive_path')},
                    'text_sha256': row['text_sha256'],
                    'reviewer': reviewer,
                    'reviewed_at': row['reviewed_at'],
                    'confirmed_evidence': quote,
                    'deal_id': row.get('deal_id', '').strip(),
                    'review_note': row.get('review_note', '').strip(),
                })
            buffer = io.StringIO()
            fields = list(exported[0]) if exported else ['accession_number', 'filing_date', 'reporting_filer', 'cik', 'form', 'sec_source_url', 'archive_path', 'text_sha256', 'reviewer', 'reviewed_at', 'confirmed_evidence', 'deal_id', 'review_note']
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(exported)
            target_zip.writestr('confirmed_manifest.csv', buffer.getvalue())
        temp.replace(output_path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    summary = {'review_rows': len(rows), 'labels': dict(counts), 'confirmed_filings': len(exported), 'output': str(output_path)}
    output_path.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('screen', 'export'))
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--queue', type=Path, default=QUEUE)
    parser.add_argument('--output', type=Path, default=EXPORT)
    args = parser.parse_args()
    result = screen(args.archive, args.manifest, args.queue) if args.command == 'screen' else export(args.archive, args.manifest, args.queue, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
