# 风控上限（硬默认）

本文件是底线。`config.yaml` 可以收紧任何值；放宽任何值需要发布新的 skill 版本。

| 上限 | 默认 | 含义 |
|---|---|---|
| `max_position_pct` | 20% | 单只持仓，占总资产 |
| `max_total_exposure_pct` | 90% | 总市值 / 总资产 |
| `max_leverage` | 1.0× | 账户允许 2.0×；先无杠杆起步 |
| `min_cash_buffer_pct` | 10% | 下单后剩余现金 |
| `max_open_positions` | 10 | 并发标的数 |
| `max_daily_loss_pct` | 3% | 已实现 + 未实现，对当日开盘权益 |
| `max_drawdown_pct` | 10% | 权益对峰值权益 |
| `per_trade_stop_pct` | 5% | 相对平均成本 |
| `max_orders_per_day` | 20 | 含撤单 |
| `cooldown_after_stop_minutes` | 60 | 止损后同标的禁止再入场 |

## 执行

每次发单前全部检查。任一盘前上限被突破则取消该订单。

## 升级

| 触发 | 响应 |
|---|---|
| 当日亏损上限 | 停止开仓、平仓、报告，下一交易日恢复 |
| 回撤上限 | 平仓、停用策略、报告；由人重新启用 |
| 鉴权/权限失败 | 停止、报告确切错误码、不循环重试 |
| 数据过期或缺失 | 跳过该标的，记入 journal |
| 反复违规 | 一个会话内三次即停止 |

## 永不

- 为了避免亏损而放宽止损。
- 冷却期未过就重回止损过的标的。
- 配置了清仓时点却持仓过夜。
- 交易 `universe.symbols` 之外的股票，或 `universe.options.underlying` 之外的期权标的。
