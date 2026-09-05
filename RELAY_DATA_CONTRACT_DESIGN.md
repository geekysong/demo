# Relay：平台契约设计与 underwriting 首个应用场景

当前产品定位：Relay 是实现供应商选择和小额采购自动化的 proxy 平台。下文个人贷款的数据契约是首个应用场景，不代表平台仅面向贷款机构。通用资源契约、多客户配置及多支付渠道仍需实现。

设计提案；尚未实现。当前 `/run`、`/status` 和 Testnet 支付行为不变。以下 `/v1/*`、字段和状态均为拟议接口，不应当作为当前可运行命令演示。

## 1. 产品边界

Relay 为个人贷款申请采购补充信息。机构决定需要什么证据以及如何使用；Relay 验证供应商、请求适配性和交付内容，不给个人作贷款决定。

公司注册信息是条件分支：只有机构明确要求核查某个公司 owner 的关联公司时才购买。个人申请编号不能代替公司标识；公司注册有效也不能证明个人持股、收入或还款能力。

XRPL 证明特定付款在链上被确认；x402 连接报价、付款和访问。这两者不自动证明数据真实、实体匹配、行业相关、及时或适合贷款用途。签名和内容摘要能支持来源认证、完整性和追溯，也不能单独证明事实正确。

## 2. 当前实现审计

| 当前事实 | 实际含义 / 缺口 |
| --- | --- |
| `marketplace.py` 给候选设定 `trust_score=80` | 演示代理值，不是经过核验的数据质量评分；fallback 也继承该值。 |
| `freshness_days=0` | 不是数据观测时间。未实现注释中所说的交付后数据新鲜度验证。 |
| 按 `data_type` 相等筛选 | 不能保证国家、行业、指标、实体、期间、统计口径或用途适配。 |
| 地区及请求原因被记录 | 没有用于地区筛选或行业指标映射。 |
| `industry_income_benchmarks` fallback 返回 CPI | 类别标签看似匹配，具体指标却不支持法律行业收入判断；应拒绝作为该请求的可用结果。 |
| 镜像返回固定 `sample_data` | 不是按申请人查询。公司样例也不能被当作该人的关联公司。 |
| `POST /run` 返回 run/request ID，`GET /status` 返回共享当前状态 | 已有传输格式，但缺少完整语义契约、按请求隔离的结果和版本化校验。 |
| 链上确认后设为 `delivered` 并计入账本 | 当前 delivered 不等于数据质量验收通过。 |

依据：`marketplace.py`、`policy_filter.py`、`orchestrator.py`。

## 3. 购买前：机构 Agent 如何知道匹配程度

### 供应商能力声明

每种资源提供可机器读取、带版本的能力清单。不能只给自由文本简介或一个总分。

- 资源 ID、供应商身份、接口及版本。
- JSON Schema：准确的输入、输出、必填参数、枚举、单位和错误结构。
- 数据含义：指标定义，个人 / 公司 / 行业汇总粒度，国家与地区范围，行业分类体系及代码、可用期间。
- 来源与更新：原始数据发布者、原始记录链接、方法、观测时间、发布时间、修订和更新频率。
- 使用条件：许可用途、禁止用途、保存或再分发限制。供应商的自述与 Relay 独立核验的证据分开记录。
- 价格、币种、网络、报价有效期；样例显式标注 `sample=true`。
- 已验证的限制，例如行业统计不能核实个人实际收入。

自然语言可帮助召回候选；结构化、确定性的规则负责硬条件检查。含糊的行业、地区或指标先返回澄清请求，不能悄悄放宽要求。

### 拟议 `POST /v1/matches`（不采购、不付款）

1. 通过认证身份绑定机构和已保存 policy；请求里的 policy 引用只能选择该机构有权限使用的版本，不能覆盖服务器规则。
2. 解析用途与所需指标，并确认已有合法数据访问依据；用不透明申请人引用做关联，按需向供应商提供最少标识。
3. 对候选逐项检查指标、地区、行业、粒度、时间、用途、必要输入、输出结构、预算及来源核验情况。
4. 返回 `eligible`、`needs_clarification`、`needs_review` 或 `no_match`，附每一项的证据与原因。未知项不能当作通过。
5. 仅在所有硬条件满足后才对价格等偏好排序。不要让综合分数掩盖国家错误、指标错误等硬失败。

### 请求示例（行业背景；不请求个人收入记录）

```json
{
  "schema_version": "1.0",
  "client_request_id": "case-001-context-01",
  "policy_ref": {"id": "personal-loan-context", "version": "3"},
  "subject": {"type": "person", "applicant_ref": "PERSON-001"},
  "purpose": "supplemental_income_context",
  "need": {
    "data_type": "industry_income_benchmarks",
    "metrics": ["median_annual_earnings", "earnings_yoy_change"],
    "geography": {"country": "US", "region": "US-CA"},
    "industry": {"label": "legal services", "taxonomy": null, "code": null},
    "granularity": "industry_region",
    "period": {"from": "2025-01-01", "to": "2025-12-31"},
    "max_publication_age_days": 180,
    "required_fields": ["metric", "value", "unit", "period", "source"]
  },
  "budget": {"max_customer_charge": "0.50", "currency": "USD"}
}
```

以上周期、180 天和预算只是示例偏好。观测期、发布时间与抓取时间分别检查；刚抓取的旧数据不是新观测数据。行业 taxonomy/code 未明确时，应确认映射后再采购。

如果购买的是个人收入核验，则用另一种契约要求可核验的主体标识、授权依据和精确实体匹配；不要把行业统计当作其替代品。公司 owner 分支另外提供关联公司标识及关联证据引用。

### 针对当前 CPI 样例的拟议匹配响应

```json
{
  "schema_version": "1.0",
  "match_id": "MATCH-001",
  "client_request_id": "case-001-context-01",
  "status": "no_match",
  "checks": [
    {"dimension": "metric", "status": "fail", "reason": "CPI is not an earnings metric"},
    {"dimension": "industry", "status": "unknown", "reason": "Legal-services coverage not demonstrated"},
    {"dimension": "geography", "status": "fail", "reason": "National CPI does not meet the requested state-level earnings scope"},
    {"dimension": "delivery_mode", "status": "fail", "reason": "Advertised sample only"}
  ],
  "eligible_resources": [],
  "purchase_allowed": false,
  "payment": {"status": "not_attempted"},
  "next_action": "Find a resource with the required earnings coverage; clarify the industry code"
}
```

对可购买候选，响应还应提供能力版本、policy 版本、完整检查证据、供应商报价、客户总价、有效期、限制和 `match_token`。Token 绑定机构、请求、资源、价格上限和 policy；采购前重新检查有效性。

## 4. 采购与交付后验证

拟议 `POST /v1/purchases` 接收 `match_token` 和 `idempotency_key`；机构预授权政策可允许其 Agent 自动提交，无需每次人工点击。重复请求必须返回同一采购状态，不能再次付款。改变资源、条件、policy 或过期报价时重新匹配。

采购为异步流程，返回 `purchase_id`；使用机构隔离的 `GET /v1/purchases/{id}` 查询，不依赖全局最新 `/status`。设置超时、失败和重复回调处理。

交付后验证：

1. JSON Schema、类型、必填字段、单位、范围及空结果。
2. 与请求的国家、行业、指标、期间及粒度逐项对照；个人或公司记录则校验精确标识和已提供的关联证据，不能仅靠同名匹配。
3. 核验观测期与发布时间；把检索时间作为另一个字段。
4. 记录原始发布者、记录定位信息、方法、版本、原始响应摘要；按机构政策要求通过原始来源复核或独立来源交叉验证。相互转载不算独立验证。
5. 检查实际交付是否超出许可用途或声明范围。
6. 每项结果使用 `pass/fail/unknown`，关联证据；供应商声称的真实性与 Relay 实际核验结果分别展示。

保留原始响应和标准化结果的关联；总结必须标注引用，不把推断包装成原始数据。数据在链下保存，按机构访问和保留规则控制；不把个人敏感内容放进公开链上收据。

付款已确认但验收失败时：保留 `payment.status=confirmed`，同时返回 `data_validation.status=rejected`；不得因为链上成功就标记为可用。不得声称 XRPL 会自动退款。客户账单暂不完成，重试/替代采购必须重新检查预算；供应商退款或争议依赖另外约定的机制。

## 5. 交付结果契约

一个响应应同时包含：请求回显、匹配解释、标准化数据、来源证据、验证结果、使用限制和付款收据。

下面是结构示例，未购买、未生成任何真实数据，因此字段为空；生产成功响应必须填入可追溯数值和证据。

```json
{
  "schema_version": "1.0",
  "purchase_id": "PURCHASE-EXAMPLE",
  "client_request_id": "case-001-context-01",
  "applicant_ref": "PERSON-001",
  "status": "pending",
  "policy_ref": {"id": "personal-loan-context", "version": "3"},
  "resource": {"id": null, "capability_version": null},
  "match": {"status": "pending", "checks": []},
  "data": {
    "scope": "industry_region",
    "geography": {"country": "US", "region": "US-CA"},
    "industry": {"taxonomy": null, "code": null},
    "observations": []
  },
  "provenance": [],
  "data_validation": {"status": "pending", "checks": []},
  "limitations": ["Industry context does not verify this person's actual income"],
  "payment": {"status": "not_attempted", "network": null, "asset": null, "amount": null, "transaction_hash": null},
  "customer_billing": {"status": "not_charged", "currency": "USD", "amount": null}
}
```

成功结果中每条 `observations` 至少有 `metric`、`value`、`unit`、`period`、`published_at`、`source_ref`。每条 provenance 至少有发布者、原始记录定位、获取时间和核验方法/结果。`data_validation` 通过只意味着满足列出的检查范围，不表示对事实真实性的绝对保证，也不替机构作适用性或贷款判断。

## 6. 下一步实施顺序

1. 先定义并校验版本化请求、能力和结果 JSON Schema；增加按请求/机构隔离的状态。
2. 修正演示可信度和新鲜度展示；将 sample 与采购验收状态分开。
3. 实现不付款的匹配接口，以及真实资源参数映射、严格实体和数据范围检查。
4. 引入交付后验证；再把验收与账单完成状态连接。
5. 使用 CPI 错配、地区错误、过期数据、缺字段、主体混淆、未知来源、重复采购请求、付款成功但数据失败等测试验证。

演示应先展示一个明确拒绝的错配例子，再展示真正符合契约的采购与交付。不能为了演示成功，将未知或错误的匹配自动判为通过。

## 7. 谁校验、怎样校验、谁决定可用

这里将 window 理解为时间窗口/新鲜度；同样的证据责任也适用于 vendor 数据。

| 检查 | 执行者（拟议） | 检查方式 | 机构看到的证据 |
| --- | --- | --- | --- |
| 时间窗口 | Relay 确定性验证服务 | 将观测期、发布时间与请求要求逐项对照；不把刚抓取视为刚发布。缺少时间则 unknown。 | 要求、实际时间、规则版本、pass/fail/unknown、原始来源引用 |
| Schema、指标、单位和国家/行业范围 | Relay 验证服务 | JSON Schema 校验及明确代码/枚举映射，检查实际输出而非供应商类别标签 | 所需与实际字段、代码映射和失败原因 |
| 人或公司匹配 | Relay 实体匹配规则；歧义由指定人工复核 | 以有权限使用的精确标识和关联证据为依据，不凭同名或 LLM 猜测 | 标识匹配结果、关联证据引用、复核记录 |
| 来源可信度 | Relay 供应商接入/数据运营负责人；机构审批所需级别 | 核对发布者、来源授权、方法及可抽查的原始记录，按政策进行独立来源复核 | 谁在何时核验什么、证据、到期时间、尚未验证项 |
| 付款结果 | Facilitator / XRPL 验证网络；Relay 独立 RPC 检查 | 校验实际交易、金额、目的地址、网络和最终状态 | 交易哈希与核对结果；不代表数据事实核验 |
| 是否适合该机构的使用目的 | 机构的数据/风险负责人事先定义；规则自动执行，例外按机构流程审阅 | 对照用途、粒度、时效、许可和限制；贷款决定仍由机构负责 | 所用 policy 版本、适用范围、限制及例外处理 |

Relay 内部验证不是独立第三方认证。Agent 可以解释、组织或提出候选；它不能仅凭自己的自然语言判断签发“可信”结果。人工审查员或第三方核验如实际参与，应明确标识身份、范围和时间。

例如：客户要求“最近 7 天发布的资料”，今天抓取到 6 个月前发布的统计，仍应判为不符合该窗口。另一个客户明确需要去年全年统计时，观测期较旧可能恰好符合需求。两种要求不能用一个 freshness_score 代替。

每个验证记录至少包含 `check_id`、`checked_by`（服务或复核角色）、`rule_version`、`checked_at`、`expected`、`observed`、`evidence_refs`、`status`。没有证据的来源真实性检查返回 unknown，不能由链上确认填补。

## 8. 为什么需要法币到链上付款层

供应商的数据接口可以是普通链下 HTTPS API；“支持链上付款”不等于供应商或数据在链上。当前两个资源被选入，是因为它们与 XRPL/x402 演示技术相容，不能推导出个人贷款数据供应商普遍接受或只接受 crypto。

产品定位应区分：

- **数据采购服务**：机构需要合适、可追溯的数据，Relay 处理供应商接入、匹配、验证和采购。这是当前 deck 较完整但尚待实现/验证的价值主张。
- **法币到 crypto 支付代理**：只有目标客户确实要买支持该结算方式的 API、同时不愿自行管理钱包与付款流程时，才有独立需求。不应仅因 hackathon 使用 XRPL 就假定存在需求。

推荐的架构提案：客户按法币计价和账单，Relay 根据合格供应商实际支持的方式付款。支持 x402 的资源可走 XRPL；支持普通支付的资源可以走传统方式。多支付渠道目前未实现，新增渠道需相应接入和运营成本。

USDT 不是必经步骤：若供应商只报价 XRP，就必须按可接受报价支付 XRP，或有明确的兑换执行安排。不能画成 USDT 在所有 XRPL 供应商之间原生通用的已实现流程。也不必每一次 query 都即时做法币兑换；拟议资金方案可以在 Relay 层预先备付并定期补充，但应单独定义资金风险、成本和对账责任。

对首批供应商逐个验证：是否覆盖个人贷款场景、是否接受 crypto、是否仅接受 crypto、是否提供按次购买、既有法币渠道有哪些障碍，以及 Relay 的全部成本是否优于直接采购。市场接受度尚无结论。

参考：
- [XRPL x402 流程](https://xrpl.org/docs/agents/agentic-payments-x402)：商户、payer agent 和 facilitator 的付款职责。
- [x402 官方 FAQ](https://docs.cdp.coinbase.com/x402/support/faq)：可编程 HTTP 付款及 API 接入定位；不作为信贷数据市场普及率证据。

## 9. Partner review 后的工作假设

- Demo 接受“可靠、相关的补充证据有价值”为工作假设；不声称无限增加数据必然提高结果。选型、冗余、适用性和付费意愿仍需验证。
- Vendor API 和链上付款是独立维度。采购接口统一可以有价值，不需要把数据放到链上；结算由具体供应商支持的币种和网络决定，不能由 Web3 / 传统企业标签推断。
- 内容真实性需原始来源核验或独立交叉验证。Schema、时间和字段 cross-check 只能证明这些条件被满足。
- 自动采购可靠性属于后续工程工作：契约、政策、幂等、对账和失败恢复；验证可以减少错误，不能保证零错误。
- 客户以 USD 理解价格；XRPL 留在幕后。低链上费用和快速确认是基础设施属性，不能等同于法币入金、兑换、数据交付全流程均快且低成本。
- 即时 XRP 兑换为 USDT 缩短价格暴露时间，但不消除价差、交易费用、滑点或 USDT 偏离美元的可能。XRPL 是网络，XRP 才是可兑换资产；兑换路径、流动性与网络兼容性仍需实现并验证。
- 月固定成本：1 名工程师 + 1 名 sales 的完整用工成本，加基础托管和运营。未给出工资，不虚构估值。
- 单次变动成本：供应商、付款与兑换、交叉验证、计算、支持和失败处理。试用也有履约成本，必须在收入模型中计入。
- 拟议经营结果 = 付费查询数 ×（客户单价 − 供应商成本 − 其他单次变动成本）− 月固定成本 − 未计入前项的试用成本。避免同一成本重复计入。之前的 0.4712 美元仅为示例数据差价，不是净利润。

技术参考：[XRPL payment properties](https://xrpl.org/about/xrp)、[AMM trading fees](https://xrpl.org/docs/concepts/tokens/decentralized-exchange/automated-market-makers)、[交易滑点示例](https://xrpl.org/docs/tutorials/defi/dex/use-amm-auction-slot-for-lower-fees)。这些资料不证明供应商实际接受某种结算方式或我们的端到端成本优势。
