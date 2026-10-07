"""Brokers. Only paper brokers exist here on purpose: there is no code path
that can place a real-money order.

LocalPaperBroker keeps a simulated account in a JSON file.
AlpacaPaperBroker uses Alpaca's paper-trading API (fake money, real prices).
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class LocalPaperBroker:
    def __init__(self, state_dir, starting_cash):
        self.path = Path(state_dir) / "paper_account.json"
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": float(starting_cash), "positions": {}}

    def positions(self):
        return self.state["positions"]

    def equity(self, prices):
        held = sum(p["qty"] * prices.get(s, p["avg_cost"]) for s, p in self.positions().items())
        return self.state["cash"] + held

    def submit(self, symbol, side, qty, price):
        pos = self.state["positions"].get(symbol, {"qty": 0, "avg_cost": 0.0})
        if side == "buy":
            cost = qty * price
            if cost > self.state["cash"]:
                qty = int(self.state["cash"] // price)
                cost = qty * price
            if qty <= 0:
                return None
            pos["avg_cost"] = (pos["avg_cost"] * pos["qty"] + cost) / (pos["qty"] + qty)
            pos["qty"] += qty
            self.state["cash"] -= cost
        else:
            qty = min(qty, pos["qty"])
            if qty <= 0:
                return None
            pos["qty"] -= qty
            self.state["cash"] += qty * price
        if pos["qty"]:
            self.state["positions"][symbol] = pos
        else:
            self.state["positions"].pop(symbol, None)
        self.save()
        return {"symbol": symbol, "side": side, "qty": qty, "price": price}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(self.state, indent=2))


class AlpacaPaperBroker:
    """Alpaca paper trading. The URL is fixed to the paper endpoint; live
    trading would need a different URL and is deliberately not supported."""

    BASE = "https://paper-api.alpaca.markets/v2"

    def __init__(self):
        self.key = os.environ["ALPACA_API_KEY"]
        self.secret = os.environ["ALPACA_API_SECRET"]

    def _call(self, method, path, body=None):
        req = urllib.request.Request(
            f"{self.BASE}/{path}", method=method,
            data=json.dumps(body).encode() if body else None,
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def positions(self):
        return {p["symbol"]: {"qty": int(float(p["qty"])), "avg_cost": float(p["avg_entry_price"])}
                for p in self._call("GET", "positions")}

    def equity(self, prices):
        return float(self._call("GET", "account")["equity"])

    def opening_equity(self):
        """Yesterday's closing equity, kept by Alpaca, so the daily loss
        limit works even when no local state survives between runs."""
        return float(self._call("GET", "account")["last_equity"])

    def submit(self, symbol, side, qty, price):
        self._call("POST", "orders", {"symbol": symbol, "qty": str(qty), "side": side,
                                      "type": "market", "time_in_force": "day"})
        return {"symbol": symbol, "side": side, "qty": qty, "price": price}


def make_broker(name, state_dir, starting_cash):
    if name == "local":
        return LocalPaperBroker(state_dir, starting_cash)
    if name == "alpaca_paper":
        return AlpacaPaperBroker()
    raise ValueError(f"Unknown broker {name!r} (only paper brokers are available)")
