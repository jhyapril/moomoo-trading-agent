#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sys
import time

LOCK = Path(__file__).resolve().parents[1] / "state" / "intraday-run.lock"


def acquire(path, owner, stale_seconds, now=None):
    now = time.time() if now is None else now
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = json.loads(path.read_text() or "{}")
            age = now - held.get("acquired_at", 0)
            if age < stale_seconds:
                return dict(acquired=False, holder=held.get("owner"), age_seconds=round(age))
            # 持有者超时视为崩溃遗留，接管前先删除
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as handle:
            json.dump(dict(owner=owner, acquired_at=now), handle)
        return dict(acquired=True, owner=owner)
    return dict(acquired=False, holder=None, age_seconds=None)


def release(path, owner):
    if not path.exists():
        return dict(released=False, reason="not_held")
    held = json.loads(path.read_text() or "{}")
    if held.get("owner") != owner:
        return dict(released=False, reason="held_by_other", holder=held.get("owner"))
    path.unlink()
    return dict(released=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("acquire", "release"))
    parser.add_argument("--owner", required=True)
    parser.add_argument("--stale-seconds", type=int, default=900)
    parser.add_argument("--lock", type=Path, default=LOCK)
    args = parser.parse_args()
    if args.action == "acquire":
        result = acquire(args.lock, args.owner, args.stale_seconds)
        ok = result["acquired"]
    else:
        result = release(args.lock, args.owner)
        ok = result["released"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
