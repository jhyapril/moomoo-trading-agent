---
name: challenge-strategy
description: >-
  在模拟比赛账户上运行 Moomoo x Qoder AI 模拟交易代理比赛的纯模拟交易策略。当被要求
  运行、复盘、再平衡或记录比赛组合，或下达、修改、撤销模拟订单时使用。强制执行账户
  固定、盘前风控上限、可重启安全的订单对账和每日决策 journal。永不发送实盘订单，
  永不触碰非比赛账户。
allowed-tools: Bash Read
metadata:
  version: 0.1.0
  requires:
    bins:
      - moomoo
license: MIT
---

# 比赛策略

比赛账户的纯模拟执行。本 skill 是行为底线：若 `config.yaml` 与本 skill 冲突，取更严的规则。

## 硬限制

- 仅限模拟账户。要求 `account_type == 2`、`account_id` 与 `market_id` 匹配、title 含比赛
  标记。任一不符则整场会话停止。
- 永不调用实盘证券、加密或保证金交易接口。
- 永不读取、打印或持久化 token 文件；OAuth 由客户端附加。
- [风控上限](references/risk-limits.md) 在**发单之前**强制执行。检查失败时跳过该动作并把
  原因记入 journal——永远不要为了迁就交易而削减规则。
- 每个标的每次评估只做一个决策。不得突破仓位上限补仓摊薄。

## 运行顺序

1. **预检** — 确认绑定的 Moomoo 工具能响应只读调用，解析账户，核实市场状态。休市或盘前
   不开新仓；出场照常执行。
2. **对账** — 读取持仓、现金和在挂订单，与上一条 journal 记录比对。券商状态是事实。
   任何差异都记入 journal。
3. **出场优先** — 先按[作战手册](references/playbook.md)评估全部持仓，再考虑入场。出场永不
   因风控容量被阻塞。
4. **入场** — 按顺序评估各道门控；发单前记录意图，去重键为 `date|symbol|rule|direction`。
   该键已成交或在挂则跳过。
5. **Journal** — 追加到当日记录：决策、订单、成交、盈亏，以及任何规则违规。没有 journal
   记录的一次运行等于没有发生。

## 工具选择

使用环境中绑定的任一 Moomoo 接口——MCP 模拟交易工具或 `moomoo sim` CLI。命令与参数细节
属于 `moomoo-sim-trading` skill；不得自创参数。若未绑定任何模拟交易接口，停止并报告能力
缺失，不得回退到其他工具。

## 停止条件

出现以下任一情况即停止运行并报告：鉴权或权限失败、账户不匹配、数据过期、当日亏损上限、
回撤上限，或记录到三次规则违规。回撤停用后的恢复由人决定，不由 agent 自主决定。

## 参考

- [作战手册](references/playbook.md) — 入场/出场门控与不确定时的默认动作
- [风控上限](references/risk-limits.md) — 硬上限与升级路径
- [执行契约](references/execution-contract.md) — 幂等与对账
