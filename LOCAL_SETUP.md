# Relay 本地运行（换机配置）

需要 Python 3.11+；本机已使用 Python 3.12 建好 `.venv`。

## 日常启动

```sh
cd /Users/alberto/Documents/hackathon/demo
sh start.sh
```

打开 http://127.0.0.1:8000/ ，点击 **Run flow**。
此地址同时提供前端和业务 API。8765 只是另行启动的静态演示文稿服务器。
关闭终端或重启电脑后，需要重新执行启动命令。

## 下一台电脑首次配置

在 demo 目录执行（将 python3.12 替换为本机 Python 3.11+）：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_testnet.py
sh start.sh
```

`setup_testnet.py` 创建两个一次性测试网钱包，向官方水龙头申请测试 XRP，
并把配置保存在权限为 600、已被 Git 忽略的 `.env` 中。已有 `.env` 时保留
钱包，不覆盖配置；重复执行可检查余额并为尚未激活的账户申请测试币。
不要提交或分享 `.env`。不需要真实资金或主网钱包。

本次配置使用官方 Testnet RPC `https://s.altnet.rippletest.net:51234/`；
旧文档的 XRPL Labs 节点在本机返回 HTTP 418，故已替换。

## 演示边界与排错

- 供应商元数据通过未付款的 HTTP 402 请求发现；供应商失联时使用标明 fallback 的数据。
- 支付在 XRPL Testnet 上真实结算，交付内容是本地镜像的供应商样例；不向主网供应商付款。
- 平台费仅记入演示账本；计费余额和累计采购计数重启后清零。
- `GET /health` 检查后端，`GET /status` 查看运行阶段，`GET /audit.csv` 导出审计记录。
- `failed to start run`：确认 `sh start.sh` 正在运行，并使用 8000 地址；旧静态页面需刷新。
- 旧 README 中的 `x402_poc`、`server.py`、`client.py`、`.env.server`、`.env.client`
  属于历史版本，本目录当前入口是 `orchestrator.py`，以本文为准。
