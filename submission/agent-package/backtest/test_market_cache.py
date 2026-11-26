import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("market_cache", ROOT / "src" / "market_cache.py")
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def response(*days):
    return {"ret_code": 0, "data": {"kline_list": [
        {"date": day, "open": 100, "high": 102, "low": 99,
         "close": 101, "volume": 1000, "turnover": 101000} for day in days
    ]}}


class MarketCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "market-data"
        self.series = cache.identity("US.NVDA")
        self.path = cache.cache_path(self.directory, self.series)

    def merge(self, payload=None, through="2026-11-17", rebuild=False):
        return cache.merge(self.directory, self.series,
                           payload or response(20261116, 20261117), through, rebuild)

    def test_bootstrap_plan_does_not_create_files(self):
        planned = cache.plan(self.directory, self.series, "2026-11-17")
        self.assertEqual(planned["action"], "bootstrap")
        self.assertEqual(planned["request"]["num"], 55)
        self.assertNotIn("start", planned["request"])
        self.assertFalse(self.directory.exists())

    def test_merge_sorted_deduplicated_and_raw_fields_preserved(self):
        self.merge(response(20261117, 20261116, 20261117))
        loaded = json.loads(self.path.read_text())
        self.assertEqual([bar["date"] for bar in loaded["bars"]], ["2026-11-16", "2026-11-17"])
        self.assertEqual(loaded["bars"][0]["turnover"], 101000)
        self.assertEqual(loaded["series"]["timezone"], "America/New_York")

    def test_incremental_request_includes_overlap(self):
        self.merge()
        planned = cache.plan(self.directory, self.series, "2026-11-18", min_bars=2)
        self.assertEqual(planned["action"], "incremental")
        self.assertEqual(planned["request"]["start"], "2026-11-17")
        self.assertEqual(planned["request"]["end"], "2026-11-18")

    def test_up_to_date_cache_needs_no_request(self):
        self.merge()
        planned = cache.plan(self.directory, self.series, "2026-11-17", min_bars=2)
        self.assertEqual(planned["action"], "cached")
        self.assertIsNone(planned["request"])

    def test_small_cache_requests_initial_window(self):
        self.merge()
        self.assertEqual(cache.plan(self.directory, self.series, "2026-11-18")["action"], "bootstrap")

    def test_incremental_merge_retains_all_history(self):
        self.merge()
        self.merge(response(20261117, 20261118), "2026-11-18")
        read = cache.read(self.directory, self.series, "2026-11-18", min_bars=3)
        self.assertEqual(read["dates"], ["2026-11-16", "2026-11-17", "2026-11-18"])
        self.assertEqual(read["bars"]["c"], [101, 101, 101])

    def test_duplicate_merge_is_idempotent(self):
        self.merge()
        self.merge()
        self.assertEqual(len(json.loads(self.path.read_text())["bars"]), 2)

    def test_missing_overlap_is_rejected_without_changing_cache(self):
        self.merge()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.merge(response(20261118), "2026-11-18")
        self.assertEqual(self.path.read_bytes(), original)

    def test_adjustment_revision_invalidates_cache_until_full_rebuild(self):
        self.merge()
        revised = response(20261117, 20261118)
        revised["data"]["kline_list"][0]["close"] = 100
        with self.assertRaises(ValueError):
            self.merge(revised, "2026-11-18")
        self.assertFalse(json.loads(self.path.read_text())["valid"])
        with self.assertRaises(ValueError):
            cache.read(self.directory, self.series, "2026-11-17", min_bars=2)
        self.assertEqual(cache.plan(self.directory, self.series, "2026-11-18")["action"], "rebuild")
        with self.assertRaises(ValueError):
            self.merge(response(20261117, 20261118), "2026-11-18")
        with self.assertRaises(ValueError):
            self.merge(response(20261117, 20261118), "2026-11-18", rebuild=True)
        self.merge(response(20261116, 20261117, 20261118), "2026-11-18", rebuild=True)
        self.assertEqual(len(cache.read(self.directory, self.series, "2026-11-18", 3)["dates"]), 3)

    def test_rebuild_cannot_drop_interior_dates(self):
        self.merge(response(20261116, 20261117, 20261118), "2026-11-18")
        with self.assertRaises(ValueError):
            self.merge(response(20261116, 20261118), "2026-11-18", rebuild=True)

    def test_unadjusted_correction_can_replace_overlap(self):
        self.series = cache.identity("US.NVDA", autype=0)
        self.merge()
        revised = response(20261117, 20261118)
        revised["data"]["kline_list"][0]["close"] = 100
        self.merge(revised, "2026-11-18")
        self.assertEqual(cache.read(self.directory, self.series, "2026-11-18", 3)["bars"]["c"], [101, 100, 101])

    def test_series_do_not_mix(self):
        self.merge()
        for alternate in (cache.identity("US.AAPL"), cache.identity("US.NVDA", autype=0),
                          cache.identity("US.NVDA", extended_time=1),
                          cache.identity("US.NVDA", source="other")):
            with self.subTest(alternate=alternate):
                self.assertEqual(cache.plan(self.directory, alternate, "2026-11-17")["cached_bars"], 0)

    def test_invalid_response_is_rejected_before_writing(self):
        cases = [{"ret_code": 1}, {"ret_code": 0, "data": {"kline_list": []}}, response(20261118)]
        for field, value in (("open", None), ("high", 98), ("low", 103),
                             ("close", float("nan")), ("volume", -1), ("volume", True)):
            payload = response(20261117)
            payload["data"]["kline_list"][0][field] = value
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                cache.merge(self.directory, self.series, payload, "2026-11-17")
        self.assertFalse(self.directory.exists())

    def test_conflicting_duplicate_dates_are_rejected(self):
        payload = response(20261117, 20261117)
        payload["data"]["kline_list"][1]["volume"] = 2000
        with self.assertRaises(ValueError):
            self.merge(payload)

    def test_read_requires_enough_history_and_exact_closed_day(self):
        self.merge()
        for through, minimum in (("2026-11-17", 55), ("2026-11-18", 2), ("2026-11-17", 0)):
            with self.subTest(through=through, minimum=minimum), self.assertRaises(ValueError):
                cache.read(self.directory, self.series, through, minimum)
        self.assertEqual(cache.read(self.directory, self.series, "2026-11-16", 1)["dates"], ["2026-11-16"])

    def test_invalid_identity_cannot_escape_directory(self):
        for symbol, source in (("../../secret", "moomoo"), ("US.NVDA", "../secret")):
            with self.assertRaises(ValueError):
                cache.identity(symbol, source=source)

    def test_concurrent_duplicate_updates_are_serialized(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: self.merge(copy.deepcopy(response(20261116, 20261117))), range(8)))
        self.assertEqual(len(json.loads(self.path.read_text())["bars"]), 2)

    def test_failed_atomic_replace_preserves_existing_file(self):
        from unittest.mock import patch
        self.merge()
        original = self.path.read_bytes()
        with patch.object(cache.os, "replace", side_effect=OSError("模拟磁盘错误")):
            with self.assertRaises(OSError):
                self.merge(response(20261117, 20261118), "2026-11-18")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual({path.suffix for path in self.directory.iterdir()}, {".json", ".lock"})

    def test_cli_roundtrip_and_scan_input(self):
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range(60)]
        payload = response(*(day.isoformat() for day in days))
        args = [sys.executable, str(ROOT / "src" / "market_cache.py"), "merge",
                "--symbol", "US.NVDA", "--through", days[-1].isoformat(),
                "--cache-dir", str(self.directory)]
        merged = subprocess.run(args, input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(merged.returncode, 0, merged.stderr)
        args[2] = "read"
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        read = json.loads(result.stdout)
        cfg = {"ma_fast": 20, "ma_slow": 50, "breakout_lookback_days": 20,
               "volume_lookback_days": 20, "bb_period": 20, "bb_stddev": 2,
               "macd_cross_max_age_days": 2, "volume_multiple": 1.2,
               "rsi_max": 75, "percent_b_max": 1}
        scan = subprocess.run([sys.executable, str(ROOT / "src" / "scan.py")],
                              input=json.dumps({"cfg": cfg, "bars": {"US.NVDA": read["bars"]}}),
                              text=True, capture_output=True)
        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertIn("US.NVDA", scan.stdout)
        self.assertNotIn("insufficient_bars", scan.stdout)


if __name__ == "__main__":
    unittest.main()
