# 比赛策略仓库

Moomoo x Qoder AI 模拟交易代理比赛的事实来源。

执行账户：`5829943`（market 100、美股 paper、account_type 2）。本仓库永远不指向
`2590077`（个人美股模拟盘）或任何实盘账户。

## 目录

| 路径 | 用途 | QCA 产物 |
|---|---|---|
| `STRATEGY.md` | 论点、标的、边缘、停止条件 | 参考资料 |
| `config.yaml` | 全部数值参数 | 随代码挂载 |
| `rules/` | 入场、出场、风控流程 | 同步进 skill |
| `src/` | 执行循环契约与代码 | 挂载进 Environment |
| `backtest/` | 离线验证 | 挂载进 Environment |
| `journal/` | 每日决策、订单、理由、盈亏 | 挂载进 Environment |
| `skill/challenge-strategy/` | 控制 agent 行为的 skill 源文件 | QCA Skill |
| `dist/` | 构建出的 ZIP（已 gitignore） | 上传产物 |

## 工作流

1. 规则和参数只在这里改，并纳入 git。这是它们唯一的修改入口。
2. 规则发生实质变化时，更新 `skill/challenge-strategy/`、重新打包，并作为新版本上传。
   Agent 会话会对 skill 做快照，未上传的修改不会到达正在运行的 agent：

   ```bash
   cd skill && zip -r -X ../dist/challenge-strategy.zip challenge-strategy
   ```
3. Environment 用 `config.yaml` 运行 `src/`；skill 规定 agent 的行为；Vault 保存 Moomoo OAuth。
4. 每个交易日结束后提交 journal。没有 journal 记录就等于这次运行没有发生。

## 本仓库的规则

- 密钥永不进入本目录。OAuth 放在 Vault；`.gitignore` 覆盖常见的泄漏路径。
- `config.yaml` 只能收紧 skill `references/risk-limits.md` 里的上限。放宽上限必须同时
  修改 skill，且要刻意为之。
- 每条代码路径都必须可安全重启：重跑一次会话不得重复下单。
