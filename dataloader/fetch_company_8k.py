#!/usr/bin/env python3
"""Fetch one company's SEC 8-K items and detected press releases with EdgarTools.

Saves source evidence and an inventory; it does not label corporate actions.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company', required=True, help='Company ticker or CIK')
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--out', type=Path, required=True, help='Local output directory, usually under data/')
    args = parser.parse_args()
    if args.end < args.start:
        parser.error('--end must be on or after --start')
    identity = os.environ.get('EDGAR_IDENTITY', '').strip()
    if not identity:
        parser.error('Set EDGAR_IDENTITY to your name and contact email before SEC requests')

    from edgar import Company, set_identity

    set_identity(identity)
    company = Company(int(args.company) if args.company.isdigit() else args.company)
    filings = company.get_filings(form=['8-K', '8-K/A'], filing_date=f'{args.start}:{args.end}')
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    inventory = []
    for filing in filings:
        record = {
            'company': filing.company, 'cik': filing.cik, 'form': filing.form,
            'filing_date': str(filing.filing_date), 'accession': filing.accession_no,
            'sec_index_url': filing.homepage_url, 'items': [], 'press_releases': [],
        }
        try:
            report = filing.obj()
            record['sec_document_url'] = filing.filing_url
            record['report_text'] = report.text()
            for item in report.items:
                record['items'].append({'item': item, 'text': report[item]})
            if report.has_press_release:
                for index in range(len(report.press_releases)):
                    release = report.press_releases[index]
                    record['press_releases'].append({
                        'document': release.document, 'sec_url': release.url(),
                        'text': release.text(),
                    })
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
        records.append(record)
        inventory.append({
            'filing_date': record['filing_date'], 'accession': record['accession'],
            'form': record['form'], 'items': '; '.join(x['item'] for x in record['items']),
            'press_release_count': len(record['press_releases']),
            'sec_document_url': record.get('sec_document_url', ''),
            'error': record.get('error', ''),
        })
        print(f'{record["filing_date"]} {record["accession"]} {"error" if record.get("error") else "ok"}', flush=True)

    (args.out / 'sec_8k_sources.json').write_text(json.dumps(records, indent=2, default=str), encoding='utf-8')
    with (args.out / 'filing_inventory.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]) if inventory else [
            'filing_date', 'accession', 'form', 'items', 'press_release_count', 'sec_document_url', 'error'])
        writer.writeheader()
        writer.writerows(inventory)
    summary = {
        'company': company.name, 'start': args.start.isoformat(), 'end': args.end.isoformat(),
        'filings': len(records), 'successful': sum(not r.get('error') for r in records),
        'failures': [r['accession'] for r in records if r.get('error')],
        'scope': '8-K and 8-K/A by filing date; item text and detected press-release exhibits',
    }
    (args.out / 'retrieval_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    if summary['failures']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
