from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("shadow", ROOT / "src" / "shadow.py")
shadow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shadow)

COST = shadow.config_block("cost")


class ShadowBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "shadow" / "ledger.jsonl"
        self.now = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
        shadow.append_event(self.path, "open", {"book": "early-surge", "cash": 100000,
                                                "strategy": "突破 1% 即买"}, self.now, COST)

    def fill(self, side, qty, price, minutes_ago=1, symbol="US.AAPL", book="early-surge"):
        return shadow.append_event(self.path, "fill", {
            "book": book, "symbol": symbol, "side": side, "qty": qty, "price": price,
            "filled_at": (self.now - timedelta(minutes=minutes_ago)).isoformat(),
            "reason": "test"}, self.now, COST)

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_config_blocks_parse(self):
        self.assertIn("commission_per_share", COST)
        self.assertIn("late_fill_minutes", shadow.config_block("shadow"))

    def test_round_trip_pnl_and_fees(self):
        buy = self.fill("buy", 100, 10.0)
        sell = self.fill("sell", 100, 11.0)
        self.assertEqual(buy["fees"], 1.99)
        self.assertGreater(sell["fees"], buy["fees"])
        book = shadow.report(self.records(), {}, 15)["books"]["early-surge"]
        self.assertEqual(book["realized_pnl"], 100.0)
        self.assertEqual(book["positions"], {})
        self.assertAlmostEqual(book["cash"], 100000 + 100 - buy["fees"] - sell["fees"], places=2)
        self.assertEqual(book["equity"], book["cash"])

    def test_open_position_needs_mark_for_equity(self):
        self.fill("buy", 10, 50.0)
        self.fill("buy", 10, 60.0)
        report = shadow.report(self.records(), {}, 15)["books"]["early-surge"]
        self.assertEqual(report["positions"]["US.AAPL"]["avg_cost"], 55.0)
        self.assertIsNone(report["equity"])
        marked = shadow.report(self.records(), {"US.AAPL": 70.0}, 15)["books"]["early-surge"]
        self.assertEqual(marked["unrealized_pnl"], 300.0)

    def test_short_and_flip(self):
        self.fill("sell", 10, 100.0)
        self.fill("buy", 15, 90.0)
        book = shadow.report(self.records(), {"US.AAPL": 95.0}, 15)["books"]["early-surge"]
        self.assertEqual(book["realized_pnl"], 100.0)
        self.assertEqual(book["positions"]["US.AAPL"]["qty"], 5)
        self.assertEqual(book["positions"]["US.AAPL"]["avg_cost"], 90.0)

    def test_late_fill_flagged_not_rejected(self):
        self.fill("buy", 1, 10.0, minutes_ago=60)
        self.fill("buy", 1, 10.0, minutes_ago=5)
        self.assertEqual(shadow.report(self.records(), {}, 15)["books"]["early-surge"]["late_fills"], 1)

    def test_rejects_future_fill_unknown_book_and_duplicate(self):
        with self.assertRaises(ValueError):
            self.fill("buy", 1, 10.0, minutes_ago=-5)
        with self.assertRaises(ValueError):
            self.fill("buy", 1, 10.0, book="missing")
        with self.assertRaises(ValueError):
            shadow.append_event(self.path, "open", {"book": "early-surge", "cash": 1, "strategy": "x"},
                                self.now, COST)
        with self.assertRaises(ValueError):
            self.fill("buy", 0, 10.0)

    def test_multiple_books_independent(self):
        shadow.append_event(self.path, "open", {"book": "mean-revert", "cash": 50000,
                                                "strategy": "回调买"}, self.now, COST)
        self.fill("buy", 10, 10.0)
        books = shadow.report(self.records(), {"US.AAPL": 10.0}, 15)["books"]
        self.assertEqual(books["mean-revert"]["equity"], 50000)
        self.assertEqual(books["early-surge"]["fills"], 1)

    def test_snapshot_cursor(self):
        root = Path(self.temp.name)
        folder = root / "snaps" / "2026-11-19"
        (folder / "minute").mkdir(parents=True)
        (folder / "0936.json").write_text("{}")
        (folder / "0946.json").write_text('{"half')
        (folder / "0956.json.tmp").write_text("{}")
        (folder / "watch.csv").write_text("x")
        result = shadow.pending(self.records(), root, "snaps", "2026-11-19")
        self.assertEqual(result["pending"], ["snaps/2026-11-19/0936.json"])
        self.assertEqual(result["unreadable"], ["snaps/2026-11-19/0946.json"])
        shadow.append_event(self.path, "seen", {"snapshot": "snaps/2026-11-19/0936.json"},
                            self.now, COST, root, "snaps")
        after = shadow.pending(self.records(), root, "snaps", "2026-11-19")
        self.assertEqual((after["pending"], after["seen"]), ([], 1))
        for bad in ("snaps/2026-11-19/0936.json", "snaps/2026-11-19/watch.csv", "x.json"):
            with self.assertRaises(ValueError):
                shadow.append_event(self.path, "seen", {"snapshot": bad}, self.now, COST, root, "snaps")
        self.assertEqual(shadow.report(self.records(), {}, 15)["books"]["early-surge"]["fills"], 0)

    def test_config_snapshot_dir_is_string(self):
        self.assertIsInstance(shadow.config_block("shadow")["snapshot_dir"], str)


if __name__ == "__main__":
    unittest.main()
