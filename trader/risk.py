"""Risk rules, applied to whatever the strategy wants."""


def cap_weights(weights, max_position_pct, max_invested_pct):
    capped = {s: min(w, max_position_pct) for s, w in weights.items()}
    total = sum(capped.values())
    if total > max_invested_pct:
        capped = {s: w * max_invested_pct / total for s, w in capped.items()}
    return capped


def stopped_out(positions, prices, stop_loss_pct):
    """Symbols whose price has fallen stop_loss_pct below the average cost."""
    return {s for s, p in positions.items()
            if s in prices and prices[s] <= p["avg_cost"] * (1 - stop_loss_pct)}


def daily_loss_hit(equity_now, equity_at_open, max_daily_loss_pct):
    return equity_at_open > 0 and equity_now <= equity_at_open * (1 - max_daily_loss_pct)


def plan_orders(target_weights, positions, prices, equity, min_trade_dollars):
    """Orders (symbol, side, qty) that move current holdings to the targets.
    Whole shares only. Sells come first so cash is freed for buys."""
    orders = []
    symbols = set(target_weights) | set(positions)
    for sym in sorted(symbols):
        price = prices.get(sym)
        if not price:
            continue
        have = positions.get(sym, {}).get("qty", 0)
        want = int(target_weights.get(sym, 0) * equity // price)
        delta = want - have
        if delta == 0 or (abs(delta) * price < min_trade_dollars and want != 0):
            continue
        orders.append((sym, "buy" if delta > 0 else "sell", abs(delta)))
    return sorted(orders, key=lambda o: o[1] != "sell")
