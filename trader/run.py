"""One trading pass. Run it on a schedule during market hours:

    python -m trader.run            # skips when the market is closed
    python -m trader.run --force    # run anyway (for testing)
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import risk
from .broker import make_broker
from .data import make_data_source
from .market_hours import NY, is_market_open
from .strategy import target_weights

ROOT = Path(__file__).resolve().parent.parent


def log(msg):
    print(f"[{datetime.now(NY):%Y-%m-%d %H:%M %Z}] {msg}", flush=True)


def opening_equity(state_dir, today, equity, broker):
    """Equity at the start of the day, for the daily loss limit."""
    path = state_dir / "day.json"
    day = json.loads(path.read_text()) if path.exists() else {}
    if day.get("date") != today:
        start = broker.opening_equity() if hasattr(broker, "opening_equity") else equity
        day = {"date": today, "equity_at_open": start, "halted": False}
        path.write_text(json.dumps(day))
    return day, path


def record(state_dir, fills):
    path = state_dir / "trades.csv"
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "symbol", "side", "qty", "price"])
        for t in fills:
            w.writerow([datetime.now(NY).isoformat(timespec="seconds"),
                        t["symbol"], t["side"], t["qty"], t["price"]])


def run(config_path, force=False, data_source=None):
    cfg = json.loads(Path(config_path).read_text())
    if cfg.get("mode") != "paper":
        sys.exit("Refusing to run: only mode \"paper\" is supported.")
    if not force and not is_market_open():
        log("Market is closed; nothing to do.")
        return []

    state_dir = Path(os.environ.get("TRADER_STATE_DIR", ROOT / "state"))
    state_dir.mkdir(exist_ok=True)
    data = data_source or make_data_source(cfg["data_source"])
    broker = make_broker(os.environ.get("TRADER_BROKER", cfg["broker"]), state_dir, cfg["starting_cash"])
    r = cfg["risk"]
    symbols = cfg["symbols"]

    held = broker.positions()
    all_syms = sorted(set(symbols) | set(held))
    closes = data.daily_closes(symbols, cfg["strategy"]["slow_days"] + 5)
    prices = data.latest_prices(all_syms)
    equity = broker.equity(prices)
    day, day_path = opening_equity(state_dir, datetime.now(NY).date().isoformat(), equity, broker)
    log(f"Equity ${equity:,.2f} (opened today at ${day['equity_at_open']:,.2f})")

    if day["halted"] or risk.daily_loss_hit(equity, day["equity_at_open"], r["max_daily_loss_pct"]):
        if not day["halted"]:
            log("Daily loss limit hit: closing all positions until tomorrow.")
            day["halted"] = True
            day_path.write_text(json.dumps(day))
        targets = {}
    else:
        targets = target_weights(cfg["strategy"], closes, prices)
        stops = risk.stopped_out(held, prices, r["stop_loss_pct"])
        for s in stops:
            log(f"Stop loss: {s} is {r['stop_loss_pct']:.0%} below cost, selling.")
            targets.pop(s, None)
        targets = risk.cap_weights(targets, r["max_position_pct"], r["max_invested_pct"])

    log("Targets: " + (", ".join(f"{s} {w:.0%}" for s, w in targets.items()) or "all cash"))
    orders = risk.plan_orders(targets, held, prices, equity, r["min_trade_dollars"])
    fills = []
    for sym, side, qty in orders:
        fill = broker.submit(sym, side, qty, prices[sym])
        if fill:
            log(f"PAPER {side.upper()} {qty} {sym} @ ${prices[sym]:,.2f}")
            fills.append(fill)
    if not orders:
        log("No trades needed.")
    record(state_dir, fills)
    return fills


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--force", action="store_true", help="run even if the market is closed")
    ap.add_argument("--simulated", action="store_true", help="use made-up prices (no account needed)")
    a = ap.parse_args()
    src = None
    if a.simulated:
        from .data import SimulatedData
        src = SimulatedData()
    run(a.config, force=a.force, data_source=src)


if __name__ == "__main__":
    main()
