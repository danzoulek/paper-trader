# Paper trader

A small bot that trades a basket of ETFs on a schedule while the US market is
open. **It only paper-trades.** There is no code path that sends a real-money
order: `mode` must be `"paper"`, and the only brokers are a local simulated
account and Alpaca's paper endpoint (hard-coded URL).

## How a run works

1. Skip if the market is closed (weekends, NYSE holidays, outside 9:30-16:00 ET, early closes).
2. Fetch ~55 days of daily closes plus the latest price for each symbol from
   free public sources: Yahoo Finance first, Stooq if Yahoo fails. No
   account or key. Both are unofficial, so a format change can break one;
   the run stops with an error (and places no trades) if both fail.
3. Strategy `sma_trend`: hold a symbol while its 20-day average is above its
   50-day average and the price is above the 50-day; otherwise cash.
4. Risk rules: at most 15% per symbol, 90% invested, sell anything 8% below
   its cost, and go to cash for the rest of the day if the account is down 3%.
5. Place whole-share orders to reach the targets (sells first, skip trades
   under $50) and append them to `state/trades.csv`.

Runs are idempotent: running again with the same prices places no new orders,
so it is safe to run every 30 minutes.

## Try it

```bash
python -m unittest tests.test_trader            # paper bot tests
python -m unittest tests.test_plan               # live-plan tests
python -m trader.run --force --simulated        # made-up prices, no account
```

```bash
python -m trader.run --force                    # real prices, local $10k paper account
```

Optional: with a free Alpaca paper account you can set `"data_source": "alpaca"`
and/or `TRADER_BROKER=alpaca_paper` (needs `ALPACA_API_KEY` and `ALPACA_API_SECRET`).

## Schedule

`.github/workflows/trade.yml` runs it every 30 minutes on weekdays from
GitHub Actions once this folder is in a GitHub repo (keep the repo private:
it stores the paper account and trade log in `state/`). No secrets needed.
A cron line on any always-on machine works too:

```
*/30 9-16 * * 1-5  cd /path/to/trader && python3 -m trader.run >> run.log 2>&1
```
(set the machine's timezone to America/New_York, or adjust the hours).

## Real money (switched off)

`trader/plan.py` is a decide-only mode for a Robinhood agentic account: it
turns the account's holdings into a plan of dollar-based orders, checks them
against hard limits (`live` in `config.json`), and never places anything
itself. A scheduled Claude task would place the planned orders through the
Robinhood connector; its instructions are in `LIVE_TASK.md`. With
`live.enabled` false (the default) every plan is a `dry_run`.

## Settings (`config.json`)

| Key | Default | Meaning |
|---|---|---|
| `symbols` | 8 ETFs | What it may hold |
| `strategy.fast_days` / `slow_days` | 20 / 50 | Moving-average windows |
| `risk.max_position_pct` | 0.15 | Largest share of the account in one symbol |
| `risk.max_invested_pct` | 0.90 | Keep at least 10% in cash |
| `risk.stop_loss_pct` | 0.08 | Sell a holding 8% below its cost |
| `risk.max_daily_loss_pct` | 0.03 | Go to cash for the day after a 3% drop |
| `starting_cash` | 10000 | Local paper account only |
| `live.enabled` | false | Must be true before any real order |
| `live.account_number` | empty | Your agentic account; must be filled in by you |
| `live.max_account_dollars` | 500 | Plans size against at most this much |
| `live.max_order_dollars` | 150 | Largest single buy |
| `live.max_orders_per_run` | 8 | More than this blocks the whole plan |

## Files

- `trader/market_hours.py`: trading calendar (holidays listed through 2027)
- `trader/data.py`: free Yahoo/Stooq prices, optional Alpaca, simulated prices for tests
- `trader/strategy.py`: strategies (add new ones to `STRATEGIES`)
- `trader/risk.py`: position caps, stops, daily loss limit, order planning
- `trader/broker.py`: local and Alpaca paper brokers
- `trader/run.py`: one paper trading pass
- `trader/plan.py`: decide-only plan for the agentic account
- `LIVE_TASK.md`: instructions for the (not yet scheduled) live task
