#!/usr/bin/env python3
"""Read the 2025 SEC merger candidate archive into merger-research outputs.

Run from any directory:
  python merger_research/scripts/import_sec_merger_2025.py
  python merger_research/scripts/import_sec_merger_2025.py --mode all --limit 100

The importer preserves SEC provenance and emits unreviewed candidates. It does
not create deal IDs, canonical merger events, or BNY notifications.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = RESEARCH_ROOT.parent
DATA_ROOT = PROJECT_ROOT / 'data' / 'mergers' / 'sec_2025'
DEFAULT_OUTPUT_ROOT = RESEARCH_ROOT / 'outputs' / 'mergers' / 'sec_2025'


def load_sample(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('sample', 'all'), default='sample')
    parser.add_argument('--limit', type=int, default=None, help='Optional cap for a staged run')
    parser.add_argument('--archive', type=Path, default=DATA_ROOT / 'sec_merger_downloads_2025.zip')
    parser.add_argument('--sample', type=Path, default=DATA_ROOT / 'sec_merger_sample_2025.csv')
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be positive')
    if not args.archive.exists():
        parser.error(f'Archive missing: {args.archive}')
    if args.mode == 'sample' and not args.sample.exists():
        parser.error(f'Sample CSV missing: {args.sample}')

    sys.path.insert(0, str(RESEARCH_ROOT))
    from src.eda.merger import extract

    output = args.output or DEFAULT_OUTPUT_ROOT / f'{args.mode}_candidates.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    summary_path = output.with_suffix('.summary.json')
    form_counts: Counter[str] = Counter()
    detections: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    processed = 0

    with zipfile.ZipFile(args.archive) as archive:
        archive_names = set(archive.namelist())
        with (DATA_ROOT / 'sec_merger_downloads_2025_manifest.csv').open(newline='', encoding='utf-8-sig') as stream:
            inventory = list(csv.DictReader(stream))
        by_accession: dict[str, dict[str, str]] = {}
        for item in inventory:
            accession = item['accession_number']
            if accession in by_accession:
                parser.error(f'Duplicate accession in manifest: {accession}')
            if item['archive_path'] not in archive_names:
                parser.error(f'Document missing from archive: {item["archive_path"]}')
            by_accession[accession] = item

        if args.mode == 'sample':
            sample = load_sample(args.sample)
            missing = sorted({r['accession_number'] for r in sample} - set(by_accession))
            if missing:
                parser.error(f'Sample accessions missing from manifest: {missing[:5]}')
            selected = [(by_accession[r['accession_number']], r['reporting_filer']) for r in sample]
        else:
            selected = [(item, item['reporting_filer']) for item in inventory]
        if args.limit is not None:
            selected = selected[:args.limit]

        try:
            with temporary.open('w', encoding='utf-8') as stream:
                for item, filer in selected:
                    source = json.loads(archive.read(item['archive_path']))
                    text = source.get('text') or ''
                    if source.get('error') or not text:
                        raise ValueError(f'Missing text for {item["accession_number"]}')
                    result = extract(text, item['form'])
                    for evidence in result['candidates'] + result['passages']:
                        if text[evidence['evidence_start']:evidence['evidence_end']] != evidence['source_quote']:
                            raise ValueError(f'Broken evidence offset for {item["accession_number"]}')
                    record = {
                        'accession': item['accession_number'],
                        'filing_date': item['filing_date'],
                        'form': item['form'],
                        'reporting_filer': filer,
                        'cik': item['cik'],
                        'source_url': item['sec_source_url'],
                        'archive_path': item['archive_path'],
                        'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                        'detection': result['detection'],
                        'cue_count': result['cue_count'],
                        'candidates': result['candidates'],
                        'passages': result['passages'],
                        'conflicting_values': result['conflicting_values'],
                        'canonical_fields': result['canonical_fields'],
                        'requires_review': True,
                        'gold_is_merger': None,
                        'deal_id': None,
                        'method': result['method'],
                    }
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                    processed += 1
                    form_counts[item['form']] += 1
                    detections[result['detection']] += 1
                    candidate_counts.update(c['field'] for c in result['candidates'])
            temporary.replace(output)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    summary = {
        'mode': args.mode,
        'source_archive': str(args.archive),
        'documents_in_archive': len(inventory),
        'documents_processed': processed,
        'by_form': dict(form_counts),
        'detection': dict(detections),
        'candidate_occurrences_by_field': dict(candidate_counts),
        'metric_note': 'Rule-selected development material; candidates are unreviewed and accuracy is not measured.',
        'output': str(output),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
