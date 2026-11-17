# 风控流程

上限来自 `config.yaml`。本文件里的值是硬默认；config 只能收紧。检查发生在订单发出之前，
而不是成交之后。

## 盘前检查（全部通过才可下单）

| 检查 | 判定 |
|---|---|
| 账户 | `account_id`、`market_id`、`account_type` 与 config 一致；title 含比赛标记 |
| 模拟盘 | 账户为模拟账户；永不调用实盘接口 |
| 仓位 | `order_notional <= total_asset * max_position_pct` |
| 敞口 | `(current_mv + order_notional) <= total_asset * max_total_exposure_pct` |
| 杠杆 | `(current_mv + order_notional) <= total_asset * max_leverage` |
| 现金缓冲 | `cash_after >= total_asset * min_cash_buffer_pct` |
| 持仓数量 | 仅当 `open_positions < max_open_positions` 才可开新仓 |
| 当日亏损 | `realized + unrealized >= -total_asset_start_of_day * max_daily_loss_pct` |
| 回撤 | `equity >= peak_equity * (1 - max_drawdown_pct)` |
| 交易频次 | `orders_today < max_orders_per_day` |
| 标的范围 | 股票在 `universe.symbols`；期权标的在 `universe.options.underlying` 且结构在 `universe.options.structures` |

## 升级阶梯

| 触发 | 动作 |
|---|---|
| 触及当日亏损上限 | 停止开仓、平仓、报告，等下一交易日 |
| 触及回撤上限 | 平仓、停用策略、报告；不得自动恢复 |
| 鉴权/权限失败 | 停止交易；报告确切错误码；绝不循环重试 |
| 数据过期或缺失 | 跳过该标的并记入 journal；不得用过期价格替代 |
| 模型/agent 不确定 | 默认不交易；记录原因 |

## 报告

每次运行结束必须给出：账户 id、权益、敞口、发出订单数、规则违规、下一个计划动作。
沉默是失败模式，不是中性结果。
