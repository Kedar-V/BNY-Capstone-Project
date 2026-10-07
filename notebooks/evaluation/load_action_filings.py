"""Download SEC filings for an action and return their text in a pandas table.

Set SEC_USER_AGENT to your name/project and contact email before running.
Example from the repository root:
    python notebooks/evaluation/load_action_filings.py --action exchange_offer --start 2023-07-01 --end 2023-08-31

Forms are listed in corporate_actions.json. Files are saved in evaluation/data/.
This script prepares text; it does not call an LLM.
"""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse, parse_qs

import warnings

import pandas as pd
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'dataloader'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(HERE))

import config
from download_samples import diversify
from eda.sec_client import SecClient
from eda.corpus import hit_to_record

ACTIONS = json.loads((HERE / 'corporate_actions.json').read_text())


def cached_bytes(client, url, path):
    """Download once, then reuse the saved file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(client.get_bytes(url))
    return path.read_bytes()


def extract_text(raw):
    """Remove hidden HTML content; keep paragraphs and table rows readable."""
    soup = BeautifulSoup(raw, 'lxml')
    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        name = tag.name.lower()
        style = re.sub(r'\s+', '', tag.get('style', '')).lower()
        if (name in {'script', 'style', 'noscript', 'ix:header', 'ix:hidden'}
                or tag.has_attr('hidden') or 'display:none' in style or 'visibility:hidden' in style):
            tag.decompose()
    # Convert inner tables first so their text is not repeated.
    for table in list(soup.find_all('table')):
        if table.find('table'):
            continue
        rows = []
        for tr in table.find_all('tr'):
            cells = [' '.join(c.stripped_strings) for c in tr.find_all(['td', 'th'], recursive=False)]
            if any(cells):
                rows.append('\t'.join(cells))
        table.replace_with('\n[TABLE]\n' + '\n'.join(rows) + '\n[/TABLE]\n')
    for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'br']):
        tag.insert_before('\n')
        if tag.name != 'br':
            tag.insert_after('\n')
    text = soup.get_text('')
    lines = [re.sub(r'[^\S\t\n]+', ' ', line).strip() for line in text.splitlines()]
    return '\n'.join(line for line in lines if line)


def discover(client, spec, forms, start, end, cap, output):
    """Search SEC by forms, keywords and dates; save results and search limits."""
    records, counts = [], []
    for form in sorted({f.removesuffix('/A') for f in forms}):
        # Optional per-form query, or a list of queries searched separately and merged (EDGAR full-text
        # search does not group "A B" OR "C D"). Default: the action's query.
        queries = spec.get('form_queries', {}).get(form, spec['query'])
        for query in [queries] if isinstance(queries, str) else queries:
            offset, total, relation = 0, 0, 'eq'
            while cap is None or offset < cap:
                page_size = 100 if cap is None else min(100, cap - offset)
                params = dict(q=query, forms=form, dateRange='custom', startdt=start,
                              enddt=end, **{'from': offset, 'size': page_size})
                key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
                path = output / 'search' / f'{key}.json'
                if path.exists():
                    payload = json.loads(path.read_text())
                else:
                    payload = client.efts_search(params)
                    if 'hits' not in payload:
                        raise ValueError(f'Invalid search response for {form}')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload))
                hits = payload['hits']
                reported = hits.get('total', 0)
                total = reported.get('value', 0) if isinstance(reported, dict) else reported
                relation = reported.get('relation', 'eq') if isinstance(reported, dict) else 'eq'
                remaining = None if cap is None else cap - offset
                batch = hits.get('hits', []) if remaining is None else hits.get('hits', [])[:remaining]
                records.extend(hit_to_record(hit) for hit in batch)
                offset += len(batch)
                if not batch or (relation == 'eq' and offset >= total):
                    break
            counts.append(dict(form=form, query=query, loaded_hits=offset, reported_hits=total,
                               total_relation=relation,
                               truncated=(cap is not None and offset < total) or relation != 'eq'))
    pd.DataFrame(counts).to_csv(output / 'search_counts.csv', index=False)
    # a document found by several queries is listed once
    frame = pd.DataFrame(records)
    return frame.drop_duplicates("hit_id").reset_index(drop=True) if "hit_id" in frame else frame


def index_documents(raw, index_url):
    """Read document names, types and links from a filing page."""
    soup = BeautifulSoup(raw, 'lxml')
    docs = []
    for table in soup.select('table.tableFile'):
        if 'Document Format Files' not in table.get('summary', ''):
            continue
        for tr in table.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 4 or not cells[2].find('a'):
                continue
            a = cells[2].find('a')
            url = urljoin(index_url, a.get('href', ''))
            if 'doc' in parse_qs(urlparse(url).query):
                url = urljoin('https://www.sec.gov', parse_qs(urlparse(url).query)['doc'][0])
            docs.append(dict(filename=a.get_text(strip=True), document_type=cells[3].get_text(strip=True),
                             description=cells[1].get_text(' ', strip=True), url=url))
    return docs


def load_action(action, start, end, n=None, include_supporting=True, include_conditional=False,
                max_hits_per_form=None, metadata_path=None, output_dir=None, user_agent=None, client=None):
    """Return a DataFrame with one row per filing; use its "text" column for the LLM.

    Choose action and start/end filing dates (YYYY-MM-DD). When n is omitted,
    every matching filing is loaded. Pass n to select a smaller diversified sample.
    Each row includes filing/event IDs, SEC form and registrant metadata, source URL,
    document count, text size, content hash, processing status, and extracted text.
    event_id starts as action_accession-number; assign the same ID to related filings
    during review when they represent one corporate-action event.
    Supporting forms are included; conditional forms are optional.
    metadata_path can supply a saved filing list instead of a new SEC search.
    Review results: a matching form or keyword does not confirm the action.
    Attached exhibits are included, but references to other filings are not followed.
    """
    if action not in ACTIONS:
        raise ValueError(f'Choose an action from {list(ACTIONS)}')
    invalid_n = n is not None and n < 1
    invalid_cap = max_hits_per_form is not None and not 1 <= max_hits_per_form <= 10000
    if date.fromisoformat(start) > date.fromisoformat(end) or invalid_n or invalid_cap:
        raise ValueError('Start must be on/before end; n must be at least 1 when set; max_hits_per_form must be 1–10000 when set')
    if client is None:
        identity = user_agent or os.getenv('SEC_USER_AGENT')
        if not identity:
            raise ValueError('Set SEC_USER_AGENT to your project/name and contact email')
        client = SecClient(user_agent=identity)
    spec = ACTIONS[action]
    forms = spec['primary'] + (spec['supporting'] if include_supporting else []) + (spec['conditional'] if include_conditional else [])
    output = Path(output_dir or HERE / 'data' / f'{action}_{start}_{end}').resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Use a saved filing list, or search SEC.
    if metadata_path:
        path = Path(metadata_path)
        pool = pd.read_parquet(path) if path.suffix == '.parquet' else pd.read_csv(path, dtype={'primary_cik': str})
    else:
        pool = discover(client, spec, forms, start, end, max_hits_per_form, output)
    results, manifest = [], []
    if not pool.empty:
        pool = pool[pool['form'].isin(forms)].dropna(subset=['accession', 'primary_cik', 'file_date']).copy()
        dates = pd.to_datetime(pool['file_date'], errors='coerce')
        pool = pool[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
        pool['year'] = pd.to_datetime(pool['file_date']).dt.year
        pool['entity_key'] = pool['primary_cik'].astype(str)
        pool = pool.sort_values('file_date').drop_duplicates('accession', keep='first')
        if n is not None:
            pool = diversify(pool, n)
    pool.to_csv(output / 'selected_filings.csv', index=False)
    # Download each filing and its attached exhibits.
    for row in pool.to_dict('records'):
        acc, cik = str(row['accession']), str(int(row['primary_cik']))
        folder = output / 'documents' / acc
        index_url = client.document_url(cik, acc, f'{acc}-index.html')
        base = dict(action=action, accession_number=acc, form=row['form'], filing_date=str(row['file_date']),
                    registrant_cik=cik.zfill(10), registrant_name=row.get('entity_name'),
                    filing_index_url=index_url, relevance='candidate_not_verified')
        chunks, errors = [], []
        try:
            raw = cached_bytes(client, index_url, folder / 'index.html')
            documents = index_documents(raw, index_url)
            if not any(d['document_type'] == row['form'] for d in documents):
                errors.append('Main document not found on the filing page')
            for doc in documents:
                primary = doc['document_type'] == row['form']
                # Skip machine-readable XBRL attachments; keep other exhibits.
                exhibit = doc['document_type'].startswith('EX-') and not doc['document_type'].startswith(('EX-101', 'EX-104'))
                selected = primary or exhibit
                info = {**base, **doc, 'role': 'primary' if primary else 'exhibit' if exhibit else 'other',
                        'status': 'excluded', 'error': '', 'raw_path': '', 'text_path': '', 'content_hash': ''}
                if selected:
                    try:
                        if urlparse(doc['url']).hostname != 'www.sec.gov' or not urlparse(doc['url']).path.startswith('/Archives/'):
                            raise ValueError('Not an SEC Archives document URL')
                        path = folder / Path(doc['filename']).name
                        data = cached_bytes(client, doc['url'], path)
                        info['raw_path'] = str(path)
                        info['content_hash'] = hashlib.sha256(data).hexdigest()
                        if path.suffix.lower() not in {'.htm', '.html', '.txt'}:
                            raise ValueError('Saved raw document; text extraction unsupported for this format')
                        text = extract_text(data) if path.suffix.lower() != '.txt' else data.decode('utf-8', errors='replace')
                        if not text.strip():
                            raise ValueError('No text extracted')
                        text_path = path.with_name(path.name + '.txt')
                        text_path.write_text(text)
                        info.update(status='ok', text_path=str(text_path))
                        chunks.append(f"=== DOCUMENT {doc['filename']} | {doc['document_type']} | {doc['url']} ===\n{text}")
                    except Exception as exc:
                        info.update(status='failed', error=str(exc))
                        errors.append(f"{doc['filename']}: {exc}")
                manifest.append(info)
        except Exception as exc:
            errors.append(f'Could not read the filing page: {exc}')
            manifest.append({**base, 'status': 'failed', 'role': 'index', 'error': str(exc)})
        text = '\n\n'.join(chunks)
        input_path = output / 'input_text' / f'{acc}.txt'
        input_path.parent.mkdir(exist_ok=True)
        input_path.write_text(text)
        text_bytes = text.encode('utf-8')
        results.append({**base, 'filing_id': acc, 'event_id': f'{action}_{acc}',
                        'text': text, 'input_text_path': str(input_path),
                        'input_hash': hashlib.sha256(text_bytes).hexdigest(),
                        'document_count': len(chunks), 'text_char_count': len(text),
                        'text_byte_count': len(text_bytes),
                        'text_size_mb': round(len(text_bytes) / 1_000_000, 3),
                        'status': 'failed' if not chunks else 'partial' if errors else 'ok',
                        'input_coverage': 'selected filing and attached exhibits only; incorporated references not followed',
                        'error': ' | '.join(errors)})
        # Save progress after each filing.
        pd.DataFrame(manifest).to_csv(output / 'documents.csv', index=False)
        pd.DataFrame(results).to_json(output / 'filings.jsonl', orient='records', lines=True, force_ascii=False)
        print(acc, results[-1]['status'], len(chunks), 'documents', flush=True)
    frame = pd.DataFrame(results, columns=list(results[0]) if results else ['action', 'accession_number', 'form', 'filing_date', 'text', 'status'])
    pd.DataFrame(manifest, columns=list(manifest[0]) if manifest else ['accession_number', 'filename', 'document_type', 'role', 'status', 'error']).to_csv(output / 'documents.csv', index=False)
    frame.to_json(output / 'filings.jsonl', orient='records', lines=True, force_ascii=False)
    frame.drop(columns='text').to_csv(output / 'filings.csv', index=False)
    (output / 'run.json').write_text(json.dumps(dict(action=action, start=start, end=end, n=n,
        forms=forms, query=spec['query'] if not metadata_path else None, metadata_path=str(metadata_path),
        max_hits_per_form=max_hits_per_form, selected_filings=len(frame)), indent=2))
    return frame


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=ACTIONS, required=True, help='Corporate action to load')
    parser.add_argument('--start', default=config.START, help='First filing date: YYYY-MM-DD (default: config.START)')
    parser.add_argument('--end', default=config.END, help='Last filing date: YYYY-MM-DD (default: config.END)')
    parser.add_argument('--n', type=int, help='Optional maximum filings; omit to load all matches')
    parser.add_argument('--primary-only', action='store_true', help='Search primary forms only')
    parser.add_argument('--include-conditional', action='store_true', help='Also search conditional forms from the configuration')
    parser.add_argument('--max-hits-per-form', type=int, help='Optional SEC search-result cap per base form')
    parser.add_argument('--metadata-path', type=Path, help='Optional saved filing list (.parquet or .csv)')
    parser.add_argument('--output-dir', type=Path, help='Optional folder for downloads and text')
    args = parser.parse_args()
    load_action(args.action, args.start, args.end, args.n, not args.primary_only,
                args.include_conditional, args.max_hits_per_form, args.metadata_path, args.output_dir)
