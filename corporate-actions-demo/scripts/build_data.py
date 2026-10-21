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

# One record per accession number (co-registrants and multi-instrument filings were extracted several times)
seen = set()
filings = [f for f in filings if not (f['id'] in seen or seen.add(f['id']))]
for f in filings:
    f['accession'] = f['id']

# ---------------------------------------------------------------- Linking evidence
FILE_NUMBERS = json.loads((Path(__file__).resolve().parent / 'cache' / 'file_numbers.json').read_text())
AGREEMENT = re.compile(
    r"(?P<sent>[^.]{0,160}?\b(?:Agreement and Plan of (?:Merger|Reorganization)|Merger Agreement|Business Combination Agreement|Plan of Merger)\b[^.]{0,60}?"
    r"(?:dated|entered into)(?: as of| on)?,? (?P<date>(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, ?\d{4})[^.]{0,200})")
FILENO_CITE = re.compile(r"(?<!\d)(333-\d{5,6}|001-\d{5,6}|000-\d{5,6}|005-\d{5})(?!\d)")
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']


def iso(d):
    m = re.match(r'([A-Za-z]+) (\d{1,2}), ?(\d{4})', d)
    return f"{m.group(3)}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"


def filing_text(f):
    folder = 'merger_2026-01-01_2026-09-30' if f['action'] == 'merger' else 'tender_offer_2026-01-01_2026-09-30'
    p = EVAL / 'data' / folder / 'input_text' / f"{f['accession']}.txt"
    return p.read_text(errors='ignore') if p.exists() else ''


for f in filings:
    f['fileNo'] = FILE_NUMBERS.get(f['accession'])
    t = filing_text(f)
    f['agreement'] = None
    f['cites'] = []
    if f['action'] == 'merger' and t:
        m = AGREEMENT.search(t[:400000])
        if m:
            f['agreement'] = {'date': iso(m.group('date')), 'quote': clean(m.group('sent'), 420)}
    if t:
        f['cites'] = sorted(set(FILENO_CITE.findall(t[:300000])) - {f['fileNo']})
    f['_acq'] = norm(f['fields'].get('acquirer') or f['fields'].get('bidder') or '')
    f['_tgt'] = norm(f['fields'].get('target') or f['fields'].get('subject_company') or f['subject'])

FORM_ORDER = {'425': 0, '8-K': 0, 'PREM14A': 1, 'S-4': 1, 'SC 13E3': 1, 'S-4/A': 2, 'SC 13E3/A': 2, 'DEFM14A': 3,
              'SC TO-I': 1, 'SC TO-T': 1, 'SC 14D9': 2, 'SC TO-I/A': 2, 'SC TO-T/A': 2, 'SC 14D9/A': 2}


def signals(a, b):
    """Evidence that filing b belongs to the same event as filing a."""
    sig = []
    # 333- (registration statement) and 005- (tender offer / going-private) numbers are deal-specific.
    # 001-/000- numbers belong to the company and are shared by all of its 8-Ks, proxies and reports.
    same_no = bool(a['fileNo'] and a['fileNo'] == b['fileNo'] and a['fileNo'][:3] in ('333', '005'))
    sig.append({'id': 'file_no', 'label': 'Same SEC file number', 'ok': same_no, 'strong': True,
                'detail': f"{a['form']}: {a['fileNo'] or 'n/a'} · {b['form']}: {b['fileNo'] or 'n/a'}" + ('' if same_no else ' (different registrants filed these)' if a['fileNo'] and b['fileNo'] else '')})
    cross = [n for n in (a['fileNo'], b['fileNo']) if n and (n in b['cites'] or n in a['cites'])]
    sig.append({'id': 'cross_ref', 'label': 'One filing cites the other\'s file number', 'ok': bool(cross), 'strong': True,
                'detail': f"Cited in text: {', '.join(cross)}" if cross else 'No file-number citation found in either filing text'})
    ag_ok = bool(a['agreement'] and b['agreement'] and a['agreement']['date'] == b['agreement']['date'])
    sig.append({'id': 'agreement', 'label': 'Same merger agreement (date)', 'ok': ag_ok,
                'detail': (f"Both filings reference the agreement dated {a['agreement']['date']}" if ag_ok else
                           'Merger agreement date not found in one or both filings'),
                'quotes': [{'source': f"{x['form']} · {x['accession']}", 'quote': x['agreement']['quote']} for x in (a, b) if x['agreement']] if ag_ok else []})
    acq_ok = bool(a['_acq'] and a['_acq'] == b['_acq'])
    tgt_ok = bool(a['_tgt'] and a['_tgt'] == b['_tgt'])
    ra = a['fields'].get('acquirer') or a['fields'].get('bidder') or '—'
    rb = b['fields'].get('acquirer') or b['fields'].get('bidder') or '—'
    sig.append({'id': 'parties', 'label': 'Same acquirer and target (extracted)', 'ok': acq_ok and tgt_ok,
                'detail': f"Acquirer: {ra.rstrip('.')} → {rb.rstrip('.')} · Target: {a['subject'].rstrip('.')} → {b['subject'].rstrip('.')}"})
    order_ok = FORM_ORDER.get(b['form'], 1) >= FORM_ORDER.get(a['form'], 1) and b['filedDate'] >= a['filedDate']
    sig.append({'id': 'sequence', 'label': 'Filing sequence is consistent', 'ok': order_ok,
                'detail': f"{a['form']} ({a['filedDate']}) → {b['form']} ({b['filedDate']})"})
    strong = same_no or bool(cross)
    if a['action'] == 'tender_offer':
        rule = 'Same SEC file number' if same_no else None
        conf = 'High' if same_no else None
    elif strong:
        rule, conf = 'SEC file-number match or citation', 'High'
    elif ag_ok and acq_ok and tgt_ok:
        rule, conf = 'Same merger agreement + same acquirer and target', 'High'
    elif ag_ok and (acq_ok or tgt_ok):
        rule, conf = 'Same merger agreement + one matching party', 'Medium'
    else:
        rule, conf = None, None
    return sig, rule, conf


# Union-find over filings; a link needs a rule (name equality alone is never enough)
parent = {f['accession']: f['accession'] for f in filings}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


filings.sort(key=lambda f: (f['filedDate'], f['accession']))
for i, b in enumerate(filings):
    for a in filings[:i]:
        if a['action'] != b['action']:
            continue
        if signals(a, b)[1]:
            parent[find(b['accession'])] = find(a['accession'])

groups = {}
for f in filings:
    groups.setdefault(find(f['accession']), []).append(f)
for members in groups.values():
    anchor = members[0]
    for f in members:
        f['eventKey'] = f"{f['action']}:{anchor['accession']}"
        f['link'] = None
        if f is not anchor:
            sig, rule, conf = signals(anchor, f)
            if not rule:  # joined through a chain of other filings
                prev = members[members.index(f) - 1]
                sig, rule, conf = signals(prev, f)
                anchor_ref = prev
            else:
                anchor_ref = anchor
            f['link'] = {'to': anchor_ref['accession'], 'toForm': anchor_ref['form'], 'toDate': anchor_ref['filedDate'],
                         'rule': rule, 'confidence': conf, 'signals': sig}
for f in filings:
    for k in ('_acq', '_tgt'):
        f.pop(k, None)

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
