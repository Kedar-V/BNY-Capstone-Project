"""Step 5: which clients the change reaches. Positions are the simulated ones in client_briefing/clients.json."""

from __future__ import annotations

import json

from events.store import Event

from . import config

# Holders of the acquirer's stock are not paid the target's consideration, so these changes reach target holders only
TARGET_ONLY = {"cash_per_share", "exchange_ratio", "election_deadline", "offer_price", "expiration_date",
               "withdrawal_deadline", "price", "ratio", "record_date", "settlement_date"}


def load_clients() -> list[dict]:
    return json.loads(config.CLIENTS_JSON.read_text(encoding="utf-8"))


def affected(event: Event, change_keys: set[str], clients: list[dict]) -> list[dict]:
    """Clients holding or watching a security of the event that the change applies to."""
    only_target = bool(change_keys) and change_keys <= TARGET_ONLY
    roles = {t.upper(): r for t, r in event.ticker_roles.items() if not only_target or r in {"target", "issuer"}}
    out: list[dict] = []
    for client in clients:
        held = {p["ticker"].upper(): p for p in client["positions"]}
        for ticker, role in roles.items():
            if ticker in held:
                p = held[ticker]
                out.append({"client_id": client["id"], "client": client["name"], "ticker": ticker, "role": role,
                            "shares": p["shares"], "on_loan": p.get("onLoan", 0), "watch_only": False})
            elif any(w["ticker"].upper() == ticker for w in client.get("watchlist", [])):
                out.append({"client_id": client["id"], "client": client["name"], "ticker": ticker, "role": role,
                            "shares": 0, "on_loan": 0, "watch_only": True})
    return out
