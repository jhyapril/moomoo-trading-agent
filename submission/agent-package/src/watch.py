#!/usr/bin/env python3
"""盘中全量盯盘判定（STRATEGY.md §4.1、§4.2、§4.4）。

stdin 读一行 JSON：
{"cfg": {...signal 块...}, "entry": {...entry 块...},
 "bars": {"US.XXX": {"c": [...], "h": [...], "l": [...], "v": [...]}},   # 已收盘日线，升序，截止上一交易日
 "live": {"US.XXX": {"price": 1.0, "volume": 1, "data_time": "...",       # 常规时段实时价与当日累计量
                     "minute_closes": [...], "as_of": "HH:MM",            # 当日自开盘起全部 1 分钟收盘价升序；末根纽约时间
                     "earnings_ok": true}}}                               # 财报门结论
触发：surge 冲高；hold 连续站稳；close 为突破晚于 late_breakout_after 时于 confirm_eval_at 后的收盘确认。
阈值全部来自 cfg/entry，本文件不写死数值。缺 live、缺 earnings_ok 或数据不足一律不触发。
"""

import argparse
import json
import statistics
import sys

from scan import atr, rsi

COLS = ["sym", "price", "prior_high", "gap_pct", "ma_fast", "ma_slow", "rsi", "pb",
        "vol_ratio", "atr", "held_minutes", "surge", "qualified", "trigger", "failed"]


def _minutes(hhmm):
    if not isinstance(hhmm, str) or ":" not in hhmm:
        return None
    hh, mm = hhmm.split(":")[:2]
    return int(hh) * 60 + int(mm)


def held_minutes(minute_closes, level):
    n = 0
    for close in reversed(minute_closes or []):
        if close is None or close <= level:
            break
        n += 1
    return n


def watch_one(sym, bars, live, cfg, entry):
    c, h, l, v = (bars.get(k) for k in ("c", "h", "l", "v"))
    need = max(cfg["ma_slow"], cfg["breakout_lookback_days"], cfg["volume_lookback_days"],
               cfg["bb_period"], 15)
    if not c or not h or not v or min(len(c), len(h), len(v)) < need:
        return {"sym": sym, "qualified": False, "trigger": "-", "failed": "insufficient_bars"}
    prior_high = max(h[-cfg["breakout_lookback_days"]:])
    price = (live or {}).get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return {"sym": sym, "prior_high": round(prior_high, 4), "qualified": False,
                "trigger": "-", "failed": "missing_live_price"}

    closes = c + [price]
    ma_fast = sum(closes[-cfg["ma_fast"]:]) / cfg["ma_fast"]
    ma_slow = sum(closes[-cfg["ma_slow"]:]) / cfg["ma_slow"]
    r = rsi(closes)
    window = closes[-cfg["bb_period"]:]
    sd = statistics.pstdev(window)
    mid = sum(window) / cfg["bb_period"]
    pb = None if sd <= 0 else (price - (mid - cfg["bb_stddev"] * sd)) / (2 * cfg["bb_stddev"] * sd)
    vol_avg = sum(v[-cfg["volume_lookback_days"]:]) / cfg["volume_lookback_days"]
    live_vol = live.get("volume")
    vol_ratio = live_vol / vol_avg if isinstance(live_vol, (int, float)) and vol_avg > 0 else None
    a = atr(h, l, c) if l and len(l) == len(c) else None
    held = held_minutes(live.get("minute_closes"), prior_high)
    surge = price >= prior_high * (1 + entry["breakout_buffer_pct"])

    gates = {
        "price>breakout": price > prior_high,
        "price>ma_slow": price > ma_slow,
        "ma_fast>ma_slow": ma_fast > ma_slow,
        "rsi": r is not None and r < cfg["rsi_max"],
        "percent_b": pb is not None and pb <= cfg["percent_b_max"],
        "earnings": live.get("earnings_ok") is True,
        "atr": a is not None,
    }
    failed = [k for k, ok in gates.items() if not ok]
    qualified = not failed
    trigger = "-"
    as_of = _minutes(live.get("as_of"))
    if qualified and surge:
        trigger = "surge"
    elif qualified and held >= entry["hold_above_breakout_minutes"]:
        trigger = "hold"
    elif (qualified and held > 0 and as_of is not None
          and as_of >= _minutes(entry["confirm_eval_at"])
          and as_of - held >= _minutes(entry["late_breakout_after"])):
        trigger = "close"
    return {
        "sym": sym, "price": price, "prior_high": round(prior_high, 4),
        "gap_pct": round((price / prior_high - 1) * 100, 2),
        "ma_fast": round(ma_fast, 2), "ma_slow": round(ma_slow, 2),
        "rsi": None if r is None else round(r, 1), "pb": None if pb is None else round(pb, 3),
        "vol_ratio": None if vol_ratio is None else round(vol_ratio, 2),
        "atr": None if a is None else round(a, 4), "held_minutes": held, "surge": surge,
        "qualified": qualified, "trigger": trigger, "failed": "|".join(failed) or "-",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="CSV 追加写路径，首行带表头")
    args = ap.parse_args()
    payload = json.load(sys.stdin)
    cfg, entry, live = payload["cfg"], payload["entry"], payload.get("live", {})
    rows = [watch_one(sym, b, live.get(sym), cfg, entry) for sym, b in payload["bars"].items()]
    lines = [",".join("" if r.get(k) is None else str(r.get(k)) for k in COLS) for r in rows]
    print("\n".join(lines))
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write(",".join(COLS) + "\n")
            f.write("\n".join(lines) + "\n")
    fired = [f"{r['sym']}:{r['trigger']}" for r in rows if r["trigger"] != "-"]
    print(f"# triggered={len(fired)}/{len(rows)} {','.join(fired) or '-'}", file=sys.stderr)


if __name__ == "__main__":
    main()
