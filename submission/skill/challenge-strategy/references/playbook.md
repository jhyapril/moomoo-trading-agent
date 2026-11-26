# 作战手册

策略自身的条件写在 `STRATEGY.md`。本文件定义围绕这些条件运行的流程，让 agent 无论信号
如何都表现一致。

## 入场门控

按顺序评估；第一项失败则该标的本次运行跳过。

1. **账户护栏** — 模拟比赛账户，id 与 market 匹配。
2. **市场开市** — 该标的所属市场处于交易时段。
3. **容量** — 仓位上限、敞口上限、现金缓冲、持仓数量、订单预算。
4. **数据新鲜** — 报价时间戳在当前会话内，必要字段非空。缺失值绝不默认为零。
5. **信号** — `STRATEGY.md` §4 的两段式判定：
   盘中全量资格（每次运行、全部 `universe.symbols`，§4.1）→ 试探仓（§4.2，`probe_ratio`）→
   确认加仓（次日 `confirm_eval_at`，§4.3，`confirm_ratio`）。
6. **扣成本后的边缘** — 按 `backtest/cost-model.md` 计算往返成本（点差 + 费率 + 滑点），
   目标幅度须达到 `cost.min_edge_cost_multiple` 倍；盘口不可用即不通过。

容量为零就停止。不要把一条规则缩小后再交易。

## 两段式入场

- 试探仓与确认加仓各是一次独立评估，各自过 Gate 0–2、各自去重（规则 id：`probe` /
  `confirm_add`），合计不得突破 `max_position_pct`。
- 试探仓不要求量比；确认加仓要求 `STRATEGY.md` §4.3 的趋势、RSI/%B、财报与量比条件。
- 突破晚于 `entry.late_breakout_after` 时，2 小时测试做不完：只走 +`breakout_buffer_pct`
  冲高，或等收盘评估时点确认。
- 确认不成立就不加仓；不加仓不等于出场，出场仍按下面六项判定。
- 永远不要用"先建满再说"或"降一点门槛"来推进。

## 出场门控

1. 硬止损或策略止损，取更紧者。
2. 逻辑失效——无论盈亏都出场。
3. 达到目标。
4. 时间止损 / 超出持有期。
5. 到达清仓时点（若已配置）。
6. 熔断——平仓并停用入场。

除非 `STRATEGY.md` 事先定义了部分出场，否则出场全有或全无。

## 不确定时的默认

- 不交易。记录歧义与缺失的输入。
- 不替换标的、不用过期价格、不换账户。
- 不通过降低阈值来"推进进度"。报告并等待。

## 历史日线增量缓存

- 每只美股已读取的完整历史日线保存在 `state/market-data/`，按来源、代码、日线周期、复权、
  交易时段及纽约时区隔离；保留原始行情字段与获取时间。数据员可用 Read 读取 JSON 缓存，
  只返回新增行情；协调者用 `src/market_cache.py` 唯一写入，成员不直接写文件。
- 迁移旧任务时先检查共享目录中的 `imported-scan-*.json`，复用已有字段，不重抓同轮历史。
  当前 `imported-scan-ed8e14d3-80f1-4536-a1af-0917044a3a05.json` 保存 14 只各 55 根 c/h/v；
  逐根日期、完整 open/low 与原请求参数缺失，标为 partial，仅供历史分析，不作为完整交易缓存。
  先从原任务导出仍保留的原始响应补齐；不可从指标/数组编造缺失日期、价格或复权口径。
  原任务已导出 `source-responses-ed8e14d3-80f1-4536-a1af-0917044a3a05.json`：CRWD、NVDA、TSM
  完整原始响应已并入正式缓存（截至 2026-11-17 共 55 根；原请求未显式传 extended_time，
  NVDA 与既有 e0 缓存重叠两根完全一致，下次增量的重叠校验可发现口径不符）。其余 11 只原始
  响应已丢失，仍为 partial，下次需按 `plan` 的 bootstrap 补取完整日线。
- 协调者先确认市场日历中的最后已收盘交易日，再运行
  `python3 src/market_cache.py plan --symbol US.NVDA --through YYYY-MM-DD`。
  `cached` 不再抓历史；`bootstrap` 按返回参数初始化；`incremental` 仅请求上次末根日线至目标日，
  含一根重叠日线。参数交给绑定的 `quote_history_kline`（`ktype=2`），不虚构 CLI 参数。
- `quote_history_kline` 的 `start/end` 含端点、`num` 最多 370，分页向过去；指定 start 后若最早
  返回日期仍晚于 start，继续按已核实的接口分页规则补齐。全部页收集、日期排序去重后一次合并；
  核验交易日连续性、分页与目标日覆盖，缺页或中间交易日缺失不得当作完整数据。
- 原始成功响应含 `ret_code=0`、`data.kline_list`，每根含 `date/open/high/low/close/volume`；
  协调者将其从 stdin 传给
  `python3 src/market_cache.py merge --symbol US.NVDA --through YYYY-MM-DD`。
  日期去重覆盖、历史保留、锁保护及原子替换；空响应、坏字段及超出已收盘日期均不推进缓存。
- 重叠已收盘 OHLCV 修订时，复权缓存标为无效，禁止继续算信号；取回原缓存完整日期窗口后
  用 merge 的 `--rebuild` 重建，不得只补新价格或丢弃旧历史。复权及交易时段变更使用独立缓存。
- `python3 src/market_cache.py read --symbol US.NVDA --through YYYY-MM-DD` 输出对齐的 OHLCV 数组，
  将 `bars` 按代码组装后传给 `src/scan.py`；所需根数按指标预热需求用 `--min-bars` 指定，默认 55。
  数据员直接 Read 时同样核验 valid、身份、根数、日期顺序及交易日覆盖；文件更新时间不是行情时间。
- 本缓存只涵盖已收盘日线，不代表当日未收盘 K 线或连续 120 分钟路径已验证。实时价、盘口、
  账户及订单仍须本轮重新读取；接口/账户失败不得用缓存绕过停止条件。盘中退出不等待缓存更新。
  现有 Team 验证轮仍是零共享写入，缓存须在允许写入的后续运行接入；不自动切换定时任务。

## Journal 字段（每个决策）

`timestamp, symbol, rule_id, side, quantity, order_type, limit, dedupe_key, reason,
expected_exit, stop, outcome, rule_violation`

## 影子研究

影子交易员独立运作（2026-11-19 用户要求）：拥有自己的空间 `shadow/`，可同时建立多个虚拟账本，
每个账本代表一套它自己的交易策略，用假设的买入卖出成交记账，目的是为优化现行策略提供对照。

- 独立性：不受现行策略的门控、仓位、风控上限、交易次数或标的范围约束，不需要风控审核或负责人批准；
  可自行读取全部日线缓存、盘中快照与分钟线，也可直接调用 Moomoo 只读行情工具自行抓数据。
- 唯一边界：零真实订单（不调用任何下单/改单/撤单接口，比赛账户与个人账户一律不碰）；
  不修改 config、STRATEGY、rules、Skill 和正式 journal；不读写凭据；只写 `shadow/` 目录。
- 数据共享（异步）：影子交易员有自己的定时任务，不占用买入决策会话。负责人每轮无论有无触发，都把
  数据员本轮返回原子存档到 `shadow.snapshot_dir/<日期>/<HHMM>.json`（先写 `.tmp` 再改名）；收盘任务把
  全部标的 1 分钟 OHLCV 存到 `<日期>/minute/US.XXX.json`，并在 journal 写比赛账户对照数据。影子交易员用
  `python3 src/shadow.py pending --date <日期>` 列出未读快照，按时间顺序处理，处理完用
  `python3 src/shadow.py seen` 标记；读不了的快照下轮再读。原始行情不复制进 `shadow/`，只记引用路径。
- 账本：`python3 src/shadow.py open` 开账本（`book, cash, strategy`，起始资金默认
  `shadow.default_book_cash`）；`python3 src/shadow.py fill` 记假设成交（`book, symbol, side, qty,
  price, filled_at, reason, data_ref`）；`python3 src/shadow.py report` 出各账本现金、持仓、已实现/
  未实现盈亏、费用与收益率（stdin 可传 `marks` 估值价）。追加写入 `shadow/ledger.jsonl`。
- 记账诚实：成交价用 `filled_at` 时点及之前可见的数据（如当时卖一/买一或成交价），`data_ref` 指明
  来源；工具自动写记录时间并按 `cost` 块算费用，晚于成交 `shadow.late_fill_minutes` 的记为补记，
  不计入前瞻样本。不事后删改记录，亏损与放弃的账本照样保留。
- 自己的空间：`shadow/strategies/<book>.md` 写各账本策略定义与改动史；`shadow/notes/<日期>.md`
  写盘中观察与盘后复盘。
- 盘后复盘：各账本对比比赛账户同期表现（收益、回撤、交易次数、胜率、费用），说明哪条规则差异
  导致结果不同，给出对现行策略的具体改进建议，结论只分保留、继续观察、建议验证。
- 改正式策略：须样本外验证与用户批准；影子结果从不自动写回 config、Skill 或正式交易。

## 报告（每次运行）

账户 id、权益、敞口、发出订单数、违规、下一个计划动作。沉默是失败模式。
影子交易员的盘后复盘任务另报各账本收益、回撤、交易次数、补记成交数及与比赛账户的对比；
结论仅为保留/继续观察/建议验证，样本外验证和用户批准前不得变更策略。
