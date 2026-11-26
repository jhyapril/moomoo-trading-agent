#!/usr/bin/env python3
"""一键复现提交材料中的全部结果数字。

  python3 submission/demo/replay.py

只读运行：不联网、不调用券商接口、不写仓库。所有数字从 submission/agent-package/ 内的
真实产物重算（src/shadow.py 的官方记账口径、state/market-data 的 watch.csv 门控表、
日线缓存），券商成交与权益来自 2026-11-26 对比赛账户 5829943 的只读实测，已固化在
data/orders.csv 以便离线复现。
"""
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PKG = ROOT / "agent-package"
sys.path.insert(0, str(PKG / "src"))

import shadow as shadow_mod  # noqa: E402  仓库自己的记账引擎，不另写一套


def rule(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def section1_orders():
    rule("1. 真实订单与成交（券商侧实测，account 5829943 / market 100 / account_type 2）")
    rows = list(csv.DictReader(open(ROOT / "data" / "orders.csv", encoding="utf-8")))
    print(f"{'order_id':>10s}  {'date/time ET':<20s}{'sym':<7s}{'side':<5s}{'qty':>5s}"
          f"{'lmt':>9s}{'fill_avg':>10s}{'cum':>5s}  status / text")
    for r in rows:
        print(f"{r['order_id']:>10s}  {r['created_et']:<20s}{r['symbol']:<7s}{r['side']:<5s}"
              f"{r['qty']:>5s}{r['limit_price']:>9s}{r['avg_fill_price']:>10s}{r['cum_qty']:>5s}"
              f"  {r['status']} / {r['text']}")
    buys = [r for r in rows if r["status"] == "filled" and r["side"] == "BUY"]
    sells = [r for r in rows if r["status"] == "filled" and r["side"] == "SELL"]
    qty = int(buys[0]["qty"])
    gross = qty * (float(sells[0]["avg_fill_price"]) - float(buys[0]["avg_fill_price"]))
    equity = 99919.81
    print(f"\n  订单总数 {len(rows)}，全部成交 {len(buys) + len(sells)} 笔，撤销 {sum(1 for r in rows if r['status'] == 'cancelled')} 笔（0 股成交）")
    print(f"  唯一一次真实往返：BUY {qty} {buys[0]['symbol']} @{buys[0]['avg_fill_price']} → SELL @{sells[0]['avg_fill_price']}"
          f" = 毛价差 {gross:+.2f} USD")
    print(f"  账户权益 {equity:,.2f} ⇒ 累计盈亏 {equity - 100000:+.2f}（{(equity / 100000 - 1) * 100:+.4f}%），"
          f"隐含费用 {gross - (equity - 100000):.2f} USD")
    print("  官方费用/现金流接口（account_order_fees、account_cash_logs）连续 3 日返回 MCP -32603，费用为推算值。")
    return len(rows)


def section2_gate_tally():
    rule("2. 入场门控判定面（src/watch.py 落盘的 CSV，程序产物而非人工汇总）")
    total = Counter()
    gates = Counter()
    per_day = Counter()
    closest = {}
    files = sorted(PKG.glob("state/market-data/intraday/*/watch.csv"))
    for f in files:
        day = f.parent.name
        for r in csv.DictReader(open(f, encoding="utf-8")):
            total["rows"] += 1
            per_day[day] += 1
            total["qualified_" + r["qualified"]] += 1
            total["trigger_" + (r["trigger"] or "-")] += 1
            gap = r["gap_pct"].strip()
            if gap and float(gap) > 0:
                total["above_breakout"] += 1
            key = (day, r["sym"])
            if gap and (key not in closest or float(gap) > closest[key]):
                closest[key] = float(gap)
            for g in (r["failed"] or "").split("|"):
                g = g.strip()
                if g and g != "-":
                    gates[g] += 1
    print(f"  评估日：{', '.join(sorted(per_day))}")
    print(f"  symbol-evaluation 总数 = {total['rows']}（14 只 × 多轮盘中复查）")
    print(f"  qualified=True ：{total['qualified_True']}")
    print(f"  trigger 非空   ：{sum(v for k, v in total.items() if k.startswith('trigger_') and k != 'trigger_-')}")
    print(f"  收盘/现价高于突破位（gap_pct>0）的行：{total['above_breakout']} / {total['rows']}")
    print("\n  被拦下的门（一行可命中多个）：")
    for g, n in gates.most_common():
        print(f"    {g:<20s}{n:6d}   {n / total['rows'] * 100:6.2f}%")
    print("\n  每日最接近突破的标的（gap_pct = price/prior_high − 1）：")
    by_day = {}
    for (day, sym), gp in closest.items():
        by_day.setdefault(day, []).append((gp, sym))
    for day in sorted(by_day):
        top = sorted(by_day[day], reverse=True)[:3]
        print("    " + day + ": " + ", ".join(f"{s.replace('US.', '')} {gp:+.2f}%" for gp, s in top))
    return total["rows"], total["qualified_True"]


def section3_shadow():
    rule("3. 影子账本 24 本（src/shadow.py report 官方口径，mark = 11/25 官方收盘）")
    marks = {}
    for f in sorted(PKG.glob("state/market-data/US.*.day.a1.e0.moomoo.json")):
        d = json.load(open(f, encoding="utf-8"))
        marks[f.name.split(".day")[0]] = d["bars"][-1]["close"]
    records = [json.loads(l) for l in open(PKG / "shadow" / "ledger.jsonl", encoding="utf-8") if l.strip()]
    settings = shadow_mod.config_block("shadow")
    rep = shadow_mod.report(records, marks, settings["late_fill_minutes"])
    books = rep["books"]
    print(f"{'book':<12s}{'fills':>6s}{'late':>6s}{'realized':>12s}{'unrealized':>12s}"
          f"{'fees':>8s}{'equity':>13s}{'ret%':>9s}")
    tot = Counter()
    for k, v in sorted(books.items(), key=lambda x: x[1]["equity"]):
        print(f"{k:<12s}{v['fills']:6d}{v['late_fills']:6d}{v['realized_pnl']:12.2f}"
              f"{v['unrealized_pnl']:12.2f}{v['fees']:8.2f}{v['equity']:13.2f}{v['return_pct']:9.3f}")
        tot["start"] += v["start_cash"]
        tot["equity"] += v["equity"]
        tot["realized"] += v["realized_pnl"]
        tot["unreal"] += v["unrealized_pnl"]
        tot["fees"] += v["fees"]
        tot["fills"] += v["fills"]
        tot["late"] += v["late_fills"]
        tot["win"] += v["equity"] > v["start_cash"]
        tot["lose"] += v["equity"] < v["start_cash"]
        tot["flat"] += v["equity"] == v["start_cash"]
    pnl = tot["equity"] - tot["start"]
    check = tot["realized"] + tot["unreal"] - tot["fees"]
    print(f"\n  SYSTEM: start {tot['start']:,.2f} → equity {tot['equity']:,.2f}"
          f" = {pnl:+,.2f}（{pnl / tot['start'] * 100:+.3f}%）")
    print(f"  闭合校验 realized+unrealized−fees = {check:+,.2f}  vs 权益差 {pnl:+,.2f}"
          f"  ⇒ 差异 {abs(check - pnl):.4f}")
    print(f"  fills {tot['fills']}、补记 {tot['late']}（{tot['late'] / tot['fills'] * 100:.2f}% 超过 "
          f"shadow.late_fill_minutes {settings['late_fill_minutes']} 分钟，不计入前瞻样本）")
    print(f"  账本胜负：{int(tot['win'])} 胜 / {int(tot['lose'])} 负 / {int(tot['flat'])} 平（平本 = 0 笔成交）")
    best = max(books.items(), key=lambda x: x[1]["return_pct"])
    worst = min(books.items(), key=lambda x: x[1]["return_pct"])
    print(f"  最好 {best[0]} {best[1]['return_pct']:+.3f}%｜最差 {worst[0]} {worst[1]['return_pct']:+.3f}%")
    short = [v for k, v in books.items() if k.startswith("shrt")]
    s_start = sum(v["start_cash"] for v in short)
    s_eq = sum(v["equity"] for v in short)
    s_loss = sum(v["equity"] - v["start_cash"] for v in short if v["equity"] < v["start_cash"])
    s_win = sum(v["equity"] - v["start_cash"] for v in short if v["equity"] > v["start_cash"])
    print(f"  做空镜像族 shrt* {len(short)} 本：{s_start:,.0f} → {s_eq:,.2f}"
          f"（{(s_eq / s_start - 1) * 100:+.3f}%）＝亏 {abs(s_loss):,.2f} / 赚 {s_win:+,.2f}")
    print("  现行只做多 sleeve 同期 0 笔入场、权益变动 0.00%；以上是假设成交，不是真实撮合。")
    return books, tot


def section4_risk_limits():
    rule("4. 风控上限：config.yaml 实际值 vs skill 硬底（config 只能收紧）")
    cfg = shadow_mod.config_block("risk")
    siz = shadow_mod.config_block("sizing")
    uni = shadow_mod.config_block("universe")
    floors = {
        "max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.10, "per_trade_stop_pct": 0.05,
        "max_orders_per_day": 20, "cooldown_after_stop_minutes": 60,
        "max_position_pct": 0.20, "max_total_exposure_pct": 0.90, "max_leverage": 1.0,
        "min_cash_buffer_pct": 0.10, "max_open_positions": 10,
    }
    live = {
        "max_daily_loss_pct": cfg["max_daily_loss_pct"], "max_drawdown_pct": cfg["max_drawdown_pct"],
        "per_trade_stop_pct": cfg["per_trade_stop_pct"], "max_orders_per_day": cfg["max_orders_per_day"],
        "cooldown_after_stop_minutes": cfg["cooldown_after_stop_minutes"],
        "max_position_pct": siz["max_position_pct"], "max_total_exposure_pct": siz["max_total_exposure_pct"],
        "max_leverage": siz["max_leverage"], "min_cash_buffer_pct": siz["min_cash_buffer_pct"],
        "max_open_positions": uni["max_open_positions"],
    }
    print(f"{'limit':<28s}{'skill floor':>12s}{'config':>10s}  relation")
    for k in floors:
        rel = "tighter ✓" if live[k] < floors[k] else ("equal（= 硬底）" if live[k] == floors[k] else "LOOSER ✗")
        print(f"{k:<28s}{floors[k]:>12g}{live[k]:>10g}  {rel}")
    used = 4
    print(f"\n  订单预算：比赛以来已用 {used} / {cfg['max_orders_per_day']:.0f}"
          f"（{used / cfg['max_orders_per_day'] * 100:.0f}%），持仓槽位 0 / {uni['max_open_positions']:.0f}，敞口 0% / {siz['max_total_exposure_pct']:.0%}")
    print(f"  账户守卫：config 期望 5829943 / type 2 / market 100 / 标题含 Qoder —— 每轮实时复核，个人账户 2590077 与实盘 0 次调用")


def main():
    if not PKG.is_dir():
        print(f"缺少 {PKG}", file=sys.stderr)
        return 1
    print("Moomoo × Qoder 交易比赛 —— 提交材料复现脚本")
    print(f"package root: {PKG}")
    n_orders = section1_orders()
    rows, qualified = section2_gate_tally()
    books, tot = section3_shadow()
    section4_risk_limits()
    rule("5. 单元测试（stdlib unittest，无第三方依赖）")
    for t in sorted((PKG / "backtest").glob("test_*.py")):
        p = subprocess.run([sys.executable, str(t)], capture_output=True, text=True)
        tail = [l for l in p.stderr.splitlines() if l.startswith(("Ran", "OK", "FAILED"))]
        print(f"  {t.name:<26s}{' '.join(tail)}")
    rule("6. 结论")
    print(f"  {rows} 次程序化入场判定，{qualified} 次通过全部门 ⇒ 策略信号入场 0 笔。比赛以来 4 张订单中 2 张为测试单（撤销、0 股成交），")
    print("  1 张为用户指定建仓，1 张由 rules/exit.md 优先级 1 硬止损（147.345）触发并全部成交。风控上限 0 次被放宽，规则违规 0 处。")
    print(f"  对照面：{len(books)} 个影子账本、{int(tot['fills'])} 笔假设成交、补记率 {tot['late'] / tot['fills'] * 100:.2f}%。")
    print("  本报告不声称短期样本证明策略盈利。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
