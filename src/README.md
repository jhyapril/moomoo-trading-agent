# 执行契约

策略代码尚未实现——本文件定义实现必须满足的契约，保证重启不会重复下单。按此编写
`src/`，不要绕过它。

## 状态机（单次运行）

```text
preflight -> reconcile -> evaluate_exits -> evaluate_entries -> journal -> exit
     |            |               |                |
     +--- 任一硬失败：停止运行、journal 记录原因、非零退出
```

## 幂等

- 每张订单带客户端去重键：`sha1(date|symbol|rule|direction|seq)`。
- 发单**之前**先把键写入 `journal/`（或本地状态文件）。
- 启动时从 journal 重建存活键集合；任何已成交或在挂的键直接跳过。重跑一次会话必须安全。
- 订单提交至少一次；状态迁移保持幂等。

## 对账

- 券商是事实，本地状态只是缓存。
- 不一致时：采纳券商持仓、撤销不明在挂订单、两边事实都记入 journal。

## 数据规则

- 拒绝早于当前会话的行情，或必要字段为空的行情。
- 缺失值绝不默认为零——零是有效的价格。

## 密钥

- 客户端负责附加 OAuth。代码不得读取、打印或持久化 token 文件。
- 代码、config、journal、日志中不得出现任何凭据。

## 试运行

- 提供 `--dry-run`：只输出意图，不发送。首次模拟盘运行必须在 dry run 与回测 journal
  对得上之后才进行。

## 扫描工具

`src/scan.py` — 日线计划仓位扫描（`STRATEGY.md` §4.1），无第三方依赖。

```bash
python3 src/scan.py --out journal/scan-YYYY-MM-DD.csv < /tmp/bars.json
```

输入一行 JSON：`{"cfg": <config.signal>, "bars": {"US.AAPL": {"c": [...], "h": [...], "l": [...], "v": [...]}}}`
（按时间升序，最后一根为评估日）。阈值全部来自 `cfg`，代码里不写死数值；`l` 缺失时
`atr` 列为空。输出 CSV（每行一只标的，`planned` 为结论）+ 一行汇总到 stderr。

