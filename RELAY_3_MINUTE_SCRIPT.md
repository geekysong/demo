# Relay — 3-minute presentation script

配套文件：relay-business-deck-v3.html，第 1–5 页。
英文讲稿，适用于英文 deck；中文提示不朗读。建议节奏共 180 秒，包含换页及指示图表的停顿，不包含播放视频或等待实时交易。以下数字均沿用页面中的示例假设。

## Slide 1 · Pain point · 0:00–0:30

Imagine an underwriter reviewing an individual’s application. Their existing data source is missing some industry context. Finding that extra information can mean finding another supplier, connecting another API, and arranging another payment.

The data request may be small, but the procurement work is still there. That is the problem Relay addresses.

提示：用 underwriting 开场，但重点放在补充采购工作，不声称已证明行业数据缺口的市场规模。

## Slide 2 · Proxy · 0:30–1:05

Relay is a procurement proxy for financial institutions’ applications and agents.

The product design is simple: your application states what it needs and its budget. Relay selects from approved suppliers, compares eligible offers, and returns the purchased data with a receipt.

The customer sees a price in dollars, while Relay handles supplier settlement behind the scenes. Our current demo demonstrates a limited version of that purchasing flow.

提示：指向右侧 business loop。USD 客户计费、完善的批准供应商目录和更丰富的匹配属于产品设计，不是全部已实现。

## Slide 3 · x402 and XRPL · 1:05–1:45

Why this payment design? Some suppliers require payment before releasing a resource.

With x402, the API returns a quote. Relay checks the budget, authorizes payment, and retries with payment proof. XRPL provides settlement confirmation, and the supplier releases the result.

We have demonstrated a real payment of point zero two Test XRP to a demo mirror, followed by sample delivery. This proves the payment path. Supplier acceptance and the cost advantage over existing billing still need validation.

提示：沿三列表格讲流程。付款证明不等于数据真实性证明；不要说所有供应商都要求链上付款，也不要声称自动退款或原子交付。

## Slide 4 · Cost benefit · 1:45–2:30

Here is an illustrative single-source request priced at fifty US cents.

At our assumed exchange rate, the supplier’s point zero two XRP quote is equivalent to about two point nine cents. That leaves roughly forty-seven cents before other costs.

At one thousand completed requests, the table shows five hundred dollars in revenue and twenty-eight dollars eighty in supplier costs. The remaining spread must cover payments, failures, engineering, sales and operations.

The customer is paying for a completed procurement task. We still need to validate that this saves them enough work to justify the price.

提示：指向减法关系，再指向 1,000 次的表格行。$0.50 是定价示例，1,000 次是数量情景，均不是销量预测。无需逐位念出 $0.4712。

## Slide 5 · Conclusion and CLI · 2:30–3:00

Once the local demo is running, one command starts the purchase. The application does not need separate supplier integrations.

This request includes the applicant, data category and region. Today, it demonstrates sample procurement; precise applicant matching remains future work. The result and payment receipt appear in the dashboard.

Your team defines the need. Relay handles the purchase.

提示：指向 CLI，不逐字朗读。请求异步返回 ID；不要说命令直接同步返回真实申请人数据。若现场执行，提前启动服务并配置 Testnet 钱包；运行会发起 Testnet 采购。

## Q&A：仅被追问时使用

- 为什么不用月结？如果供应商已经提供合适的月结安排，XRPL 未必更好。我们针对先付款后交付、按需购买的路径，并会比较完整成本。
- 为什么 $0.50？这是完成一次单源采购的示例价格，尚未验证付费意愿。多源任务另行报价，不能理解成所有 API 的统一单价。
- 数据可信吗？当前交付样本。生产版本需要主体匹配、字段和时效校验及来源证据；当前付款回执只证明付款。
- 法币和 USDT 已实现吗？没有。当前是 XRP Testnet 付款；USD 计费和实际兑换仍是计划。页面 USDT 数值是换算示例。
