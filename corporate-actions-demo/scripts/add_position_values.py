"""Adds a cost per share and a current price to each client position (idempotent).

The client positions carry shares only. These per-share values are placeholders so the Holdings page can show
invested and current amounts; replace them with custody and market data when those feeds are available.
"""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [ROOT / 'agents' / 'client_briefing' / 'clients.json', ROOT / 'corporate-actions-demo' / 'src' / 'data' / 'briefs.json']
KNOWN = {'AAPL': 210.0, 'MSFT': 450.0, 'JPM': 250.0, 'GOOGL': 185.0, 'VTI': 290.0}


def unit(ticker: str, salt: str) -> float:
    return int(hashlib.sha256(f'{salt}:{ticker}'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def values(ticker: str) -> tuple[float, float]:
    price = KNOWN.get(ticker) or round(8 + unit(ticker, 'price') * 132, 2)
    cost = round(price * (0.72 + unit(ticker, 'cost') * 0.56), 2)
    return price, cost


def patch(clients: list[dict]) -> None:
    for c in clients:
        for p in c['positions']:
            p['price'], p['avgCost'] = values(p['ticker'])


for path in TARGETS:
    data = json.loads(path.read_text())
    patch(data['clients'] if isinstance(data, dict) else data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2 if isinstance(data, list) else None, separators=None if isinstance(data, list) else (',', ':')))
    print('updated', path.relative_to(ROOT))
