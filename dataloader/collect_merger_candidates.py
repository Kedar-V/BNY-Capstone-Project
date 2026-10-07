#!/usr/bin/env python3
"""Rebuild a local SEC merger-candidate dataset from filing dates.

Uses EdgarTools for EDGAR full-text search and downloads source documents from
SEC URLs. The keyword screen is not a verified merger-event label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from edgar import search_filings, set_identity


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from eda.sec_client import SecClient  # noqa: E402


DEFAULT_FORMS = ('8-K', '8-K/A', '6-K', '6-K/A', 'DEFM14A', 'DEFS14A')
EVIDENCE_PATTERNS = {
    'merger_agreement_signed': re.compile(r'\b(?:entered into|executed|signed)\b.{0,180}?\b(?:agreement and plan of merger|merger agreement)\b', re.I),
    'merger_completed': re.compile(r'\b(?:completed|consummated)\s+(?:the\s+|its\s+|a\s+|previously announced\s+|proposed\s+){0,4}merger\b|\bmerger\s+(?:was\s+|has been\s+|had been\s+)(?:completed|consummated)\b', re.I),
    'merger_agreement_terminated': re.compile(r'\bterminated\s+(?:the|its)\s+(?:previously announced\s+)?(?:agreement and plan of merger|merger agreement)\b|\bmerger agreement\s+(?:was|has been)\s+terminated\b', re.I),
}
MANIFEST_FIELDS = ('archive_path', 'accession_number', 'filing_date', 'form', 'document_type',
                   'reporting_filer', 'cik', 'sec_source_url', 'text_characters', 'raw_sha256', 'retrieval_error')


def dump_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def search_month(start: str, end: str, forms: tuple[str, ...], cache: Path) -> list[dict]:
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))
    page = search_filings('merger', forms=list(forms), start_date=start, end_date=end, limit=100)
    if page.total >= 10000:
        raise ValueError(f'{start}:{end} has {page.total} hits; use a narrower date range')
    expected = page.total
    rows: list[dict] = []
    while page is not None:
        rows.extend(asdict(item) for item in page)
        page = page.next()
    if len(rows) != expected:
        raise RuntimeError(f'Incomplete search for {start}:{end}: {len(rows)}/{expected}')
    dump_json(cache, rows)
    return rows


def choose_documents(hits: list[dict], forms: tuple[str, ...], max_per_month: int | None) -> list[dict]:
    by_accession: dict[str, tuple[int, dict]] = {}
    for hit in hits:
        if not hit.get('cik') or not hit.get('document_id'):
            continue
        file_type = hit.get('file_type') or ''
        if file_type == hit.get('form'):
            rank = 0
        elif file_type.startswith('EX-99'):
            rank = 1
        else:
            continue
        accession = hit['accession_number']
        previous = by_accession.get(accession)
        if previous is None or rank < previous[0] or (rank == previous[0] and hit.get('score', 0) > previous[1].get('score', 0)):
            by_accession[accession] = rank, hit
    candidates = [value[1] for value in by_accession.values()]
    candidates.sort(key=lambda r: (-r.get('score', 0), r['accession_number']))
    if max_per_month is not None:
        candidates = candidates[:max_per_month]
    return candidates


def evidence_from_text(text: str) -> list[dict]:
    evidence = []
    for kind, pattern in EVIDENCE_PATTERNS.items():
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 180):match.start()]
            if re.search(r'\b(?:if|unless|may|could|would|will|shall)\b[^.;]{0,70}$', before, re.I):
                continue
            lo, hi = max(0, match.start() - 260), min(len(text), match.end() + 650)
            evidence.append({'event_type': kind, 'excerpt': text[lo:hi], 'match': match.group()})
    return evidence


def download_one(hit: dict, client: SecClient, out: Path) -> tuple[dict, bool]:
    accession = hit['accession_number']
    cik = str(hit['cik'])
    filename = hit['document_id']
    url = client.document_url(cik, accession, filename)
    stem = hashlib.sha256(url.encode()).hexdigest()[:24]
    raw_path = out / 'raw' / f'{stem}.html'
    doc_path = out / 'documents' / f'{stem}.json'
    archive_path = f'documents/{stem}.json'
    row = dict(archive_path=archive_path, accession_number=accession,
               filing_date=hit['filed'], form=hit['form'],
               document_type=hit.get('file_type') or '',
               reporting_filer=hit.get('company') or '', cik=cik,
               sec_source_url=url, text_characters=0, raw_sha256='', retrieval_error='')
    if doc_path.exists() and raw_path.exists():
        doc = json.loads(doc_path.read_text(encoding='utf-8'))
        if doc.get('text') and not doc.get('error'):
            row['text_characters'] = len(doc['text'])
            row['raw_sha256'] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            return row, True
    try:
        raw = client.get_bytes(url)
        if not raw:
            raise ValueError('Empty SEC response')
        raw_path.write_bytes(raw)
        soup = BeautifulSoup(raw, 'lxml')
        for tag in soup(['script', 'style', 'ix:header']):
            tag.decompose()
        text = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True))
        if not text:
            raise ValueError('No readable text')
        evidence = evidence_from_text(text)
        doc = {'metadata': hit, 'source_url': url, 'text': text, 'evidence': evidence,
               'screen_status': 'merger_event_language_found' if evidence else 'needs_review_no_event_pattern'}
        dump_json(doc_path, doc)
        row['text_characters'] = len(text)
        row['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        return row, True
    except Exception as exc:
        row['retrieval_error'] = f'{type(exc).__name__}: {exc}'
        return row, False


def collect(start: date, end: date, forms: tuple[str, ...], max_per_month: int | None, out: Path, identity: str) -> dict:
    set_identity(identity)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'documents').mkdir(exist_ok=True)
    (out / 'raw').mkdir(exist_ok=True)
    client = SecClient(user_agent=identity)
    selected: dict[str, dict] = {}
    hit_count = 0
    for month_start, month_end in client.iter_month_windows(start.isoformat(), end.isoformat()):
        hits = search_month(month_start, month_end, forms, out / f'search_{month_start[:7]}.json')
        hit_count += len(hits)
        picks = choose_documents(hits, forms, max_per_month)
        for item in picks:
            selected.setdefault(item['accession_number'], item)
        print(f'{month_start[:7]}: {len(hits)} hits, {len(picks)} selected', flush=True)
    manifest, failures = [], []
    for index, hit in enumerate(selected.values(), 1):
        row, ok = download_one(hit, client, out)
        (manifest if ok else failures).append(row)
        if index % 25 == 0 or index == len(selected):
            print(f'Downloaded {index}/{len(selected)}; failures {len(failures)}', flush=True)
    write_csv(out / 'manifest.csv', manifest, MANIFEST_FIELDS)
    write_csv(out / 'failures.csv', failures, MANIFEST_FIELDS)
    archive = out / 'candidate_documents.zip'
    temp = archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as stream:
        stream.write(out / 'manifest.csv', 'manifest.csv')
        stream.write(out / 'failures.csv', 'failures.csv')
        for row in manifest:
            stream.write(out / row['archive_path'], row['archive_path'])
    temp.replace(archive)
    summary = {'start': start.isoformat(), 'end': end.isoformat(), 'forms': list(forms),
               'query': 'merger', 'search_hits': hit_count, 'selected_filings': len(selected),
               'downloaded_documents': len(manifest), 'failures': len(failures),
               'by_form': dict(Counter(row['form'] for row in manifest)),
               'note': 'Keyword-selected filings are candidates, not confirmed merger events or unique deals.'}
    dump_json(out / 'summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--forms', default=','.join(DEFAULT_FORMS), help='Comma-separated SEC form types')
    parser.add_argument('--per-month', type=int, default=3, help='Maximum filing documents per month; default 3')
    parser.add_argument('--all', action='store_true', help='Download every eligible search result, which can be large')
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error('--end must be on or after --start')
    if args.per_month <= 0:
        parser.error('--per-month must be positive')
    identity = os.environ.get('EDGAR_IDENTITY', '').strip()
    if not identity:
        parser.error('Set EDGAR_IDENTITY to your name and contact email before SEC requests')
    forms = tuple(form.strip() for form in args.forms.split(',') if form.strip())
    if not forms:
        parser.error('--forms cannot be empty')
    out = args.out or PROJECT / 'data' / 'mergers' / f'sec_{args.start}_{args.end}'
    print(json.dumps(collect(args.start, args.end, forms, None if args.all else args.per_month, out, identity), indent=2))


if __name__ == '__main__':
    main()
