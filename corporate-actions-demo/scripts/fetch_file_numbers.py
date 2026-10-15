"""Collects the SEC file number of each filing from the SEC submissions API (cached)."""
import json, re, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / 'cache' / 'file_numbers.json'
env = (ROOT / '.env').read_text() if (ROOT / '.env').exists() else ''
m = re.search(r'^SEC_USER_AGENT\s*=\s*(.+)$', env, re.M)
UA = m.group(1).strip().strip('"\'') if m else 'BNY Capstone pb251@duke.edu'

filings = json.load(open(Path(__file__).resolve().parents[1] / 'src' / 'data' / 'filings.json'))
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
wanted = {f['accession'] for f in filings} - set(cache)
for cik in sorted({f['cik'] for f in filings if f['accession'] in wanted}):
    out = subprocess.run(['curl', '-s', '-m', '30', '-A', UA, '--compressed', f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'],
                         capture_output=True, text=True).stdout
    try:
        r = json.loads(out)['filings']['recent']
    except Exception:
        print('fail', cik)
        continue
    for acc, fn in zip(r['accessionNumber'], r['fileNumber']):
        if acc in wanted and fn:
            cache[acc] = fn
    time.sleep(0.2)
CACHE.write_text(json.dumps(cache, indent=0))
print(len(cache), 'of', len({f['accession'] for f in filings}), 'accessions have a file number')
