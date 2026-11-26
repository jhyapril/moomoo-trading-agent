#!/usr/bin/env python3
"""日线计划仓位扫描（STRATEGY.md §4.1）。

stdin 读一行 JSON：{"cfg": {...signal 块...}, "bars": {"US.XXX": {"c": [...], "h": [...], "l": [...], "v": [...]}}}
bars 按时间升序，最后一根是评估日。阈值全部来自 cfg，本文件不写死任何数值；缺 l 时 atr 为空，不影响判定。

输出：CSV 到 stdout（可选 --out 追加写）；每行一个标的，最后打印汇总行。
判定失败不等于错误：一行一个结论，失败项列在 failed 列。
"""

import argparse
import json
import statistics
import sys

CSV_COLS = ["sym", "close", "ma_fast", "ma_slow", "prior_high", "gap",
            "vol_ratio", "rsi", "pb", "macd_age", "atr", "planned", "failed"]


def ema(vals, n):
    k = 2.0 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    if len(gains) < n:
        return None
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(highs, lows, closes, n=14):
    if len(closes) <= n:
        return None
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
               abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def macd_cross_age(closes, max_age):
    if len(closes) < 35:
        return None
    dif = [f - s for f, s in zip(ema(closes, 12), ema(closes, 26))]
    dea = ema(dif, 9)
    for age in range(0, max_age + 1):
        i = len(dif) - 1 - age
        if i < 1:
            return None
        if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            return age
    return None


def scan_one(sym, bars, cfg):
    c, h, v = bars.get("c"), bars.get("h"), bars.get("v")
    need = max(cfg["ma_slow"], cfg["breakout_lookback_days"] + 1,
               cfg["volume_lookback_days"] + 1, cfg["bb_period"], 35)
    if not c or not h or not v or min(len(c), len(h), len(v)) < need:
        return {"sym": sym, "planned": False, "failed": "insufficient_bars"}
    if any(x is None for x in (c[-1], h[-1], v[-1])) or c[-1] <= 0:
        return {"sym": sym, "planned": False, "failed": "missing_field"}

    ma_fast = sum(c[-cfg["ma_fast"]:]) / cfg["ma_fast"]
    ma_slow = sum(c[-cfg["ma_slow"]:]) / cfg["ma_slow"]
    prior_high = max(h[-cfg["breakout_lookback_days"] - 1:-1])
    vol_avg = sum(v[-cfg["volume_lookback_days"] - 1:-1]) / cfg["volume_lookback_days"]
    if vol_avg <= 0:
        return {"sym": sym, "planned": False, "failed": "zero_volume_avg"}
    vol_ratio = v[-1] / vol_avg

    r = rsi(c)
    sd = statistics.pstdev(c[-cfg["bb_period"]:])
    mid = sum(c[-cfg["bb_period"]:]) / cfg["bb_period"]
    pb = None if sd <= 0 else (c[-1] - (mid - cfg["bb_stddev"] * sd)) / (2 * cfg["bb_stddev"] * sd)
    age = macd_cross_age(c, cfg["macd_cross_max_age_days"])
    l = bars.get("l")
    a = atr(h, l, c) if l and len(l) == len(c) else None

    gates = {
        "close>ma_slow": c[-1] > ma_slow,
        "ma_fast>ma_slow": ma_fast > ma_slow,
        "breakout": c[-1] > prior_high,
        "volume": vol_ratio >= cfg["volume_multiple"],
        "rsi": r is not None and r < cfg["rsi_max"],
        "percent_b": pb is not None and pb <= cfg["percent_b_max"],
        # §4.1 第 5 条是"金叉 <= N 天 或 收盘突破阻力"，与第 3 条叠加后突破分支恒真
        "macd": age is not None or c[-1] > prior_high,
    }
    failed = [k for k, ok in gates.items() if not ok]
    return {
        "sym": sym, "close": round(c[-1], 2), "ma_fast": round(ma_fast, 2),
        "ma_slow": round(ma_slow, 2), "prior_high": round(prior_high, 2),
        "gap": round(c[-1] - prior_high, 2), "vol_ratio": round(vol_ratio, 2),
        "rsi": None if r is None else round(r, 1),
        "pb": None if pb is None else round(pb, 3),
        "macd_age": age, "atr": None if a is None else round(a, 2),
        "planned": not failed, "failed": "|".join(failed) or "-",
    }


def fmt(row):
    return ",".join("" if row.get(k) is None else str(row.get(k, "")) for k in CSV_COLS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="CSV 输出路径（追加写，首行带表头）")
    args = ap.parse_args()

    payload = json.load(sys.stdin)
    cfg, bars = payload["cfg"], payload["bars"]
    rows = [scan_one(sym, b, cfg) for sym, b in bars.items()]

    for row in rows:
        print(fmt(row))
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write(",".join(CSV_COLS) + "\n")
            for row in rows:
                f.write(fmt(row) + "\n")

    passed = [r["sym"] for r in rows if r["planned"]]
    print(f"# planned={len(passed)}/{len(rows)} symbols={','.join(passed) or '-'}", file=sys.stderr)


if __name__ == "__main__":
    main()
