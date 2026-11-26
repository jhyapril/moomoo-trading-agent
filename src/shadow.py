#!/usr/bin/env python3
"""影子交易员的虚拟账本（零真实订单）。

  python3 src/shadow.py open   < {"book", "cash", "strategy"}
  python3 src/shadow.py fill   < {"book", "symbol", "side", "qty", "price", "filled_at", "reason", "data_ref"}
  python3 src/shadow.py report [< {"marks": {"US.X": 价格}, "as_of": "..."}]
  python3 src/shadow.py pending --date YYYY-MM-DD   列出尚未读过的盘中快照
  python3 src/shadow.py seen   < {"snapshot": "state/market-data/intraday/<日期>/<HHMM>.json"}

账本只追加到 shadow/ledger.jsonl。费用按 config.yaml 的 cost 块计算；记录时间由工具写入，
晚于成交时间超过 shadow.late_fill_minutes 的成交在报告中标为补记，不计入前瞻样本。
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "shadow" / "ledger.jsonl"
CONFIG = ROOT / "config.yaml"


def config_block(name, path=CONFIG):
    values, inside = {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(rf"^{name}:", line):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break
        match = re.match(r'^\s+(\w+):\s*(?:"([^"]*)"|([-+0-9.eE]+))\s*(#.*)?$', line) if inside else None
        if match:
            values[match.group(1)] = match.group(2) if match.group(2) is not None else float(match.group(3))
    return values


def timestamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须为带时区的 ISO-8601 字符串")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} 必须包含时区")
    return parsed.astimezone(timezone.utc)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少 {name}")
    return value


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须为正的有限数值")
    return value


def fees(side, qty, price, cost):
    total = (max(qty * cost["commission_per_share"], cost["commission_min_per_order"])
             + max(qty * cost["platform_per_share"], cost["platform_min_per_order"]))
    if side == "sell":
        total += qty * price * cost["sec_fee_rate"] + min(qty * cost["taf_per_share"], cost["taf_max_per_order"])
    return round(total, 4)


def open_book(payload, records, now):
    book = text(payload.get("book"), "book")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", book):
        raise ValueError("book 格式无效")
    if any(r["event"] == "open" and r["book"] == book for r in records):
        raise ValueError("账本已存在")
    return {"event": "open", "book": book, "cash": positive(payload.get("cash"), "cash"),
            "strategy": text(payload.get("strategy"), "strategy"), "recorded_at": now.isoformat()}


def fill(payload, records, now, cost):
    book = text(payload.get("book"), "book")
    if not any(r["event"] == "open" and r["book"] == book for r in records):
        raise ValueError("账本不存在，先 open")
    symbol = text(payload.get("symbol"), "symbol")
    if not re.fullmatch(r"US\.[A-Z0-9.]+", symbol):
        raise ValueError("symbol 须为 US.XXX")
    side = payload.get("side")
    if side not in ("buy", "sell"):
        raise ValueError("side 须为 buy 或 sell")
    qty = payload.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError("qty 必须为正整数")
    price = positive(payload.get("price"), "price")
    filled_at = timestamp(payload.get("filled_at"), "filled_at")
    if filled_at > now:
        raise ValueError("不得记录未来成交")
    return {"event": "fill", "book": book, "symbol": symbol, "side": side, "qty": qty,
            "price": price, "fees": fees(side, qty, price, cost), "filled_at": filled_at.isoformat(),
            "recorded_at": now.isoformat(), "reason": text(payload.get("reason"), "reason"),
            "data_ref": payload.get("data_ref")}


def snapshot_files(root, snapshot_dir, day):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("date 须为 YYYY-MM-DD")
    folder = root / snapshot_dir / day
    return sorted(str(p.relative_to(root)) for p in folder.glob("[0-9][0-9][0-9][0-9].json")) if folder.is_dir() else []


def pending(records, root, snapshot_dir, day):
    seen = {r["snapshot"] for r in records if r["event"] == "seen"}
    ready, unreadable = [], []
    for rel in snapshot_files(root, snapshot_dir, day):
        if rel in seen:
            continue
        try:
            json.loads((root / rel).read_text(encoding="utf-8"))
            ready.append(rel)
        except (OSError, ValueError):
            # 负责人可能仍在写入，下一轮再读
            unreadable.append(rel)
    return {"date": day, "pending": ready, "unreadable": unreadable,
            "seen": sum(1 for r in records if r["event"] == "seen" and f"/{day}/" in r["snapshot"])}


def mark_seen(payload, records, now, root, snapshot_dir):
    snapshot = text(payload.get("snapshot"), "snapshot")
    day = snapshot.split("/")[-2] if snapshot.count("/") >= 1 else ""
    if snapshot not in snapshot_files(root, snapshot_dir, day):
        raise ValueError("snapshot 不在快照目录中")
    if any(r["event"] == "seen" and r["snapshot"] == snapshot for r in records):
        raise ValueError("快照已标记为已读")
    return {"event": "seen", "snapshot": snapshot, "recorded_at": now.isoformat()}


def append_event(path, action, payload, now, cost, root=ROOT, snapshot_dir=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        records = [json.loads(line) for line in handle if line.strip()]
        if action == "open":
            event = open_book(payload, records, now)
        elif action == "seen":
            event = mark_seen(payload, records, now, root, snapshot_dir)
        else:
            event = fill(payload, records, now, cost)
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return event


def apply_fill(position, signed, price):
    qty, avg = position
    if qty == 0 or (qty > 0) == (signed > 0):
        new_qty = qty + signed
        return (new_qty, (avg * abs(qty) + price * abs(signed)) / abs(new_qty)), 0.0
    closed = min(abs(qty), abs(signed))
    realized = closed * (price - avg) * (1 if qty > 0 else -1)
    new_qty = qty + signed
    if new_qty == 0:
        return (0, 0.0), realized
    return (new_qty, avg if (new_qty > 0) == (qty > 0) else price), realized


def report(records, marks, late_minutes):
    books = {}
    for r in records:
        if r["event"] == "open":
            books[r["book"]] = {"strategy": r["strategy"], "start_cash": r["cash"], "cash": r["cash"],
                                "positions": {}, "realized_pnl": 0.0, "fees": 0.0,
                                "fills": 0, "late_fills": 0}
        elif r["event"] == "fill":
            b = books[r["book"]]
            signed = r["qty"] if r["side"] == "buy" else -r["qty"]
            b["positions"][r["symbol"]], realized = apply_fill(
                b["positions"].get(r["symbol"], (0, 0.0)), signed, r["price"])
            b["realized_pnl"] += realized
            b["fees"] += r["fees"]
            b["cash"] -= signed * r["price"] + r["fees"]
            b["fills"] += 1
            lag = timestamp(r["recorded_at"], "recorded_at") - timestamp(r["filled_at"], "filled_at")
            b["late_fills"] += lag.total_seconds() > late_minutes * 60
    out = {}
    for name, b in books.items():
        positions, unrealized, value, complete = {}, 0.0, 0.0, True
        for sym, (qty, avg) in b["positions"].items():
            if qty == 0:
                continue
            mark = marks.get(sym)
            pnl = None if mark is None else (mark - avg) * qty
            complete &= mark is not None
            if mark is not None:
                unrealized += pnl
                value += mark * qty
            positions[sym] = {"qty": qty, "avg_cost": round(avg, 4), "mark": mark,
                              "unrealized_pnl": None if pnl is None else round(pnl, 2)}
        equity = b["cash"] + value if complete else None
        out[name] = {
            "strategy": b["strategy"], "start_cash": b["start_cash"], "cash": round(b["cash"], 2),
            "positions": positions, "realized_pnl": round(b["realized_pnl"], 2),
            "unrealized_pnl": round(unrealized, 2) if complete else None,
            "fees": round(b["fees"], 2), "equity": None if equity is None else round(equity, 2),
            "return_pct": None if equity is None else round((equity / b["start_cash"] - 1) * 100, 3),
            "fills": b["fills"], "late_fills": b["late_fills"],
        }
    return {"books": out, "paper_orders": 0,
            "evidence_limit": "假设成交，非真实撮合；少量样本不能证明策略有效，补记成交不计入前瞻样本。"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("open", "fill", "report", "pending", "seen"))
    parser.add_argument("--date", help="pending 使用的纽约交易日 YYYY-MM-DD")
    args = parser.parse_args()
    try:
        settings = config_block("shadow")
        if args.action in ("report", "pending"):
            records = []
            if LEDGER.exists():
                with LEDGER.open(encoding="utf-8") as handle:
                    fcntl.flock(handle, fcntl.LOCK_SH)
                    records = [json.loads(line) for line in handle if line.strip()]
            if args.action == "pending":
                output = pending(records, ROOT, settings["snapshot_dir"], text(args.date, "--date"))
            else:
                raw = sys.stdin.read() if not sys.stdin.isatty() else ""
                payload = json.loads(raw) if raw.strip() else {}
                output = report(records, payload.get("marks", {}), settings["late_fill_minutes"])
                output["as_of"] = payload.get("as_of")
        else:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("输入必须为 JSON 对象")
            if args.action == "open" and payload.get("cash") is None:
                payload["cash"] = settings["default_book_cash"]
            output = append_event(LEDGER, args.action, payload, datetime.now(timezone.utc),
                                  config_block("cost"), ROOT, settings["snapshot_dir"])
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
