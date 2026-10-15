"""Builds src/data/filings.json from the evaluation extraction outputs."""
import ast, json, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / 'notebooks' / 'evaluation'
OUT = Path(__file__).resolve().parents[1] / 'src' / 'data' / 'filings.json'

TENDER_FIELDS = ['bidder', 'parent', 'acquisition_subsidiary', 'dealer_manager', 'depositary', 'information_agent',
                 'security_description', 'ticker', 'cusip', 'isin', 'event_status', 'event_status_details',
                 'mandatory_voluntary_indicator', 'offer_price_type', 'offer_price', 'currency', 'offer_price_basis',
                 'offer_price_qualifications', 'expiration_date', 'withdrawal_deadline', 'settlement_date',
                 'effective_date', 'minimum_tender_condition', 'proration_terms', 'tendering_conditions',
                 'available_options', 'default_option', 'financial_terms', 'conditions_restrictions']
MERGER_FIELDS = ['acquirer', 'target', 'consideration_type', 'cash_consideration', 'stock_exchange_ratio',
                 'shareholder_vote_date', 'closing_conditions', 'event_status', 'security_description',
                 'effective_date', 'available_options', 'default_option', 'election_deadline']
PASSAGE_ALIAS = {'offer_price_currency': 'currency'}


def clean(v, cap=600):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = re.sub(r'\s+', ' ', str(v)).strip()
    if not s or s.lower() in ('nan', 'none', 'null'):
        return None
    return s if len(s) <= cap else s[:cap].rsplit(' ', 1)[0] + '…'


def norm(name):
    s = re.sub(r'[^a-z0-9 ]', '', (name or '').lower())
    s = re.sub(r'\b(inc|corp|corporation|llc|ltd|limited|co|company|holdings|plc|lp|the)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def passages(raw):
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        d = json.loads(raw)
    except Exception:
        try:
            d = ast.literal_eval(raw)
        except Exception:
            return {}
    out = {}
    for k, items in d.items():
        k = PASSAGE_ALIAS.get(k, k)
        quotes = []
        for it in sorted(items or [], key=lambda x: -x.get('relevance_score', 0))[:2]:
            q = clean(it.get('quote'), 700)
            if q:
                quotes.append({'quote': q, 'location': clean(it.get('location'), 140) or ''})
        if quotes:
            out[k] = quotes
    return out


def rows(df, action, fields, subject_col, counter_col, passage_col):
    res = []
    for _, r in df.iterrows():
        subject = clean(r.get(subject_col)) or clean(r.get('registrant_name'))
        counter = clean(r.get(counter_col))
        res.append({
            'id': r['accession_number'],
            'action': action,
            'form': r['form'],
            'filedDate': r['filing_date'],
            'subject': subject,
            'counterparty': counter,
            'registrant': clean(r.get('registrant_name')),
            'cik': str(r.get('registrant_cik')),
            'indexUrl': r.get('filing_index_url'),
            'docs': int(r.get('document_count') or 0),
            'sizeMb': float(r.get('text_size_mb') or 0),
            'eventKey': f"{action}:{norm(subject)}",
            'fields': {k: v for k in fields if (v := clean(r.get(k)))},
            'passages': passages(r.get(passage_col)),
        })
    return res


t = pd.read_csv(EVAL / 'tender_offers.csv')
m = pd.read_csv(EVAL / 'data' / 'merger_2026-01-01_2026-09-30' / 'mergers.csv')
t['subject_company'] = t['subject_company'].fillna(t['registrant_name'])
filings = rows(t, 'tender_offer', TENDER_FIELDS, 'subject_company', 'bidder', 'passage') + \
    rows(m, 'merger', MERGER_FIELDS, 'target', 'acquirer', 'passages')
# Merger rows keep both parties as fields; ensure the target is always present
for f in filings:
    if f['action'] == 'merger' and 'target' not in f['fields']:
        f['fields']['target'] = f['subject']
    if f['action'] == 'tender_offer':
        f['fields'].setdefault('bidder', f['counterparty'] or f['subject'])
        f['fields']['subject_company'] = f['subject']

# One record per accession number (a few filings were extracted twice)
seen = set()
filings = [f for f in filings if not ((f['id'], f['eventKey']) in seen or seen.add((f['id'], f['eventKey'])))]
counts = {}
for f in filings:
    f['accession'] = f['id']
    counts[f['id']] = counts.get(f['id'], 0) + 1
    if counts[f['id']] > 1:
        f['id'] = f"{f['accession']}_{counts[f['accession']]}"

# Order within each event and mark the latest few filings as "incoming" for the live-fetch walkthrough
filings.sort(key=lambda f: (f['filedDate'], f['id']))
by_event = {}
for f in filings:
    by_event.setdefault(f['eventKey'], []).append(f)
latest_follow_ups = sorted([v[-1] for v in by_event.values() if len(v) > 1], key=lambda f: f['filedDate'])[-4:]
singles = sorted([v[0] for v in by_event.values() if len(v) == 1], key=lambda f: f['filedDate'])
incoming = {f['id'] for f in latest_follow_ups}
for action, n in (('tender_offer', 5), ('merger', 5)):
    incoming |= {f['id'] for f in [s for s in singles if s['action'] == action][-n:]}
for f in filings:
    f['incoming'] = f['id'] in incoming

OUT.write_text(json.dumps(filings, ensure_ascii=False, separators=(',', ':')))
print(len(filings), 'filings;', len(by_event), 'events;', len(incoming), 'incoming;', OUT.stat().st_size // 1024, 'KB')
