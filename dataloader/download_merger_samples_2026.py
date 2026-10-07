#!/usr/bin/env python3
"""Download dated 2026 merger-candidate samples as SEC HTML and local PDFs.

Uses the existing 2026 review queue for sampling; priority is not a confirmed
merger label. Keeps these files separate from the 2020-2025 dataloader sample.
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from download_samples import CHROME, OUT, ROOT, SecClient, save_doc


QUEUE = ROOT / 'data/mergers/sec_2026/review_queue.csv'
DEST = OUT / 'mergers_2026'
MANIFEST = OUT / 'manifest_2026_mergers.csv'
FIELDS = [
    'folder', 'form', 'year', 'accession', 'filename', 'entity_name',
    'file_date', 'file_description', 'file_type', 'doc_role',
    'screen_priority', 'evidence_types', 'source_archive_path',
    'url', 'local_path', 'html_path', 'bytes', 'html_bytes', 'status', 'error',
]


def select(queue: Path, start: date, end: date, per_month: int) -> list[dict[str, str]]:
    if per_month <= 0:
        raise ValueError('--per-month must be positive')
    with queue.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        filing_date = date.fromisoformat(row['filing_date'])
        if start <= filing_date <= end and row['suggested_priority'] == 'high':
            grouped[row['filing_date'][:7]].append(row)
    chosen = []
    for month in sorted(grouped):
        # Prefer primary domestic reports, then diversify filers within month.
        candidates = sorted(grouped[month], key=lambda r: (
            {'8-K': 0, '8-K/A': 1, 'DEFM14A': 2, '6-K': 3, '6-K/A': 4}.get(r['form'], 5),
            r['filing_date'], r['accession_number'],
        ))
        used_ciks = set()
        month_rows = []
        for row in candidates:
            if row['cik'] not in used_ciks:
                month_rows.append(row)
                used_ciks.add(row['cik'])
            if len(month_rows) == per_month:
                break
        if len(month_rows) < per_month:
            month_rows.extend(row for row in candidates if row not in month_rows)  # pragma: no cover
        chosen.extend(month_rows[:per_month])
    return chosen


def run(per_month: int, start: date, end: date, force: bool, chrome: Path, queue: Path = QUEUE) -> Path:
    if not queue.exists():
        raise SystemExit(f'Missing {queue}')
    if not chrome.exists():
        raise SystemExit(f'Chrome not found at {chrome}')
    selected = select(queue, start, end, per_month)
    expected_months = {(start.year, m) for m in range(start.month, end.month + 1)} if start.year == end.year else set()
    actual_months = {(int(r['filing_date'][:4]), int(r['filing_date'][5:7])) for r in selected}
    if expected_months and actual_months != expected_months:
        raise SystemExit(f'No high-priority candidates in months: {sorted(expected_months - actual_months)}')
    client = SecClient(user_agent=os.environ.get('EDGAR_IDENTITY') or None)
    print(f'Selected {len(selected)} candidate filings across {len(actual_months)} months', flush=True)
    DEST.mkdir(parents=True, exist_ok=True)
    records = []
    for index, row in enumerate(selected, 1):
        filename = Path(urlparse(row['sec_source_url']).path).name
        result = save_doc(
            client, cik=row['cik'], accession=row['accession_number'],
            filename=filename, dest=DEST, force=force, chrome=chrome,
        )
        if result['status'] == 'failed' and result['html_path']:
            result['status'] = 'html_only'
        records.append({
            'folder': 'mergers_2026', 'form': row['form'], 'year': 2026,
            'accession': row['accession_number'], 'filename': filename,
            'entity_name': row['reporting_filer'], 'file_date': row['filing_date'],
            'file_description': '', 'file_type': row['form'], 'doc_role': 'screened_candidate',
            'screen_priority': row['suggested_priority'], 'evidence_types': row['evidence_types'],
            'source_archive_path': row['archive_path'], **result,
        })
        with MANIFEST.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)
        print(f'{index}/{len(selected)} {row["filing_date"]} {row["accession_number"]} {result["status"]}', flush=True)
    return MANIFEST


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument('--per-month', type=int, default=3)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--chrome', type=Path, default=CHROME)
    parser.add_argument('--queue', type=Path, default=QUEUE, help='Merger review queue CSV')
    args = parser.parse_args()
    if args.end < args.start:
        parser.error('--end must be on or after --start')
    print(run(args.per_month, args.start, args.end, args.force, args.chrome, args.queue))


if __name__ == '__main__':
    main()
