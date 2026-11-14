"""Builds src/data/amendments.json from the amendment impact agent's queue.

    python -m agents.amendment_impact.agent          # from the repository root, refreshes the queue first
    python corporate-actions-demo/scripts/build_amendments.py

Every assessed filing is included, so the demo shows the agent's real output. Long extracted text is clipped.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'agents' / 'amendment_impact' / 'output' / 'amendment_queue.json'
OUT = Path(__file__).resolve().parents[1] / 'src' / 'data' / 'amendments.json'
# Hand-labelled sector of the company holders own, for the operations sector filter (see the file's _note)
SECTORS = json.loads((Path(__file__).resolve().parent / 'sectors.json').read_text(encoding='utf-8'))['sectors']


def clip(text, limit=420):
    if not text or len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0] + '…'


queue = json.loads(SRC.read_text(encoding='utf-8'))
items = []
for i, r in enumerate(sorted(queue['amendments'], key=lambda r: (r['filed'], r['accession'])), 1):
    items.append({
        'id': f"A-{i:03d}",
        'eventId': r['event_id'],
        'action': r['action'],
        'sector': SECTORS.get(r['event_id'], 'Unclassified'),
        'title': r['title'],
        'accession': r['accession'],
        'form': r['form'],
        'filed': r['filed'],
        'url': r['url'],
        'version': r['version'] + 1,
        'tier': r['tier'],
        'why': r['why'],
        'review': r['review'],
        'changes': [{
            'field': c['field'], 'kind': c['kind'], 'previous': clip(c['previous']), 'current': clip(c['current']),
            'tier': c['tier'], 'reason': clip(c['reason'], 300), 'quote': clip(c['quote'], 600), 'location': c['location'],
            'decidedBy': c.get('decided_by', 'rules'),
        } for c in r['changes']],
        'restated': r['restated'],
        'holders': [{'client': h['client'], 'ticker': h['ticker'], 'shares': h['shares'], 'watchOnly': h['watch_only']}
                    for h in r['holders']],
        'notice': r['notice'] and {
            'subject': r['notice']['subject'],
            'lines': [clip(x, 500) for x in r['notice']['lines']],
            'source': r['notice']['source'],
            'recipients': r['notice']['recipients'],
            'watchers': r['notice']['watchers'],
        },
        'trace': r['trace'],
    })

text_changes = [c for r in items for c in r['changes'] if c['kind'] == 'text' and c['previous']]
data = {
    'summary': {
        **{k: queue['summary'][k] for k in ('amendments', 'by_tier', 'by_action', 'held_for_review', 'review_reasons')},
        'events': len({r['eventId'] for r in items}),
        'textChanges': len(text_changes),
        # Decided by the LLM; unsure answers and made-up quotes went to a person instead
        'llmJudged': sum(c['decidedBy'] == 'llm' and c['tier'] != 'needs_review' for c in text_changes),
        'llmMaterial': sum(c['decidedBy'] == 'llm' and c['tier'] == 'action' for c in text_changes),
        'notices': sum(r['notice'] is not None for r in items),
        'reachingClients': sum(bool(r['notice'] and r['notice']['recipients']) for r in items),
    },
    'items': items,
}
OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(len(items), 'amendments;', dict(Counter(r['tier'] for r in items)), f"{OUT.stat().st_size // 1024} KB")
