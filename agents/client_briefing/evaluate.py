"""Are the numbers in a brief right? Scores the Translate step for rights offerings against the annotated ground truth.

For every rights filing the agent reads, a standard 10,000-share position is worked out twice: from the extraction
run the brief actually uses, and from the independently annotated answer key. The two must give the same client numbers.

    python -m agents.client_briefing.evaluate
"""

from __future__ import annotations

import json
import math
from collections import Counter

from . import config, parsers
from .event_store import load_rights_events

SHARES = 10_000


def client_numbers(ratio: dict | None, price_amount: float | None) -> dict:
    rps = (ratio or {}).get("rights_per_share")
    spr = (ratio or {}).get("shares_per_right")
    rights = math.floor(SHARES * parsers.exact_fraction(rps)) if rps else None
    new_shares = math.floor(rights * parsers.exact_fraction(spr)) if rights is not None and spr else None
    cash = round(new_shares * price_amount, 2) if new_shares is not None and price_amount is not None else None
    return {"rights": rights, "new_shares": new_shares, "cash": cash}


def main() -> None:
    gold = {x["accession_number"]: x for x in json.loads(config.GOLD_JSON.read_text(encoding="utf-8")) if x["is_rights_offering"]}
    every_filing = [f for e in load_rights_events() for f in e.filings]
    filings = [f for f in every_filing if f.accession in gold]
    print(f"{len(every_filing) - len(filings)} filings in the run are not rights offerings in the answer key, so they are not scored.")
    tally: Counter = Counter()
    misses = []
    for f in filings:
        rec = gold[f.accession]["records"][0]
        g_ratio = rec["subscription_ratio"]["normalized"]
        g_price = (rec["subscription_price"]["normalized"] or {}).get("amount")
        p_price = (parsers.parse_price(f.fields.get("subscription_price")) or {}).get("amount")
        ours, truth = client_numbers(parsers.parse_ratio(f.fields.get("subscription_ratio")), p_price), client_numbers(g_ratio, g_price)
        for k in ours:
            tally[f"{k}_total"] += 1
            if ours[k] == truth[k]:
                tally[f"{k}_match"] += 1
                if truth[k] is not None:
                    tally[f"{k}_match_stated"] += 1
            else:
                misses.append((f.registrant, f.form, k, ours[k], truth[k]))
            tally[f"{k}_stated"] += truth[k] is not None

    print(f"{len(filings)} rights filings in the sample; each worked out for a {SHARES:,}-share position.\n")
    print(f"{'Number':<14}{'Same as answer key':<24}{'Where the key has a number':<28}")
    for k, label in [("rights", "Rights"), ("new_shares", "New shares"), ("cash", "Cash")]:
        print(f"{label:<14}{tally[k + '_match']}/{tally[k + '_total']} ({tally[k + '_match'] / tally[k + '_total']:.1%})".ljust(38)
              + f"{tally[k + '_match_stated']}/{tally[k + '_stated']}")
    print("\nDifferences:")
    for m in misses:
        print(f"  {m[0][:38]:<38} {m[1]:<6} {m[2]:<10} brief={m[3]}  key={m[4]}")


if __name__ == "__main__":
    main()
