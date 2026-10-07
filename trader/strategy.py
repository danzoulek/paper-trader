"""Trading strategies. A strategy turns price history into target weights
(fraction of account value to hold in each symbol). Risk rules are applied
afterwards in risk.py."""


def sma(values, n):
    return sum(values[-n:]) / n


def sma_trend(closes, prices, fast_days=20, slow_days=50):
    """Hold a symbol while its fast moving average is above its slow one and
    the price is above the slow average; otherwise stay in cash. Every symbol
    that qualifies gets an equal share."""
    picks = []
    for sym, hist in closes.items():
        if len(hist) < slow_days or sym not in prices:
            continue
        slow = sma(hist, slow_days)
        if sma(hist, fast_days) > slow and prices[sym] > slow:
            picks.append(sym)
    if not picks:
        return {}
    return {s: 1.0 / len(picks) for s in sorted(picks)}


STRATEGIES = {"sma_trend": sma_trend}


def target_weights(cfg, closes, prices):
    params = dict(cfg)
    fn = STRATEGIES[params.pop("name")]
    return fn(closes, prices, **params)
