import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import watch  # noqa: E402

CFG = dict(ma_fast=20, ma_slow=50, breakout_lookback_days=20, volume_lookback_days=20,
           volume_multiple=1.2, rsi_max=75, bb_period=20, bb_stddev=2.0, percent_b_max=1.0,
           macd_cross_max_age_days=2, earnings_blackout_days=3)
ENTRY = dict(breakout_buffer_pct=0.02, hold_above_breakout_minutes=120,
             late_breakout_after="13:30", confirm_eval_at="15:25")


def uptrend(n=60):
    c = [100 + i * 0.3 + (4 if i % 2 else -4) for i in range(n)]
    return dict(c=c, h=[x + 0.2 for x in c], l=[x - 1 for x in c], v=[1000] * n)


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.bars = uptrend()
        self.level = max(self.bars["h"][-20:])

    def live(self, price, minutes, earnings=True):
        return dict(price=price, volume=900, minute_closes=minutes, earnings_ok=earnings)

    def test_hold_trigger_needs_full_window(self):
        p = self.level + 0.3
        short = watch.watch_one("X", self.bars, self.live(p, [p] * 119), CFG, ENTRY)
        self.assertTrue(short["qualified"])
        self.assertEqual(short["trigger"], "-")
        full = watch.watch_one("X", self.bars, self.live(p, [self.level - 1] + [p] * 120), CFG, ENTRY)
        self.assertEqual(full["trigger"], "hold")

    def test_dip_resets_hold(self):
        p = self.level + 0.3
        row = watch.watch_one("X", self.bars, self.live(p, [p] * 100 + [self.level] + [p] * 30),
                              CFG, ENTRY)
        self.assertEqual(row["held_minutes"], 30)
        self.assertEqual(row["trigger"], "-")

    def test_surge_trigger(self):
        p = self.level * 1.021
        row = watch.watch_one("X", self.bars, self.live(p, [p]), CFG, ENTRY)
        self.assertTrue(row["qualified"])
        self.assertEqual(row["trigger"], "surge")

    def test_fail_closed_on_missing_earnings_or_price(self):
        p = self.level * 1.03
        row = watch.watch_one("X", self.bars, dict(price=p, minute_closes=[p]), CFG, ENTRY)
        self.assertIn("earnings", row["failed"])
        self.assertEqual(row["trigger"], "-")
        missing = watch.watch_one("X", self.bars, None, CFG, ENTRY)
        self.assertEqual(missing["failed"], "missing_live_price")
        self.assertEqual(missing["prior_high"], round(self.level, 4))

    def test_below_breakout_not_triggered(self):
        row = watch.watch_one("X", self.bars, self.live(self.level - 0.5, []), CFG, ENTRY)
        self.assertIn("price>breakout", row["failed"])
        self.assertEqual(row["trigger"], "-")

    def test_late_breakout_close_confirmation(self):
        p = self.level + 0.3

        def at(as_of, held):
            live = self.live(p, [self.level - 1] + [p] * held)
            live["as_of"] = as_of
            return watch.watch_one("X", self.bars, live, CFG, ENTRY)["trigger"]

        self.assertEqual(at("15:25", 100), "close")
        self.assertEqual(at("15:20", 95), "-")
        self.assertEqual(at("15:25", 116), "-")
        self.assertEqual(at("15:30", 120), "hold")


if __name__ == "__main__":
    unittest.main()
