import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from trader import risk
from trader.data import SimulatedData
from trader.market_hours import NY, is_market_open
from trader.strategy import sma_trend


class MarketHours(unittest.TestCase):
    def test_regular_session(self):
        self.assertTrue(is_market_open(datetime(2026, 10, 7, 10, 0, tzinfo=NY)))
        self.assertFalse(is_market_open(datetime(2026, 10, 7, 9, 29, tzinfo=NY)))
        self.assertFalse(is_market_open(datetime(2026, 10, 7, 16, 0, tzinfo=NY)))

    def test_weekend_holiday_early_close(self):
        self.assertFalse(is_market_open(datetime(2026, 10, 10, 12, 0, tzinfo=NY)))  # Saturday
        self.assertFalse(is_market_open(datetime(2026, 11, 26, 12, 0, tzinfo=NY)))  # Thanksgiving
        self.assertTrue(is_market_open(datetime(2026, 11, 27, 12, 0, tzinfo=NY)))
        self.assertFalse(is_market_open(datetime(2026, 11, 27, 13, 30, tzinfo=NY)))


class Strategy(unittest.TestCase):
    def test_uptrend_bought_downtrend_skipped(self):
        up = [100 + i for i in range(60)]
        down = [200 - i for i in range(60)]
        w = sma_trend({"UP": up, "DOWN": down}, {"UP": 160, "DOWN": 140})
        self.assertEqual(w, {"UP": 1.0})

    def test_not_enough_history(self):
        self.assertEqual(sma_trend({"X": [1] * 10}, {"X": 1}), {})


class Risk(unittest.TestCase):
    def test_caps(self):
        w = risk.cap_weights({"A": 0.5, "B": 0.5}, 0.15, 0.9)
        self.assertEqual(w, {"A": 0.15, "B": 0.15})
        w = risk.cap_weights({s: 0.1 for s in "ABCDEFGHIJ"}, 0.15, 0.9)
        self.assertAlmostEqual(sum(w.values()), 0.9)

    def test_stop_and_daily_loss(self):
        pos = {"A": {"qty": 10, "avg_cost": 100}, "B": {"qty": 10, "avg_cost": 100}}
        self.assertEqual(risk.stopped_out(pos, {"A": 91, "B": 95}, 0.08), {"A"})
        self.assertTrue(risk.daily_loss_hit(9690, 10000, 0.03))
        self.assertFalse(risk.daily_loss_hit(9800, 10000, 0.03))

    def test_plan_sells_first_and_skips_tiny(self):
        pos = {"OLD": {"qty": 5, "avg_cost": 10}}
        orders = risk.plan_orders({"NEW": 0.5}, pos, {"OLD": 10, "NEW": 100}, 1000, 50)
        self.assertEqual(orders, [("OLD", "sell", 5), ("NEW", "buy", 5)])
        pos = {"NEW": {"qty": 5, "avg_cost": 100}}
        self.assertEqual(risk.plan_orders({"NEW": 0.52}, pos, {"NEW": 100}, 1000, 50), [])


class FreeSources(unittest.TestCase):
    def test_yahoo_parse_skips_gaps(self):
        body = json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": 101.5},
            "indicators": {"quote": [{"close": [99.0, None, 100.0, 101.0]}]}}]}})
        from trader.data import YahooData
        self.assertEqual(YahooData.parse(body), ([99.0, 100.0, 101.0], 101.5))

    def test_stooq_parse(self):
        from trader.data import StooqData
        csv_text = "Date,Open,High,Low,Close,Volume\n2026-10-05,1,2,0.5,1.5,100\n2026-10-06,1,2,0.5,1.75,100\n"
        self.assertEqual(StooqData.parse(csv_text), [1.5, 1.75])
        with self.assertRaises(ValueError):
            StooqData.parse("No data")

    def test_fallback_to_next_source(self):
        from trader.data import FreeData

        class Broken:
            def latest_prices(self, symbols):
                raise OSError("blocked")
        free = FreeData([Broken(), SimulatedData()])
        self.assertIn("SPY", free.latest_prices(["SPY"]))
        with self.assertRaises(RuntimeError):
            FreeData([Broken()]).latest_prices(["SPY"])


class EndToEnd(unittest.TestCase):
    def test_paper_run_is_idempotent(self):
        from trader.run import ROOT, run
        with tempfile.TemporaryDirectory() as d:
            os.environ["TRADER_STATE_DIR"] = d
            cfg = json.loads((ROOT / "config.json").read_text())
            cfg.update(broker="local", data_source="simulated")
            cp = Path(d) / "config.json"
            cp.write_text(json.dumps(cfg))
            first = run(cp, force=True, data_source=SimulatedData())
            second = run(cp, force=True, data_source=SimulatedData())
            acct = json.loads((Path(d) / "paper_account.json").read_text())
            del os.environ["TRADER_STATE_DIR"]
        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertGreaterEqual(acct["cash"], 0)

    def test_live_mode_refused(self):
        from trader.run import run
        with tempfile.TemporaryDirectory() as d:
            cp = Path(d) / "config.json"
            cp.write_text(json.dumps({"mode": "live"}))
            with self.assertRaises(SystemExit):
                run(cp, force=True)


if __name__ == "__main__":
    unittest.main()
