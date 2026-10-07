import json
import unittest
from datetime import datetime

from trader.data import SimulatedData
from trader.market_hours import NY
from trader.plan import check, make_plan
from trader.run import ROOT

OPEN = datetime(2026, 10, 7, 10, 0, tzinfo=NY)
CLOSED = datetime(2026, 10, 10, 10, 0, tzinfo=NY)


def config(**live):
    cfg = json.loads((ROOT / "config.json").read_text())
    cfg["live"].update(live)
    return cfg


class Plan(unittest.TestCase):
    def test_off_by_default(self):
        cfg = json.loads((ROOT / "config.json").read_text())
        self.assertFalse(cfg["live"]["enabled"])
        self.assertEqual(cfg["live"]["account_number"], "")

    def test_switched_off_is_dry_run_with_orders(self):
        plan = make_plan(config(), {"cash": 500, "positions": {}}, SimulatedData(), OPEN)
        self.assertEqual(plan["status"], "dry_run")
        self.assertTrue(plan["orders"])
        self.assertTrue(all(o["side"] == "buy" for o in plan["orders"]))

    def test_limits_respected(self):
        cfg = config(enabled=True, account_number="X", max_account_dollars=500, max_order_dollars=60)
        plan = make_plan(cfg, {"cash": 5000, "positions": {}}, SimulatedData(), OPEN)
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["budget"], 500)
        self.assertTrue(all(o["dollar_amount"] <= 60 for o in plan["orders"]))
        self.assertLessEqual(sum(o["dollar_amount"] for o in plan["orders"]), 500 * 0.9 + 0.01)

    def test_never_spends_more_than_cash(self):
        cfg = config(enabled=True, account_number="X")
        plan = make_plan(cfg, {"cash": 40, "positions": {}}, SimulatedData(), OPEN)
        self.assertLessEqual(sum(o["dollar_amount"] for o in plan["orders"]), 40)

    def test_enabled_without_account_is_blocked(self):
        plan = make_plan(config(enabled=True), {"cash": 500, "positions": {}}, SimulatedData(), OPEN)
        self.assertEqual(plan["status"], "blocked")

    def test_closed_market_is_blocked(self):
        cfg = config(enabled=True, account_number="X")
        plan = make_plan(cfg, {"cash": 500, "positions": {}}, SimulatedData(), CLOSED)
        self.assertEqual(plan["status"], "blocked")

    def test_sells_holdings_outside_targets(self):
        cfg = config()
        holdings = {"cash": 0, "positions": {"ZZZ": {"qty": 1.5, "avg_cost": 10}}}
        plan = make_plan(cfg, holdings, SimulatedData(), OPEN)
        self.assertIn({"symbol": "ZZZ", "side": "sell", "quantity": 1.5}, plan["orders"])

    def test_check_catches_bad_orders(self):
        cfg = config()
        holdings = {"cash": 100, "positions": {"SPY": {"qty": 1, "avg_cost": 1}}}
        bad = [{"symbol": "TSLA", "side": "buy", "dollar_amount": 500},
               {"symbol": "SPY", "side": "sell", "quantity": 2}]
        self.assertEqual(len(check(cfg, bad, holdings)), 4)


if __name__ == "__main__":
    unittest.main()
