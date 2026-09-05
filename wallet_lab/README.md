> 已通过 Git subtree 从独立原型 `9211402` 合入 demo。界面入口为 `/wallets`；集成说明见上一级 `WALLET_VISUALIZATION.md`。下文保留原型的实现说明，涉及“尚未 merge”的段落描述的是原始 checkpoint。

# Wallet Lab：独立主钱包 / 子钱包购买原型

本地闭环已实现：创建两个独立子钱包 → 主钱包分别注资 → 子钱包通过 x402 购买样例数据 → 独立核对模拟账本 → 持久化结果。包括超预算拒绝、付款后响应丢失和重启恢复。

**这是离线集成验证，不是 Testnet 上链验收。** 使用真实 XRPL 密钥、交易编码、签名验证和 `x402-xrpl` SDK；账本、准备金、资金、facilitator 和数据交付由本地模拟。哈希来自真实签名交易，但不能在公共浏览器查询。没有读取 demo 的 `.env`，没有使用现有钱包，没有外部请求。

## 运行

在任意目录可使用工作区已有解释器运行（只借用已安装依赖，不导入 demo 业务代码）：

```sh
/Users/alberto/Documents/hackathon/demo/.venv/bin/python /Users/alberto/Documents/hackathon/demo/wallet_lab/run.py
/Users/alberto/Documents/hackathon/demo/.venv/bin/python -m unittest discover -s /Users/alberto/Documents/hackathon/demo/wallet_lab -v
```

也可在此目录创建自己的环境：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
.venv/bin/python -m unittest -v
```

每次运行创建独立的 `.runtime/<run-id>/lab.sqlite3`，不会重置已有实验。结果写入 `reports/latest.json`，其中不含 seed、私钥或签名 blob。SQLite 中保存一次性本地测试 seed，文件权限为 0600；此存储方式仅用于原型，不能存放真实资金钱包。不要提交 `.runtime/`。

## 已跑通的流程

```text
master（模拟初始余额 20 XRP）
  ├─ 1.1 XRP → agent-a（采购额度 60,000 drops）
  │                ├─ 20,000 drops → merchant
  │                └─ 20,000 drops → merchant，响应丢失后重启补取
  └─ 1.1 XRP → agent-b（采购额度 20,000 drops）
                   ├─ 20,000 drops → merchant
                   └─ 再次购买：超预算，签名前拒绝
```

模拟参数：准备金 1,000,000 drops；每笔手续费 12 drops；商品 20,000 drops。参数用于确定性验证，不代表当前 Testnet 配置。预算只计采购本金，手续费从钱包余额另扣；资金分配与采购授权是两个独立概念。

主钱包和子钱包通过数据库 `parent` 关联，使用独立随机 seed；不做 HD 派生。主钱包注资不产生链上控制权。调用方通过内部方法的 tenant 参数模拟已认证主体，当前没有对外 HTTP 业务 API 或登录系统；不能把调用方自报 tenant 当成生产授权。

## 模块边界

| 实现 | 作用 |
| --- | --- |
| `Store` | 钱包归属、额度、交易和交付状态持久化；创建幂等 |
| `Engine.fund` | 校验主子关系、生成主钱包付款交易、保存后提交 |
| `Engine.purchase` | 授权和余额检查、预算预占、最终 402 报价核对、SDK 签名 |
| `Engine.resume` | 复用已保存签名和哈希查账、恢复交付、处理过期 |
| `LocalRpc` | SDK 的离线 RPC adapter，真实执行 SDK autofill / invoice 绑定 |
| `LocalLedger` | 验签、余额/手续费/Sequence 模拟、同哈希幂等结算 |
| `merchant_app` | FastAPI 本地商户，通过 TestClient 执行 HTTP 402 和带签名重试 |

原型完全位于本目录。没有修改 `demo/`、`provider/`，没有 merge。

## 关键保证及限制

- 先保存签名 blob、哈希、LastLedgerSequence，再提交；重试不会重新签名。
- 预算在 SQLite 事务中预占，已付款未交付仍占用预算；失败且未支付、确定过期才释放。
- 原型通过文件锁串行化全部操作，并限制同钱包只有一笔未完成操作；优先验证正确性，暂不优化多钱包吞吐。
- 已签名付款可能在禁用钱包前已发出；禁用后只核对未决付款，不主动重发未结算交易。
- 本地模拟账本有完整历史；真实 RPC 的查无交易和历史缺口不能直接判断过期失败。
- 商户缓存并绑定 invoice → transaction → data，允许同一签名补取。这是本原型新增能力，不代表现有 demo 中间件或外部商户已经支持。
- 模拟账本只实现直接 XRP Payment 的必要子集，不模拟共识、真实费用波动、全部 XRPL 错误码或完整安全策略。
- 不提供自动补款、回收、退款、主网、稳定币或密钥轮换。

## Testnet 验证入口准备

当前没有可执行的真实转账开关，避免把离线通过误认为链上通过。延续探索阶段“不执行真实转账或付费购买”的约束。

独立原型进入下一阶段时，在本目录添加真实 Ledger/RPC adapter 和真实商户 HTTP transport，保留 Engine 的“提交前持久化”和幂等语义。需要同时：

1. 使用全新 Testnet 主钱包、商户钱包和子钱包；查询目标网络准备金、费用及网络标识。
2. 让主钱包实际注资两个子钱包并查询 validated 结果；注资不要用水龙头直接给子钱包替代。
3. 子钱包使用 demo 同款 SDK 对 Testnet 镜像付款；使用实际金额核对交易及余额。
4. 验证真实 facilitator 对重复签名和 invoice 的行为；支付成功而交付丢失时必须有补取协议。
5. 将模拟账本的完整历史假设替换为 RPC 历史完整性判断，并记录真实费用和最终错误结果。

真实 Testnet 验收完成后再讨论 merge；当前不改原项目接口。
