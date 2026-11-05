"""Builds src/data/reconciliation.json from the vendor_reconciliation outputs."""
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'vendor_reconciliation' / 'synthetic'
OUT = Path(__file__).resolve().parents[1] / 'src' / 'data' / 'reconciliation.json'

vendor_a = list(csv.DictReader(open(SRC / 'vendor_a.csv', encoding='utf-8')))
vendor_b = [json.loads(line) for line in open(SRC / 'vendor_b.jsonl', encoding='utf-8') if line.strip()]
issuer = {('A', r['VendorId']): r['IssuerName'] for r in vendor_a}
issuer.update({('B', r['id']): r['issuer_legal_name'] for r in vendor_b})

tickets = []
for i, r in enumerate(csv.DictReader(open(SRC / 'mismatches.csv', encoding='utf-8')), 1):
    name = issuer.get((r['vendor'], r['vendor_id']), '')
    tickets.append({
        'id': f"T-{i:03d}",
        'vendor': r['vendor'],
        'vendorId': r['vendor_id'],
        'issuer': name.title() if name.isupper() else name,
        'field': r['field'],
        'kind': r['kind'],
        'severity': r['severity'],
        'filingValue': r['filing_value'] or None,
        'vendorValue': r['vendor_value'] or None,
        'accession': r['evidence_accession'],
        'form': r['evidence_form'],
        'filed': r['evidence_filing_date'],
    })

summary = json.loads((SRC / 'evaluation_summary.json').read_text())
data = {
    'vendors': [
        {'id': 'A', 'name': 'Vendor A', 'format': 'CSV', 'records': len(vendor_a)},
        {'id': 'B', 'name': 'Vendor B', 'format': 'JSONL', 'records': len(vendor_b)},
    ],
    'totals': {'vendorRecords': summary['vendor_records'], 'matched': summary['matched']},
    'tickets': tickets,
}
OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
print(len(tickets), 'tickets;', data['totals'], OUT.stat().st_size // 1024, 'KB')
