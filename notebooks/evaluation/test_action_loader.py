import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_action_filings import extract_text, load_action


def test_visible_text_and_tables():
    text = extract_text(b'<html><body><ix:header>hidden metadata</ix:header><p>Offer <b>expires</b> tomorrow.</p><div style="display: none">secret</div><table><tr><th>Series</th><th>Ratio</th></tr><tr><td>A</td><td>0.62</td></tr></table></body></html>')
    assert 'hidden metadata' not in text and 'secret' not in text
    assert 'Offer expires tomorrow.' in text
    assert 'Series\tRatio' in text and 'A\t0.62' in text


class Client:
    def __init__(self): self.calls = []
    def document_url(self, cik, accession, filename):
        return f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{filename}'
    def get_bytes(self, url):
        self.calls.append(url)
        if url.endswith('-index.html'):
            return b'''<table class="tableFile" summary="Document Format Files">
            <tr><td>1</td><td>Main</td><td><a href="main.htm">main.htm</a></td><td>SC TO-I</td></tr>
            <tr><td>2</td><td>Offer</td><td><a href="offer.htm">offer.htm</a></td><td>EX-99.1</td></tr>
            <tr><td>3</td><td>Contract</td><td><a href="contract.pdf">contract.pdf</a></td><td>EX-10</td></tr>
            </table>'''
        if url.endswith('.pdf'): return b'%PDF-unsupported'
        return b'<p>Exchange offer: 0.62 shares for each warrant.</p>'


def test_bundle_cache_and_partial_coverage(tmp_path):
    path = tmp_path / 'metadata.csv'
    pd.DataFrame([dict(accession='0000000001-23-000001', primary_cik='1', form='SC TO-I',
                      file_date='2023-07-24', entity_name='Example')]).to_csv(path, index=False)
    client = Client()
    kwargs = dict(action='exchange_offer', start='2023-01-01', end='2023-12-31', n=1,
                  metadata_path=path, output_dir=tmp_path/'out', client=client)
    result = load_action(**kwargs)
    assert result.iloc[0]['status'] == 'partial'
    assert result.iloc[0]['document_count'] == 2
    assert result.iloc[0]['filing_id'] == result.iloc[0]['accession_number']
    assert result.iloc[0]['event_id'] == 'exchange_offer_0000000001-23-000001'
    assert result.iloc[0]['text_char_count'] == len(result.iloc[0]['text'])
    assert result.iloc[0]['text_byte_count'] == len(result.iloc[0]['text'].encode('utf-8'))
    assert result.iloc[0]['text_size_mb'] == round(result.iloc[0]['text_byte_count'] / 1_000_000, 3)
    assert result.iloc[0]['form'] == 'SC TO-I'
    assert result.iloc[0]['registrant_name'] == 'Example'
    assert result.iloc[0]['filing_index_url'].endswith('0000000001-23-000001-index.html')
    assert 'main.htm' in result.iloc[0]['text'] and 'offer.htm' in result.iloc[0]['text']
    assert 'unsupported' in result.iloc[0]['error']
    first = len(client.calls)
    again = load_action(**kwargs)
    assert len(client.calls) == first
    assert again.iloc[0]['input_hash'] == result.iloc[0]['input_hash']


def test_omitting_n_loads_every_metadata_row(tmp_path):
    path = tmp_path / 'metadata.csv'
    pd.DataFrame([
        dict(accession='0000000001-23-000001', primary_cik='1', form='SC TO-I',
             file_date='2023-07-24', entity_name='Example One'),
        dict(accession='0000000002-23-000002', primary_cik='2', form='SC TO-I',
             file_date='2023-07-25', entity_name='Example Two'),
    ]).to_csv(path, index=False)
    result = load_action(
        action='exchange_offer', start='2023-01-01', end='2023-12-31',
        metadata_path=path, output_dir=tmp_path/'all', client=Client(),
    )
    assert len(result) == 2
    assert set(result['registrant_name']) == {'Example One', 'Example Two'}


def test_discovery_pagination_and_cache(tmp_path):
    from load_action_filings import discover
    class SearchClient:
        def __init__(self): self.calls = []
        def efts_search(self, params):
            self.calls.append(params)
            start = params['from']
            size = min(params['size'], 105-start)
            return {'hits': {'total': {'value': 105, 'relation': 'eq'}, 'hits': [
                {'_id': f'acc{i}:main.htm', '_source': {'adsh': f'acc{i}', 'form': 'S-4',
                 'file_type': 'S-4', 'file_date': '2023-07-24', 'ciks': ['1']}}
                for i in range(start, start+size)]}}
    client = SearchClient()
    frame = discover(client, {'query': 'exchange'}, ['S-4', 'S-4/A'], '2023-01-01', '2023-12-31', 103, tmp_path)
    assert len(frame) == 103
    assert [c['size'] for c in client.calls] == [100, 3]
    assert pd.read_csv(tmp_path / 'search_counts.csv').iloc[0]['truncated']
    discover(client, {'query': 'exchange'}, ['S-4'], '2023-01-01', '2023-12-31', 103, tmp_path)
    assert len(client.calls) == 2

    unlimited_client = SearchClient()
    unlimited = discover(
        unlimited_client, {'query': 'exchange'}, ['S-4'],
        '2023-01-01', '2023-12-31', None, tmp_path/'unlimited'
    )
    assert len(unlimited) == 105
    assert [call['size'] for call in unlimited_client.calls] == [100, 100]


class SearchClient(Client):
    """Fake SEC search: the general query returns 8 filings, each targeted query 3 (one also in the general set)."""
    def efts_search(self, params):
        q = params['q']
        tag = 'c' if 'Completion' in q else 'e' if 'election' in q else 'g'
        accs = [f'000000000{i}-26-00000{i}' for i in range(8)] if tag == 'g' else \
               [f'00000001{i}-26-0000{tag}{i}' for i in range(2)] + ['0000000001-26-000001']
        accs = accs if params['from'] == 0 else []
        hits = [dict(_id=f'{a}:main.htm', _source=dict(adsh=a, form=params['forms'], file_date='2026-03-01',
                    ciks=[a[:9]], display_names=[f'Co {a} (CIK {a[:9]})'])) for a in accs]
        return dict(hits=dict(total=dict(value=len(hits), relation='eq'), hits=hits))


def test_targeted_searches_get_reserved_slots(tmp_path):
    import load_action_filings as laf
    spec = dict(primary=['DEFM14A'], supporting=[], conditional=[], query='"merger"',
                targeted=[dict(name='completion', forms=['DEFM14A'], query='"Completion"', n=2),
                          dict(name='election', forms=['DEFM14A'], query='"election deadline"', n=5)])
    laf.ACTIONS['test_merger'] = spec
    try:
        out = load_action('test_merger', '2026-01-01', '2026-09-30', n=6, output_dir=tmp_path, client=SearchClient())
    finally:
        del laf.ACTIONS['test_merger']
    sel = pd.read_csv(tmp_path / 'selected_filings.csv')
    assert len(out) == 6 and sel['accession'].is_unique
    counts = sel['search'].value_counts()
    assert counts['completion'] == 2          # capped at its n
    assert counts['election'] == 3            # every new match (the shared one went to completion or general)
    assert counts['general'] == 1             # the rest of n comes from the general search
    assert (tmp_path / 'search_counts_completion.csv').exists()
