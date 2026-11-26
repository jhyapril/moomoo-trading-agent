# 盘前连接器检查（写路径验证）

这是运维验证，不是策略信号：不产生 `probe` / `confirm_add` 去重键，不改变任何持仓与出场判断。

## 时点与去重

- 仅交易日纽约时间 `cadence.connector_check_at`（09:15）起、09:20 前执行一次；过期不补做。
- 当日 journal 已有 `rule_id: connector_check` 的发单记录 → 直接结束，不重复下单。
- 09:20–09:29 的唤醒属于空跑，不查账、不发单。

## 账户与读路径（硬约束）

1. `sim_trade_account_list` 实时核对：`5829943`、`account_type == 2`、`market_id == 100`、
   title 含 "Qoder"。任一不符 → 硬停，不换账户。
2. 一次新鲜行情调用（`quote_stock_quote`）加 `quote_market_state`，时间戳须在本次会话内；
   缺失或过期即跳过后续步骤。
3. 永不使用个人模拟账户 `2590077`；永不调用任何 `trading_order_*`、实盘或通用交易接口。

## 预算与容量

- 读 `sim_trade_history_order_list` 的当日订单数；本次测试最多 2 张（买 1 + 撤 1），
  与当日已用合计不得超过 `risk.max_orders_per_day`；不可读或超限 → 跳过写路径，只记录。
- 读 `sim_trade_cash_info`，确认可用现金 ≥ 测试单限价金额。

## 写路径测试

1. 选 `universe.symbols` 中有新鲜盘前报价的标的。
2. `sim_trade_input_order`：BUY、LIMIT、`qty=1`、限价 ≤ 参考价 × 0.9（远离市价），
   `order_trade_time_type=1`（仅盘中），盘前不可能成交。
3. 发单前先写 journal：`rule_id=connector_check`、symbol、side、qty、limit、参考价、
   outcome `pending_submit`。
4. 提交后查询当日订单取得 order_id，立即 `sim_trade_cancel_order`，再查一次确认终态。
5. 记录 order_id、提交结果、撤单结果、最终状态；万一成交（不应发生），按 §5 常规出场管理，
   不做测试性平仓。

## 失败处理

- 分类器拦截、超时或状态不明：查询原订单确认是否落单；记录事实，不重试同一报文、
  不补发、不换接口、不绕过权限。
- 盘口缺失、市场状态异常、账户不符：跳过并结束本次检查。

## 收尾

- journal 记录时间、账户 id、测试单结果、下一次动作。
- 本检查不改变策略仓位与风控容量；测试单计入日订单预算。
