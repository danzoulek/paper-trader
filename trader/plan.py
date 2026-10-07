"""Decide-only mode for the Robinhood agentic account.

This module never places an order. It reads the account's holdings (a JSON
file the scheduled Claude task writes from the Robinhood connector), runs the
same strategy and risk rules as the paper bot, and writes a plan of dollar-
based orders plus a status:

    ready    live trading is enabled and every order passed the hard limits
    dry_run  live trading is switched off; the orders are what it WOULD do
    blocked  something failed a check; nothing may be placed

    python -m trader.plan --holdings holdings.json --out plan.json

holdings.json looks like:
    {"cash": 480.0, "equity_previous_close": 500.0,
     "positions": {"SPY": {"qty": 0.025, "avg_cost": 777.0}}}
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import risk
from .data import FileData, make_data_source
from .market_hours import NY, is_market_open
from .strategy import target_weights

ROOT = Path(__file__).resolve().parent.parent


def make_orders(cfg, holdings, closes, prices):
    """Dollar-based orders that move the holdings toward the strategy's
    targets, sized against at most live.max_account_dollars."""
    live, r = cfg["live"], cfg["risk"]
    positions = holdings.get("positions", {})
    cash = float(holdings["cash"])
    equity = cash + sum(p["qty"] * prices.get(s, p["avg_cost"]) for s, p in positions.items())
    budget = min(equity, live["max_account_dollars"])
    notes = []

    prev = holdings.get("equity_previous_close")
    if prev and risk.daily_loss_hit(equity, float(prev), r["max_daily_loss_pct"]):
        notes.append("Daily loss limit hit: selling everything for today.")
        targets = {}
    else:
        targets = target_weights(cfg["strategy"], closes, prices)
        for s in risk.stopped_out(positions, prices, r["stop_loss_pct"]):
            notes.append(f"Stop loss on {s}.")
            targets.pop(s, None)
        targets = risk.cap_weights(targets, r["max_position_pct"], r["max_invested_pct"])

    sells, buys = [], []
    for sym in sorted(set(targets) | set(positions)):
        price = prices.get(sym)
        if not price:
            continue
        have_qty = positions.get(sym, {}).get("qty", 0)
        delta = targets.get(sym, 0) * budget - have_qty * price
        if sym not in targets and have_qty > 0:
            sells.append({"symbol": sym, "side": "sell", "quantity": round(have_qty, 6)})
        elif delta <= -live["min_order_dollars"]:
            sells.append({"symbol": sym, "side": "sell", "quantity": round(-delta / price, 6)})
        elif delta >= live["min_order_dollars"]:
            buys.append({"symbol": sym, "side": "buy",
                         "dollar_amount": round(min(delta, live["max_order_dollars"]), 2)})

    # Only spend cash already in the account; sale proceeds settle later.
    spendable, kept = cash, []
    for b in buys:
        amt = round(min(b["dollar_amount"], spendable), 2)
        if amt >= live["min_order_dollars"]:
            kept.append({**b, "dollar_amount": amt})
            spendable -= amt
    return sells + kept, equity, budget, notes


def check(cfg, orders, holdings):
    """Hard limits, enforced in code before anything reaches Robinhood."""
    live = cfg["live"]
    problems = []
    if len(orders) > live["max_orders_per_run"]:
        problems.append(f"{len(orders)} orders is over the limit of {live['max_orders_per_run']}.")
    total_buys = sum(o.get("dollar_amount", 0) for o in orders)
    if total_buys > float(holdings["cash"]) + 0.01:
        problems.append("Buys exceed available cash.")
    for o in orders:
        if o["symbol"] not in cfg["symbols"] and o["side"] == "buy":
            problems.append(f"{o['symbol']} is not on the allowed list.")
        if o.get("dollar_amount", 0) > live["max_order_dollars"]:
            problems.append(f"{o['symbol']} buy is over ${live['max_order_dollars']}.")
        held = holdings.get("positions", {}).get(o["symbol"], {}).get("qty", 0)
        if o["side"] == "sell" and o["quantity"] > held + 1e-6:
            problems.append(f"Selling more {o['symbol']} than is held.")
    return problems


def make_plan(cfg, holdings, data, now=None):
    now = now or datetime.now(NY)
    closes = data.daily_closes(cfg["symbols"], cfg["strategy"]["slow_days"] + 5)
    prices = data.latest_prices(sorted(set(cfg["symbols"]) | set(holdings.get("positions", {}))))
    orders, equity, budget, notes = make_orders(cfg, holdings, closes, prices)
    problems = check(cfg, orders, holdings)
    live = cfg["live"]

    if not is_market_open(now):
        problems.append("Market is closed.")
    if problems:
        status = "blocked"
    elif not live["enabled"]:
        status = "dry_run"
    elif not live["account_number"]:
        status, problems = "blocked", ["No agentic account number in config.json."]
    else:
        status = "ready"
    return {
        "created": now.isoformat(timespec="seconds"),
        "status": status,
        "account_number": live["account_number"],
        "equity": round(equity, 2),
        "budget": round(budget, 2),
        "orders": orders,
        "prices": {o["symbol"]: prices[o["symbol"]] for o in orders},
        "notes": notes,
        "problems": problems,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holdings", required=True)
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--market-data", help="JSON file of closes and prices to use instead of the web")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    holdings = json.loads(Path(a.holdings).read_text())
    data = FileData(a.market_data) if a.market_data else make_data_source(cfg["data_source"])
    plan = make_plan(cfg, holdings, data)
    Path(a.out).write_text(json.dumps(plan, indent=2))
    print(f"Status: {plan['status']}")
    for o in plan["orders"]:
        size = f"${o['dollar_amount']:.2f}" if "dollar_amount" in o else f"{o['quantity']} sh"
        print(f"  {o['side'].upper()} {o['symbol']} {size}")
    for line in plan["notes"] + plan["problems"]:
        print(f"  - {line}")
    sys.exit(0 if plan["status"] != "blocked" else 2)


if __name__ == "__main__":
    main()
