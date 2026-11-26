# STRATEGY.md — Moomoo × Qoder 交易比赛策略

比赛账户：US$100,000 模拟（paper）账户。交易窗口 2026-11-17 至 2026-11-28（约 8 个美股交易日）。提交截止 2026-11-30 23:59 SGT。

## §1 论点

大盘趋势向上时，买入盘中突破近期新高、站上长期均线的高流动性股票，持有至多 `exits.stock.max_holding_days` 个交易日，赚动量延续。盘中对 `universe.symbols` 全部标的轮询，不再要求前一日收盘已入选计划。入场分两段：盘中试探 `entry.probe_ratio`，次日确认后再加 `entry.confirm_ratio`——启动日不缺席，假突破也只亏试探仓那部分。期权 sleeve 只做 XSP 的 defined-risk 价差（多腿单已实测可用），不做裸卖、不做 0DTE。数据、风控和研究 Agent 只提交分析；订单仅由唯一执行者按 Skill 门控与风控检查发送。目前执行由提示词与 Skill 编排，不把它描述为已实现的代码交易引擎。

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

股票 sleeve 采用两段式入场：先试探、后确认。目的是启动日不缺席，同时把假突破的代价压到
计划仓位的 `entry.probe_ratio`。

### 4.1 盘中资格（每次运行对全部标的判定）

2026-11-18 用户决定：盘中直接盯 `universe.symbols` 全部标的，不再以"前一日收盘已突破"作为
前置计划。每次运行用截止上一交易日的已收盘日线加本次实时价（视作当日临时收盘）判定：

1. **突破位** = 近 `signal.breakout_lookback_days` 个已收盘交易日的最高价
2. 实时价 > MA`signal.ma_slow`，且 MA`signal.ma_fast` > MA`signal.ma_slow`（均线含实时价）
3. RSI < `signal.rsi_max`，且 %B ≤ `signal.percent_b_max`（BB `signal.bb_period` 日、`signal.bb_stddev` 倍标准差，含实时价）
4. 财报在 `signal.earnings_blackout_days` 天内不进；查不到财报日同样不进（fail closed）
5. ATR`exits.stock.stop_atr_period` 可由已收盘日线算出（止损与股数需要）
6. 已持有该标的、或在 `risk.cooldown_after_stop_minutes` 止损冷却内，不再建试探仓

计划仓位股数在触发时按 §6 算，是**上限**，不是立即买入 100%。判定由 `src/watch.py` 完成。

> 量比与 MACD 不在盘中资格内：盘中量能不可靠，量比留给次日确认；MACD 原本是"金叉或突破"
> 的 OR 条件，突破已强制，故不构成独立过滤。

### 4.2 试探仓（计划仓位 × `entry.probe_ratio`）

§4.1 全部成立时，满足任一条即建试探仓：

- 连续 `entry.hold_above_breakout_minutes` 分钟（1 分钟收盘价）不收回突破位；或
- 实时价 ≥ 突破位 × (1 + `entry.breakout_buffer_pct`)

**不要求** `signal.volume_multiple` 量比。

### 4.3 确认加仓（补足 `entry.confirm_ratio`）

次日 `entry.confirm_eval_at` 用当时价近似收盘价评估：

- 价格仍在原突破位上方，**且** §4.1 第 2–4 条成立，**且**当日累计量 ≥
  `signal.volume_lookback_days` 日均量 × `signal.volume_multiple` → 加满剩余 `entry.confirm_ratio`
- 任一条不成立 → 不加仓；试探仓转由 §5 常规管理。不得下调门槛，不得补仓摊薄

### 4.4 时间约束

- 突破发生在 `entry.late_breakout_after` 之后时，`entry.hold_above_breakout_minutes` 的测试在
  `cadence.entry_window` 内做不完
- 此时只剩两条路径：+`entry.breakout_buffer_pct` 冲高触发；或等到收盘评估时点，若价格仍在
  突破位上方，以该收盘确认替代 2 小时测试，建试探仓
- 两条都不成立则当日不建仓

### 4.5 记录与去重

- 试探仓规则 id 为 `probe`，确认加仓为 `confirm_add`；各自记 journal、各自去重
- 两笔都计入 `risk.max_orders_per_day`，并各自单独通过 `rules/risk.md` 的全部检查

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

以上对试探仓与满仓一视同仁：止损相对**平均成本**。只建了 25% 不是放宽止损的理由；
确认失败也不是降低止损或摊薄的依据。

XSP vertical 出场：

- 止损：亏损达到净借方的 `exits.options.stop_loss_pct_of_debit`（价差价值剩一半）即平仓
- 目标：价差价值达到净借方的 `exits.options.take_profit_multiple` 倍即平仓
- 时间止损：到期前 `exits.options.close_before_expiry_days` 个交易日平仓，不持有到期
- 逻辑失效：标的收盘反向突破 MA`exits.options.thesis_exit_ma` 即平仓

## §6 仓位方法

本节只写方法，数字以 `config.yaml` 为准。

波动率目标仓位法：股数 =（账户权益 × `sizing.risk_per_trade_pct`）/ 每股止损距离（美元）。
该股数是**计划仓位**，按 §4 拆成两笔：试探仓 = 计划仓位 × `entry.probe_ratio`，确认加仓 =
计划仓位 × `entry.confirm_ratio`。

- 风险预算按**计划仓位**计算：满仓打止损 = `sizing.risk_per_trade_pct`
- 只建到试探仓时，最坏亏损 ≈ `sizing.risk_per_trade_pct` × `entry.probe_ratio`
- 单笔风险 `sizing.risk_per_trade_pct`（占账户权益）
- 单只上限 `sizing.max_position_pct`，总仓位上限 `sizing.max_total_exposure_pct`，始终留 `sizing.min_cash_buffer_pct` 现金
- 同时最多 `universe.max_open_positions` 只，各 sleeve 共享
- 杠杆 `sizing.max_leverage`

## §7 停止条件

除默认的日亏 / 回撤外：

- 单日亏损达 `risk.max_daily_loss_pct` 即停手平仓，当日不再开新仓
- 从峰值回撤 `risk.max_drawdown_pct` 即禁用策略（熔断），人工复盘后才能恢复
- 连续 `risk.max_consecutive_failed_breakouts` 次假突破（试探仓建仓后 `risk.failed_breakout_window_days` 日内触发止损或逻辑失效，计一次）即停手复盘，当日不再开新仓；确认失败但没有止损的，不计入
- 账户、数据、对账任一异常即停手

## §8 复盘节奏

- 每天收盘后写 journal/YYYY-MM-DD.md：决策、订单、成交、盈亏、违规
- 影子交易员独立运作（2026-11-19 用户要求）：有自己的定时任务，不占用买入决策会话；协调者每轮把
  数据员的价格数据无条件存档到快照目录，影子交易员异步读取，也可自行读取全部缓存与行情；在 `shadow/`
  自建多个虚拟账本，各自代表一套策略，用假设买卖成交记账，不受现行策略门控与风控上限约束，目的是
  为优化本策略提供对照。唯一边界：零真实订单、不改正式策略文件。
  账本与笔记契约见 Skill 作战手册的影子研究部分。
- 盘后影子交易员在自己的复盘任务中对比各账本与比赛账户同期收益扣费用、回撤、交易次数与胜率，
  指出导致差异的规则，给出具体改进建议，写在 `shadow/notes/`；协调者收盘任务只提供比赛账户对照数据。
- 影子账本只追加到 `shadow/ledger.jsonl`；保留亏损、放弃的账本和补记成交标记，不只报赢家。
- 研究结论仅分保留、继续观察、建议验证。先积累样本，冻结改动候选并做独立样本外验证；
  用户批准后才修改正式策略和 Skill 版本。比赛窗口短，不把几次成功或账本汇总当盈利验证。
- 每周复盘一次：胜率、盈亏比、假突破次数、风控触发情况
- 比赛结束（11/28）后写总结：策略是否有效、哪些条件要改、能否复用到实盘
