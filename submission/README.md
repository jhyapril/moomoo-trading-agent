# Moomoo × Qoder AI 交易代理比赛 · 提交包

账户 `5829943` · Moomoo x Qoder AI Paper Trading Agent Challenge · `account_type 2` · `market_id 100` · paper only
交易窗口 2026-11-17 → 2026-11-28 · 本包数据截至 **11/25 收盘**（11/26 感恩节休市）· 提交截止 2026-11-30 23:59 SGT

## 三十秒结论

| | |
|---|---|
| 真实订单 | **4 张**（券商 `has_more=false` 全史）：2 张测试单撤销 0 股、1 张用户指定建仓、1 张风控硬止损平仓 |
| 策略信号入场 | **0 笔**，出自 **1,260 次**程序化全量判定，`qualified=True` 计数为 0 |
| 账户结果 | 权益 **99,919.81**、累计 **−0.0802%**、持仓 0/8、敞口 0% |
| 风控 | 阈值改动 **0 次**、规则违规 **0 处**、未知来源订单 **0 笔** |
| 对照研究 | **24 个影子账本 / 136 笔假设成交 / −3.092%**，闭合到 0.01 美元；补记率 **39.71%** 主动公开 |
| 工程 | 36 个单元测试全通过、零第三方依赖、337 次 git 提交、约 20,000 行 journal |
| 未声称 | 策略盈利、回测通过、费用经账单核实、无人值守链路完整验证 |

一句话：**这套系统在市场没有给出它要求的东西时，证明了自己能不出手，并且把"为什么没出手"记成了可复现的证据。**

## 目录

```
submission/
├── README.md                        本文件
├── deck/                            Qoder 生成的演示文稿（.pptx）
├── evidence/
│   ├── 01-strategy.md               策略说明：论点、两段式入场、出场优先级、仓位方法、治理
│   ├── 02-risk-limits.md            风控上限表 + 实际执行记录 + 已知缺口
│   ├── 03-decision-log.md           8 天逐日决策日志（含出处）
│   ├── 04-fills-and-results.md      券商侧成交全史、权益盈亏、24 本影子结果、交付边界
│   └── 05-demo.md                   什么有效 / 什么失败 / 为什么 —— 含一键复现
├── demo/
│   ├── replay.py                    一键复现所有数字（109 行输出）
│   └── replay-output.txt            复现结果快照
├── data/
│   ├── orders.csv                   4 张真实订单（券商只读实测）
│   ├── shadow_books.csv             24 本账本逐项结果
│   ├── gate_tally.csv               1,260 次判定的门控拦截分布
│   └── run_inventory.csv            每日轮次 / 快照 / 分钟档案计数
├── agent-package/                   ★ 可运行的 trading-agent 包
│   ├── config.yaml                  全部数值参数（唯一来源）
│   ├── STRATEGY.md                  策略正文（§1–§8）
│   ├── rules/                       entry / exit / risk / connector-check 流程
│   ├── src/                         scan.py · watch.py · market_cache.py · shadow.py · run_lock.py
│   ├── backtest/                    36 个单元测试 + cost-model.md
│   ├── journal/                     8 个交易日原始审计轨迹（约 20,000 行）
│   ├── shadow/                      24 份策略定义 + ledger.jsonl + 5 份盘后复盘
│   └── state/market-data/           14 只日线缓存 + 4 个交易日的 watch.csv 判定表
├── skill/
│   ├── challenge-strategy/          控制 agent 行为的 skill 源文件（v0.6.0）
│   └── challenge-strategy.zip       重新打包的上传产物
└── agents/                          四角色 Team 定义
    ├── 比赛｜执行协调者.md            唯一券商写入者
    ├── 比赛｜数据研究员.md            只读行情与新闻
    ├── 比赛｜风控退出审核员.md         只读核验，持入场否决权
    └── 比赛｜影子策略研究员.md         独立虚拟账本研究，零真实订单
```

## 快速验证

```bash
python3 submission/demo/replay.py
for t in submission/agent-package/backtest/test_*.py; do python3 "$t"; done
```

两条命令覆盖：真实订单与盈亏、1,260 次门控判定、24 本影子账本的逐项结果与闭合校验、
风控上限 vs skill 硬底的松紧关系、36 个单元测试。全程离线、只读、不触碰券商接口。

## 架构

```
定时任务（盘中 cadence.poll_interval_minutes / 16:30 ET 收盘 / 盘后影子）
        │
        ▼
比赛｜执行协调者  ── 唯一券商写接口（sim_trade_input_order / modify / cancel）
   │  ├─ run_lock.py acquire ── 跨会话互斥（已知缺口：无 renew）
   │  ├─ 账户守卫 5829943/type2/market100/标题含 Qoder ── 不符整场停手
   │  ├─ rules/risk.md 12 项发单前检查
   │  └─ 委派 ─┬─ 比赛｜数据研究员     只读行情 → 返回原始数值 + missing_fields
   │           └─ 比赛｜风控退出审核员  只读账户 → exit_recommendations + entry_verdict
   ├─ src/watch.py  14 只全量门控判定 → state/.../watch.csv（15 列 × 1,260 行）
   ├─ src/market_cache.py  日线增量缓存（plan / merge / read，修订即禁用旧缓存）
   ├─ 原子快照 → state/market-data/intraday/<日期>/<HHMM>.json（90 个）
   └─ journal/<日期>.md 追加 → git 提交 → release
                     │
                     ▼（异步，不阻塞交易）
        比赛｜影子策略研究员  自有定时任务，读快照 + 缓存 + 行情
          └─ src/shadow.py open/fill/report/seen → shadow/ledger.jsonl（append-only）
          └─ shadow/notes/<日期>.md 盘后复盘 → 建议只分 保留 / 继续观察 / 建议验证
```

**唯一的边界**：研究层零真实订单、不改正式策略文件；正式策略与 skill 版本的变更需要独立样本外
验证和用户批准。执行层与研究了互不阻塞——影子研究员有自己的排期，负责人不调用也不等待它。

## 已知缺口（写在这里而不是藏在后面）

| 缺口 | 实测 |
|---|---|
| `run_lock.py` 无 `renew` | 第 14 次复现；最长持锁 109.2 分钟 = 7.28× `stale_seconds 900`；R5 期间挤掉 15:25 确认唤醒 |
| 官方费用/现金流接口 | `account_order_fees` ×3、`account_cash_logs` ×2 全部 MCP `-32603`，连续 3 日 ⇒ 费用为反推估算 |
| 回测 | 从未跑过样本外收益验证；`STRATEGY.md` §3 自开赛即写"待验证" |
| 前瞻样本 | 11/25 当日 46/46 假设成交全为补记 ⇒ 该日前瞻样本为 0，所有建议封顶 |
| 判据文本 | `shrt10t` 移动止损捕获率恒 0（结构性缺陷，11/26 起新读法生效，当日三腿不回改） |
| 条件止损单 | 券商 `sim_trade_input_order` 仅限价/市价 ⇒ 止损靠每轮现价复查，实测滑价 +0.076%…+2.048% |

细节与量化见 `evidence/05-demo.md`。
