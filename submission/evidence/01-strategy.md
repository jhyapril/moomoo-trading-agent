# 01 · 策略说明

比赛账户 `5829943` · US$100,000 paper · 交易窗口 2026-11-17 → 2026-11-28 · 提交截止 2026-11-30 23:59 SGT
数值唯一来源：`agent-package/config.yaml`。散文见 `agent-package/STRATEGY.md`。本文只解释逻辑，不重复阈值。

## 一句话

大盘趋势向上时，买入盘中突破近期新高、站上长期均线的高流动性股票，用两段式入场把假突破的代价压到计划仓位的一部分，持有赚动量延续；同一时间用 24 个影子账本在同一个标的池上跑互相冲突的假设，为下一个版本提供证据。

## 为什么是这个策略

- **动量突破是经典右侧策略**，入场条件直接取自 Jason 个人实盘标准：收盘突破阻力、站上 MA50、量比 ≥1.2、RSI <75、%B <1.0。这套标准 2026 年已在实盘使用，不是为比赛临时编的。
- **比赛窗口只有约 8 个交易日**，不可能跑出统计显著的样本。因此本次交付的目标不是"证明策略赚钱"，而是"证明一套 AI 交易系统可以在真实券商接口上被纪律地运行、被诚实地记账、被完整地复盘"。`STRATEGY.md` §3 在开赛前就写明"回测区间：待验证"，没有编数字。
- **入场与不入场都要留痕。** 一个 0 笔交易的比赛周，如果只有"没交易"这个结论，价值为零；如果有 1,260 次程序化判定、每次记录了是哪条门拦下的、拦截距离是多少，那就是可复盘的市场证据。

## 标的与周期

| sleeve | 标的 | 方向 | 结构 |
|---|---|---|---|
| 股票 | `universe.symbols` 14 只（AAPL/MSFT/NVDA/AMD/AVGO/META/GOOGL/MU/TSLA/ISRG/KO/APP/CRWD/TSM） | 只做多 | 两段式：probe → confirm_add |
| 期权 | XSP 指数期权 | 双向 | 只做 defined-risk vertical（bull call / bear put spread），多腿单，不裸卖、不 0DTE |

持有周期为股票波段，可过夜（`cadence.flatten_by = null`），最长 `exits.stock.max_holding_days` 个交易日。

## 入场：两段式

设计意图写在 `STRATEGY.md` §1：**启动日不缺席，同时假突破只亏试探仓那部分。**

### 第一层 · 盘中资格（每次运行对全部 14 只判定，`src/watch.py`）

1. 突破位 = 近 `signal.breakout_lookback_days` 个**已收盘**交易日的最高价
2. 实时价 > MA`signal.ma_slow`，且 MA`signal.ma_fast` > MA`signal.ma_slow`
3. RSI < `signal.rsi_max` 且 %B ≤ `signal.percent_b_max`
4. 财报在 `signal.earnings_blackout_days` 天内不进；**查不到财报日同样不进（fail closed）**
5. ATR`exits.stock.stop_atr_period` 可由已收盘日线算出（止损与股数需要）
6. 已持有该标的、或在 `risk.cooldown_after_stop_minutes` 冷却内，不再建试探仓

2026-11-18 用户决定把前一日收盘的"计划门"删掉，改为盘中全量盯 14 只——理由是"没计划就没事干"的日子读起来像系统没在工作。现在收盘任务只准备数据和突破位，不再准备候选名单。

> 量比与 MACD 不在盘中资格内：盘中量能不可靠，量比留给次日确认；MACD 原本是"金叉 **或** 突破"的 OR 条件，突破已强制，不构成独立过滤。

### 第二层 · 试探仓（计划仓位 × `entry.probe_ratio`）

第一层全部成立后，满足任一条即建仓：

- 连续 `entry.hold_above_breakout_minutes` 分钟（1 分钟收盘价）不收回突破位；**或**
- 实时价 ≥ 突破位 × (1 + `entry.breakout_buffer_pct`)

### 第三层 · 确认加仓（补足 `entry.confirm_ratio`）

次日 `entry.confirm_eval_at` 用当时价近似收盘价评估：价格仍在原突破位上方 **且** 均线/RSI/%B 仍成立 **且** 当日累计量 ≥ `signal.volume_lookback_days` 日均量 × `signal.volume_multiple` → 加满剩余部分；任一条不成立 → 不加仓，试探仓转常规管理。**不得下调门槛，不得补仓摊薄。**

### 时间约束

突破发生在 `entry.late_breakout_after` 之后时，2 小时站稳测试在 `cadence.entry_window` 内做不完，只剩 +buffer 冲高或收盘确认两条路径；两条都不成立则当日不建仓。

## 出场：优先级固定，出场永远先于入场

| 优先级 | 触发 | 口径 |
|---|---|---|
| 1 | 硬止损 | `min(risk.per_trade_stop_pct, exits.stock.stop_atr_mult × ATR / 价格)`，相对**平均成本** |
| 2 | 逻辑失效 | 收盘跌破 MA`exits.stock.thesis_exit_ma` 就走，不等止损 |
| 3 | 止盈 | +`exits.stock.take_profit_pct` |
| 4 | 时间止损 | 持有满 `exits.stock.max_holding_days` 个交易日 |

对试探仓与满仓一视同仁：只建了 25% 不是放宽止损的理由，确认失败也不是降低止损或摊薄的依据。

券商侧限制已实测：`sim_trade_input_order` 只支持 order_type 1=限价 / 3=市价，**无条件止损单**，因此止损以"每轮复查现价、触及时按当日买一可成交限价全量卖出"实现。这是 2026-11-19 那笔真实成交的实际执行路径。

## 仓位方法

波动率目标法：股数 =（账户权益 × `sizing.risk_per_trade_pct`）/ 每股止损距离（美元）。该值是**上限**，按两段式拆分。

- 满仓打止损 = `sizing.risk_per_trade_pct`
- 只建到试探仓时，最坏亏损 ≈ `sizing.risk_per_trade_pct` × `entry.probe_ratio`
- 单只上限 `sizing.max_position_pct`、总敞口上限 `sizing.max_total_exposure_pct`、始终留 `sizing.min_cash_buffer_pct` 现金、并发 `universe.max_open_positions` 只、杠杆 `sizing.max_leverage`

## 成本门（`rules/entry.md` Gate 3.5）

目标幅度必须 ≥ 往返成本 × `cost.min_edge_cost_multiple`。佣金、平台费、SEC 费、TAF、每边 `cost.slippage_bps_per_side` 的推导写在 `backtest/cost-model.md`。**假设未经权威来源核实**：这些是公开标准费率的建模值，不是从比赛账户实际账单读出的——账户费用接口连续 3 日返回 MCP `-32603`，这点在 `04-fills-and-results.md` 里如实登记。

## 治理：数字改哪里

三层职责，2026-11-17 经用户确认：

| 层 | 内容 | 变更授权 |
|---|---|---|
| `config.yaml` | 全部数值，唯一来源 | 只能收紧 skill 上限；放宽需显式批准 |
| `STRATEGY.md` / `rules/` | 论点与流程，**不写具体数字** | 实质变化需同步 skill 并升版本 |
| `skill/challenge-strategy/` | 硬安全底 + agent 行为约束 | 放宽上限必须改 skill 且刻意为之 |

运行中的执行者不得动态放宽自身配置来"让交易发生"。本次比赛全程 0 次阈值改动。
