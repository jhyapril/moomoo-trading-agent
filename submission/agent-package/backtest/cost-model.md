# 往返成本模型（Gate 3.5）

本文件是 `rules/entry.md` Gate 3.5 的推导依据。参数值只写在 `config.yaml` 的 `cost` 块，
这里不重复数值，只给公式、口径与校准计划。

## 口径

一次完整往返 = 买入 + 卖出，按四块计：

1. **佣金与平台费**（两边各收一次，按单笔取最低）
   `per_side = max(commission_per_share × qty, commission_min_per_order)
             + max(platform_per_share × qty, platform_min_per_order)`
2. **卖出监管费**（只在卖出边）
   `sec = sec_fee_rate × price × qty`
   `taf = min(taf_per_share × qty, taf_max_per_order)`
3. **点差**（决策时实时盘口，买在卖一、卖在买一）
   `spread_pct = (ask - bid) / ((ask + bid) / 2)`
4. **滑点**（两边各一次，保守常数）
   `slippage_pct = 2 × slippage_bps_per_side / 10000`

## 判定

```text
round_trip_cost_pct = 2 × per_side / notional
                    + (sec + taf) / notional
                    + spread_pct
                    + slippage_pct
notional = price × qty

通过条件：exits.stock.take_profit_pct >= min_edge_cost_multiple × round_trip_cost_pct
```

即：`目标幅度 ÷ 往返成本 >= min_edge_cost_multiple`。用 `min_edge_cost_multiple = 10`
时，10% 止盈目标意味着往返成本必须 ≤ 1%。

## 为什么用最低费用而非仅按股数

单笔金额小时，`min_per_order` 主导成本：约 $500 的订单，佣金 + 平台费最低合计约 $3.98，
仅费用就接近 0.8%，再加滑点与点差约 1.06% → 10 倍门槛不通过。这是一条有意的下限：
过小的订单成本占比吃掉边际，不如不做。

## 数据来源与校准

- 费率：券商美股公开费率表（佣金 $0.0049/股、最低 $0.99；平台费 $0.005/股、最低 $1.00；
  SEC 费与 TAF 为监管费率）。属**保守上限假设**，不是从本账户实测。
- 点差：决策时用 `quote_order_book` 取实时买卖一；盘口缺失、时间戳过期或买卖一为空 → 判不通过。
  非交易时段盘口不可用于判定（此时也不开新仓）。
- 校准：第一笔真实成交后，用 `account_order_fees` 读回实际费用，替换本模型中的费率假设；
  校准前该模型只能收紧、不能放宽。
- 尚未建模：卖出时的价格改善、分批成交、盘前盘后成交（策略本就只在常规时段开仓）。

## 已知局限

- 滑点 10 bps/边 是假设，不是实测；若成交回报显示系统性偏差，先调高再考虑调低。
- 本模型不评估"策略本身是否有边际"，只保证成本不吞掉目标幅度；是否有边际由
  `backtest/` 的样本外结果回答。
- 期权 sleeve 未纳入本模型（净借方、点差按合约计），需要单独补一节后才能对期权开仓。
