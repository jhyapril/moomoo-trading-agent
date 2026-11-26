import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run_lock  # noqa: E402


class RunLockTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lock = Path(self.dir.name) / "state" / "run.lock"

    def tearDown(self):
        self.dir.cleanup()

    def test_second_holder_blocked_until_stale(self):
        self.assertTrue(run_lock.acquire(self.lock, "a", 900, now=1000)["acquired"])
        blocked = run_lock.acquire(self.lock, "b", 900, now=1500)
        self.assertFalse(blocked["acquired"])
        self.assertEqual(blocked["holder"], "a")
        self.assertTrue(run_lock.acquire(self.lock, "b", 900, now=2000)["acquired"])

    def test_release_only_by_owner(self):
        run_lock.acquire(self.lock, "a", 900, now=1000)
        self.assertFalse(run_lock.release(self.lock, "b")["released"])
        self.assertTrue(run_lock.release(self.lock, "a")["released"])
        self.assertFalse(run_lock.release(self.lock, "a")["released"])
        self.assertTrue(run_lock.acquire(self.lock, "c", 900, now=1001)["acquired"])


if __name__ == "__main__":
    unittest.main()
