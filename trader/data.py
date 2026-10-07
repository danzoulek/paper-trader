"""Market data sources. Each returns {symbol: [daily closes, oldest first]}
and {symbol: latest price}."""
import json
import math
import os
import random
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


class AlpacaData:
    """Free market data from Alpaca (IEX feed). Needs ALPACA_API_KEY and
    ALPACA_API_SECRET from a free Alpaca paper account. Read-only."""

    BASE = "https://data.alpaca.markets/v2/stocks"

    def __init__(self):
        self.key = os.environ.get("ALPACA_API_KEY")
        self.secret = os.environ.get("ALPACA_API_SECRET")
        if not (self.key and self.secret):
            raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET to use Alpaca market data.")

    def _get(self, path, params):
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def daily_closes(self, symbols, days):
        start = (datetime.now(timezone.utc) - timedelta(days=days * 2 + 10)).date().isoformat()
        out = {s: [] for s in symbols}
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                  "limit": 10000, "feed": "iex", "adjustment": "all"}
        while True:
            body = self._get("bars", params)
            for sym, bars in (body.get("bars") or {}).items():
                out[sym].extend(b["c"] for b in bars)
            token = body.get("next_page_token")
            if not token:
                return out
            params["page_token"] = token

    def latest_prices(self, symbols):
        body = self._get("trades/latest", {"symbols": ",".join(symbols), "feed": "iex"})
        return {s: t["p"] for s, t in body.get("trades", {}).items()}


class SimulatedData:
    """Random-walk prices for testing without a network or an account."""

    def __init__(self, seed=7, days=120):
        self.seed, self.days = seed, days

    def _series(self, symbol):
        rng = random.Random(f"{self.seed}-{symbol}")
        drift = rng.uniform(-0.001, 0.0015)
        price, out = rng.uniform(50, 500), []
        for _ in range(self.days):
            price *= math.exp(drift + rng.gauss(0, 0.012))
            out.append(round(price, 2))
        return out

    def daily_closes(self, symbols, days):
        return {s: self._series(s)[-days:] for s in symbols}

    def latest_prices(self, symbols):
        return {s: self._series(s)[-1] for s in symbols}


UA = {"User-Agent": "Mozilla/5.0 (paper-trader)"}


def _fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode()


class YahooData:
    """Free daily prices from Yahoo Finance's public chart endpoint. No
    account or key. Unofficial, so FreeData falls back to Stooq if it fails."""

    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"

    @staticmethod
    def parse(text):
        res = json.loads(text)["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        return closes, res["meta"].get("regularMarketPrice") or closes[-1]

    def _one(self, sym, days):
        rng = "3mo" if days <= 55 else "6mo" if days <= 115 else "1y"
        return self.parse(_fetch(self.URL.format(sym=urllib.parse.quote(sym), rng=rng)))

    def daily_closes(self, symbols, days):
        return {s: self._one(s, days)[0][-days:] for s in symbols}

    def latest_prices(self, symbols):
        return {s: self._one(s, 5)[1] for s in symbols}


class StooqData:
    """Free end-of-day prices from stooq.com as CSV. No account or key.
    The last row is today's bar while the market is open."""

    URL = "https://stooq.com/q/d/l/?s={sym}.us&i=d"

    @staticmethod
    def parse(text):
        rows = [line.split(",") for line in text.strip().splitlines()[1:]]
        closes = [float(r[4]) for r in rows if len(r) > 4 and r[4] not in ("", "N/D")]
        if not closes:
            raise ValueError("Stooq returned no prices")
        return closes

    def _one(self, sym):
        return self.parse(_fetch(self.URL.format(sym=sym.lower().replace(".", "-"))))

    def daily_closes(self, symbols, days):
        return {s: self._one(s)[-days:] for s in symbols}

    def latest_prices(self, symbols):
        return {s: self._one(s)[-1] for s in symbols}


class FreeData:
    """Tries each free source in order and uses the first that works."""

    def __init__(self, sources=None):
        self.sources = sources or [YahooData(), StooqData()]

    def _first(self, method, *args):
        errors = []
        for src in self.sources:
            try:
                return getattr(src, method)(*args)
            except Exception as e:  # network error, format change, rate limit
                errors.append(f"{type(src).__name__}: {e}")
        raise RuntimeError("All free data sources failed: " + "; ".join(errors))

    def daily_closes(self, symbols, days):
        return self._first("daily_closes", symbols, days)

    def latest_prices(self, symbols):
        return self._first("latest_prices", symbols)


class FileData:
    """Prices from a JSON file written by someone else, e.g. the live Claude
    task copying Robinhood's own quotes: {"closes": {sym: [...]}, "prices": {sym: p}}."""

    def __init__(self, path):
        body = json.loads(open(path).read())
        self.closes, self.prices = body["closes"], body["prices"]

    def daily_closes(self, symbols, days):
        return {s: [float(c) for c in self.closes.get(s, [])][-days:] for s in symbols}

    def latest_prices(self, symbols):
        return {s: float(self.prices[s]) for s in symbols if s in self.prices}


def make_data_source(name):
    if name == "free":
        return FreeData()
    if name == "alpaca":
        return AlpacaData()
    if name == "simulated":
        return SimulatedData()
    raise ValueError(f"Unknown data_source {name!r}")
