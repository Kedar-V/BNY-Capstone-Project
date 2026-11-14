"""Collects each filing's SEC file number and each issuer's incorporation from the SEC submissions API (cached)."""
import json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'notebooks' / 'evaluation'))
from issuer_info import SUBMISSIONS_URL, issuer_location  # noqa: E402

CACHE = Path(__file__).resolve().parent / 'cache' / 'file_numbers.json'
ISSUERS = Path(__file__).resolve().parent / 'cache' / 'issuers.json'
env = (ROOT / '.env').read_text() if (ROOT / '.env').exists() else ''
m = re.search(r'^SEC_USER_AGENT\s*=\s*(.+)$', env, re.M)
UA = m.group(1).strip().strip('"\'') if m else 'BNY Capstone pb251@duke.edu'


class CurlClient:
    """Fetches each URL once per run, so the file numbers and the issuer fields share one SEC call per company."""

    def __init__(self):
        self.seen = {}

    def get_json(self, url):
        if url not in self.seen:
            out = subprocess.run(['curl', '-s', '-m', '30', '-A', UA, '--compressed', url], capture_output=True, text=True).stdout
            self.seen[url] = json.loads(out)
            time.sleep(0.2)
        return self.seen[url]


filings = json.load(open(Path(__file__).resolve().parents[1] / 'src' / 'data' / 'filings.json'))
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
issuers = json.loads(ISSUERS.read_text()) if ISSUERS.exists() else {}
client = CurlClient()
wanted = {f['accession'] for f in filings} - set(cache)
ciks = {f['cik'] for f in filings if f['accession'] in wanted} | {f['cik'] for f in filings if str(int(f['cik'])) not in issuers}
for cik in sorted(ciks):
    try:
        r = client.get_json(SUBMISSIONS_URL.format(cik=int(cik)))['filings']['recent']
    except Exception:
        print('fail', cik)
        continue
    for acc, fn in zip(r['accessionNumber'], r['fileNumber']):
        if acc in wanted and fn:
            cache[acc] = fn
    location = issuer_location(cik, client)
    if location:
        issuers[str(int(cik))] = location
CACHE.write_text(json.dumps(cache, indent=0))
ISSUERS.write_text(json.dumps(issuers, indent=0))
print(len(cache), 'of', len({f['accession'] for f in filings}), 'accessions have a file number;', len(issuers), 'issuers recorded')
