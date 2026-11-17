# STRATEGY.md — Moomoo × Qoder 交易比赛策略

比赛账户：US$100,000 模拟（paper）账户。交易窗口 2026-11-17 至 2026-11-28（约 8 个美股交易日）。提交截止 2026-11-30 23:59 SGT。

## §1 论点

大盘趋势向上时，买入收盘突破近期新高、站上长期均线的高流动性大盘股，持有至多 `exits.stock.max_holding_days` 个交易日，赚动量延续。期权 sleeve 只做 XSP 的 defined-risk 价差（多腿单已实测可用），不做裸卖、不做 0DTE。LLM 只做信号筛选与复盘，不直接下单；所有订单走代码门控与风控检查。

## §2 标的与周期

- 股票 sleeve（只做多）：`universe.symbols`
- 期权 sleeve：`universe.options.underlying`（XSP 指数期权），只做 `universe.options.structures` 内的 defined-risk vertical，多腿单执行
- 持有周期：股票波段，最长 `exits.stock.max_holding_days` 个交易日，可过夜（`cadence.flatten_by` 为 `null`）
- XSP 不做股票，只做期权

## §3 证据

| 项目 | 内容 |
|---|---|
| 回测区间 | 待验证（本次比赛窗口仅约 8 个交易日，未跑完整回测） |
| 样本量 | 待验证 |
| 凭什么相信 | 动量突破是经典右侧策略；入场条件取自 Jason 个人实盘标准（MACD 金叉 / 收盘突破阻力、站上 MA50、量比 ≥1.2、RSI <75、%B <1.0），该标准 2026 年已在实盘中使用 |
| 什么情况下会失效 | 横盘震荡市连续假突破；大盘系统性下跌（指数跌破 MA50）；财报夜波动；流动性枯竭 |

没回测就写待验证，不编数字。先在 `backtest/` 按 README 的标准验证，通过了才开工交易。

## §4 入场条件

信号按收盘价判断，下一交易日在 `cadence.entry_window`（`cadence.timezone`）内执行。股票入场需全部满足：

1. 收盘价 > MA`signal.ma_slow`，且 MA`signal.ma_fast` > MA`signal.ma_slow`
2. 收盘突破近 `signal.breakout_lookback_days` 日最高价
3. 成交量 ≥ `signal.volume_lookback_days` 日均量 × `signal.volume_multiple`
4. RSI < `signal.rsi_max`，且 %B < `signal.percent_b_max`（BB `signal.bb_period` 日、`signal.bb_stddev` 倍标准差）
5. MACD 金叉在 `signal.macd_cross_max_age_days` 天内，或收盘突破阻力
6. 财报在 `signal.earnings_blackout_days` 天内不进（例：NVDA 2026-11-17 盘后财报，当天不进 NVDA）

XSP vertical 入场（择一方向，需全部满足）：

- Bull call spread：SPX/XSP 日线收盘 > MA`signal.ma_slow` 且 MA`signal.ma_fast` > MA`signal.ma_slow`，RSI < `options.max_rsi`；买入平值附近 call、卖出高一档 call，净借方
- Bear put spread：日线收盘 < MA`signal.ma_slow` 且 MA`signal.ma_fast` < MA`signal.ma_slow`，RSI > `options.min_rsi`；买入平值附近 put、卖出低一档 put，净借方
- 只做 defined-risk（最大亏损 = 净借方），剩余到期 ≥ `options.min_days_to_expiry` 天，不做 0DTE

## §5 出场条件

股票出场（任一触发即走，出场永远优先于入场）：

- 止损：`risk.per_trade_stop_pct` 或 `exits.stock.stop_atr_mult`×ATR`exits.stock.stop_atr_period`，取更近者即 `min()`
- 目标：+`exits.stock.take_profit_pct`
- 时间止损：持有满 `exits.stock.max_holding_days` 个交易日
- 逻辑失效：收盘跌破 MA`exits.stock.thesis_exit_ma` 就走，不等止损

XSP vertical 出场：

- 止损：亏损达到净借方的 `exits.options.stop_loss_pct_of_debit`（价差价值剩一半）即平仓
- 目标：价差价值达到净借方的 `exits.options.take_profit_multiple` 倍即平仓
- 时间止损：到期前 `exits.options.close_before_expiry_days` 个交易日平仓，不持有到期
- 逻辑失效：标的收盘反向突破 MA`exits.options.thesis_exit_ma` 即平仓

## §6 仓位方法

本节只写方法，数字以 `config.yaml` 为准。

波动率目标仓位法：股数 =（账户权益 × `sizing.risk_per_trade_pct`）/ 每股止损距离（美元）。

- 单笔风险 `sizing.risk_per_trade_pct`（占账户权益）
- 单只上限 `sizing.max_position_pct`，总仓位上限 `sizing.max_total_exposure_pct`，始终留 `sizing.min_cash_buffer_pct` 现金
- 同时最多 `universe.max_open_positions` 只，各 sleeve 共享
- 杠杆 `sizing.max_leverage`

## §7 停止条件

除默认的日亏 / 回撤外：

- 单日亏损达 `risk.max_daily_loss_pct` 即停手平仓，当日不再开新仓
- 从峰值回撤 `risk.max_drawdown_pct` 即禁用策略（熔断），人工复盘后才能恢复
- 连续 `risk.max_consecutive_failed_breakouts` 次假突破（入场后 `risk.failed_breakout_window_days` 日内触发止损或逻辑失效）即停手复盘，当日不再开新仓
- 账户、数据、对账任一异常即停手

## §8 复盘节奏

- 每天收盘后写 journal/YYYY-MM-DD.md：决策、订单、成交、盈亏、违规
- 每周复盘一次：胜率、盈亏比、假突破次数、风控触发情况
- 比赛结束（11/28）后写总结：策略是否有效、哪些条件要改、能否复用到实盘
