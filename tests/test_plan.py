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
    cfg["live"].update(enabled=False, account_number="", require_approval=False, max_account_dollars=500,
                       max_order_dollars=150, max_orders_per_run=8, min_order_dollars=5)
    cfg["live"].update(live)
    return cfg


class Plan(unittest.TestCase):
    def test_file_data_matches_source(self):
        import tempfile
        from trader.data import FileData
        sim, syms = SimulatedData(), ["SPY", "QQQ"]
        body = {"closes": sim.daily_closes(syms, 60), "prices": sim.latest_prices(syms)}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(body, f)
        fd = FileData(f.name)
        self.assertEqual(fd.daily_closes(syms, 55), sim.daily_closes(syms, 55))
        self.assertEqual(fd.latest_prices(syms), sim.latest_prices(syms))

    def test_config_has_live_limits(self):
        live = json.loads((ROOT / "config.json").read_text())["live"]
        for key in ("enabled", "account_number", "max_account_dollars", "max_order_dollars"):
            self.assertIn(key, live)

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

    def test_approval_required(self):
        cfg = config(enabled=True, account_number="X", require_approval=True)
        holdings = {"cash": 500, "positions": {}}
        self.assertEqual(make_plan(cfg, holdings, SimulatedData(), OPEN)["status"], "needs_approval")
        self.assertEqual(make_plan(cfg, holdings, SimulatedData(), OPEN, approved=True)["status"], "ready")

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
