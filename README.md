# Relay

**面向贷款机构的按需数据采购代理。**

贷方提出缺少什么数据，Relay 按采购规则选择资源、读取报价、完成付款，并返回数据及可追溯的采购凭证。贷方通过一次 Relay 集成使用多个数据来源；贷款审批仍由贷方负责。

本仓库是 hackathon 演示：**真实 XRP 测试网结算 + 本地供应商镜像 + 样例数据交付**，不是生产贷款系统。

## 演示什么

看板包含三个标签页：

| 页面 | 内容 |
| --- | --- |
| Live Shopping | 请求信息、供应商声明、筛选、402 报价、付款状态、交付数据及链上凭证 |
| Policy Config | 当前生效的预算与类别规则，只读展示 |
| Audit Ledger | 采购记录、候选与拒绝原因、交易链接和 CSV 导出 |

当前可选择两个数据产品：

| 产品 | 数据类别 | Demo 交付 |
| --- | --- | --- |
| CompliancePulse · Global LEI lookup | 企业注册状态 | 法定名称、实体状态、注册状态等样例 |
| MacroPulse · BLS wage benchmarks | 行业收入基准 | 劳动统计序列的声明样例 |

成功流程：

> 结构化请求 → 来源探测 → 策略筛选 → HTTP 402 报价 → 签名付款 → 测试网结算 → 独立链上确认 → 数据与审计凭证

Relay 只有在独立链上查询确认成功后，才将结果标记为 `delivered`。

## 快速开始

以下命令适用于 macOS / Linux，需要 **Python 3.11+**（本机使用 3.12 验证）、Git 和外网连接。GitHub 仓库若为私有，需要有访问权限；未登录浏览器可能显示 404。

```sh
git clone git@github.com:geekysong/demo.git
cd demo
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_testnet.py
sh start.sh
```

如果已下载仓库，从 `cd demo` 后的步骤开始；可将 `python3.12` 替换为本机的 Python 3.11+ 命令。

打开 **[本地业务看板](http://127.0.0.1:8000/)**，选择数据类别并点击 **Run flow**。正常演示请一次运行一个请求。

初始化脚本会创建付款和收款两个一次性测试网钱包，通过水龙头申请测试 XRP，并保存到被 Git 忽略的 `.env`（权限 `600`）。已有配置时不会覆盖钱包。无需真实资金或主网钱包；请勿提交或分享 `.env`。

之后重新启动只需在仓库目录执行：

```sh
sh start.sh
```

后端仅监听 `127.0.0.1:8000`，同时提供看板与业务 API。终端关闭或电脑重启后，需要重新启动服务。更多环境说明见 [本地配置指南](LOCAL_SETUP.md)。

## 查看演示文稿

- **[产品故事 v2](relay-business-deck-v2.html)**：产品本质、客户场景、交付结果、付费理由、商业模式及技术机制，共 10 页。
- [原版演示稿](relay-business-deck.html)：保留的早期版本。

HTML 文件在 GitHub 中显示为源码。克隆后可用浏览器直接打开文件，或在仓库目录另开终端运行：

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

再打开 **[本地 v2 演示稿](http://127.0.0.1:8765/relay-business-deck-v2.html)**，使用左右方向键翻页。8765 是静态展示服务；运行采购流程仍需启动 8000 业务后端。上述 localhost 链接只指向访问者自己的电脑，不是公开部署地址。

## 真实与模拟的边界

| 环节 | 当前实现 |
| --- | --- |
| 供应商发现 | 实时读取两个已配置资源的未付款 402 声明；不是动态搜索整个 Bazaar 目录 |
| 来源失联 | 每个资源可单独回退到 fixture，看板标为 fallback；仍可执行镜像采购 |
| 策略 | 服务端执行价格、累计额度、类别、信任阈值和新鲜度字段检查；信任分及新鲜度字段含 Demo 假设 |
| 支付 | 本地付款钱包向本地镜像的收款账户支付 XRP Testnet 测试币 |
| 原始供应商 | 声明使用主网 `xrpl:0`；Demo 没有向它们付款 |
| 数据交付 | 镜像返回保存的供应商样例，不是对当前申请人的实时核验 |
| 凭证 | 真实交易哈希、独立链上确认和余额查询；审计追加到本地 JSONL |
| 平台收费 | 仅计算演示账本，不向贷方真实收费 |

一次已验证的采购支付了 **20,000 drops（0.02 XRP）**，并返回 `delivered / tesSUCCESS`：[测试网交易](https://testnet.xrpl.org/transactions/B92C9FC50F57E81F0814B46E55A9E59AE789DDABB73E2A8484C1D7EB8318C138)。这验证了付款与样例交付流程，不代表已验证真实数据质量或生产性能。

供应商来源及镜像说明见 [MARKETPLACE_TESTNET.md](MARKETPLACE_TESTNET.md)。

## 商业模式

产品拟向贷款机构按完成的数据采购收费，支付供应商成本后保留采购服务收入。价值在于统一来源接入、采购规则与付款记录。

演示文稿提出 **US$0.50/次、US$10 试用额度**，属于待验证的商业方案。当前 `billing.py` 仍采用**数据成本加 17.5% 平台费、标称 US$50 试用额度**：额度只覆盖数据成本，平台费照常记账；耗尽后自动转为按用量计费。

运行账本使用固定换算假设，并非实时汇率。USD 收费、USDT 结算和货币兑换尚未实现；当前链上支付资产为 XRP Testnet。两套定价方案尚未统一，不应据此推导真实利润率。

## API 示例

后端启动后，可通过 API 发起与看板相同的采购：

```sh
curl -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"applicant_score":612,"data_type":"business_registration_status","applicant_region":"US","freshness_requirement_days":30}'

curl http://127.0.0.1:8000/status
```

`POST /run` 异步返回运行 ID；`GET /status` 返回当前全局任务状态，不是按 ID 隔离的任务查询接口。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 后端状态及测试网标识 |
| `GET /marketplace/candidates` | 刷新两家供应商的未付款声明 |
| `GET /policy.json` | 生效策略 |
| `GET /billing` | 演示计费余额 |
| `GET /audit` | 审计 JSON |
| `GET /audit.csv` | 导出 CSV |

`POST /run` 另接受 `scenario: "over_cap"`、`"blacklist"` 或 `"no_candidate"`，用于不付款的策略测试。前端尚未完整呈现这些终态，请通过 API 状态或审计查看结果。

## 当前限制

- 策略配置只读；可解释性筛选、按类别的新鲜度与实际数据时点核验尚未实现，region 只记录不筛选。
- 无候选只产生状态与审计，没有可操作的人审队列；PDF 导出尚未实现。
- 部分异常终态的前端处理、付款前报价一致性验证仍需完善。
- 单全局运行状态；无多租户、认证或完整并发/幂等保护。
- 计费和累计额度保存在内存，重启清零；JSONL 审计保留，但不具备防篡改保证。

完整差异、优先级和验收标准见 [PRD v2.1](relay-prd-v2-gap-execution-plan.md)。[README_AUDIT.md](README_AUDIT.md) 是历史测试记录，其中部分完成状态已过时，以当前 PRD 的核对结果为准。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `failed to start run` 或 JSON/SyntaxError | 运行 `sh start.sh`，使用 8000 看板地址；修改代码后刷新旧页面 |
| 找不到 `x402-xrpl` 安装版本 | 检查虚拟环境是否使用 Python 3.11+，不要使用系统 Python 3.9 |
| 钱包缺失或未激活 | 在虚拟环境中运行 `setup_testnet.py`；已有 `.env` 时保留原配置，只为未激活钱包申请测试币 |
| RPC 请求失败 | 检查外网连接及 `.env` 的 `XRPL_TESTNET_RPC_URL`；初始化脚本配置为 `https://s.altnet.rippletest.net:51234/` |
| GitHub 仓库链接 404 | 在浏览器登录有仓库权限的 GitHub 账号；Git SSH 登录与浏览器登录互不替代 |

## 代码结构

| 文件 | 职责 |
| --- | --- |
| `orchestrator.py` | FastAPI 服务、镜像路由、采购流程、状态及审计 |
| `marketplace.py` | 资源声明适配与 fallback 样例 |
| `policy_filter.py` | 策略、筛选与测试夹具 |
| `billing.py` | 试用额度与平台费账本 |
| `relay-screen1-live.html` | 三个标签页的业务看板 |
| `setup_testnet.py` / `start.sh` | 钱包配置与本地启动 |
| `requirements.txt` | 已验证环境的依赖版本 |
