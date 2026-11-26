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

`src/watch.py` — 盘中全量盯盘判定（`STRATEGY.md` §4.1、§4.2、§4.4），每次运行对全部标的执行。

```bash
python3 src/watch.py --out /tmp/watch-YYYY-MM-DD.csv < /tmp/watch.json
```

输入：`{"cfg": <config.signal>, "entry": <config.entry>, "bars": {...截止上一交易日的已收盘日线 c/h/l/v...},
"live": {"US.AAPL": {"price", "volume", "data_time", "minute_closes", "as_of", "earnings_ok"}}}`。
`minute_closes` 为当日自 09:30 起全部 1 分钟收盘价；`trigger` 为 `surge`/`hold`/`close`/`-`。
缺实时价、缺财报结论或 ATR 不可算一律不触发；缺实时价时仍输出 `prior_high`，可用于盘后记录次日突破位。

`src/scan.py` — 按收盘价的日线扫描（旧 §4.1 口径），仅作盘后参考，不再作为盘中入场前置。

```bash
python3 src/scan.py --out journal/scan-YYYY-MM-DD.csv < /tmp/bars.json
```

输入一行 JSON：`{"cfg": <config.signal>, "bars": {"US.AAPL": {"c": [...], "h": [...], "l": [...], "v": [...]}}}`
（按时间升序，最后一根为评估日）。阈值全部来自 `cfg`，代码里不写死数值；`l` 缺失时
`atr` 列为空。输出 CSV（每行一只标的，`planned` 为结论）+ 一行汇总到 stderr。

## 影子虚拟账本

`src/shadow.py` — 影子交易员的假设成交账本，追加写入 `shadow/ledger.jsonl`，零真实订单。

```bash
echo '{"book":"momo","strategy":"..."}' | python3 src/shadow.py open
echo '{"book":"momo","symbol":"US.NVDA","side":"buy","qty":10,"price":155.1,"filled_at":"2026-11-19T10:05:00-05:00","reason":"...","data_ref":"state/market-data/intraday/2026-11-19/1005.json"}' | python3 src/shadow.py fill
echo '{"marks":{"US.NVDA":156.2}}' | python3 src/shadow.py report
python3 src/shadow.py pending --date 2026-11-19
echo '{"snapshot":"state/market-data/intraday/2026-11-19/1005.json"}' | python3 src/shadow.py seen
```

`pending` 列出 `shadow.snapshot_dir/<日期>/` 下尚未标记已读的 `HHMM.json` 快照（解析失败的列在 `unreadable`，
多半是负责人仍在写入，下一轮再读）；`seen` 把快照标记为已读，同一快照不可重复标记。

`cash` 缺省取 `shadow.default_book_cash`；费用按 `config.cost` 计算（卖出另加 SEC 与 TAF）；`filled_at`
不得晚于当前时间，记录时间晚于成交超过 `shadow.late_fill_minutes` 的标为补记。`report` 只有全部持仓都有
`marks` 时才给出权益与收益率。

