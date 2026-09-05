# Wallet visualization

The local demo now includes **Wallets** at `/wallets`, linked from Live Shopping.

Start the existing backend with `sh start.sh`, then open http://127.0.0.1:8000/wallets.

- **Run full flow** creates a fresh session, two independent child wallets, funds each with 1.1 simulated XRP, and buys data from each. A final purchase deliberately loses its data response after settlement.
- **Recover same transaction** retrieves that data with the same signed payment and hash, without another charge.
- Individual controls create wallets, allocate funds, and purchase data. Agent A has a 0.06 XRP purchase budget; Agent B has 0.02 XRP. Purchases cost 0.02 XRP, excluding the simulated network fee.
- Click any transaction to inspect the signing wallet, hash, destination, and sample data.
- Refresh preserves the current session; **New session** creates a separate experiment without deleting previous records.

This page uses real XRPL signing and the x402 SDK against a **local simulated ledger and merchant**. It does not use the configured Testnet buyer, make live purchases, or alter checkout/billing records. Reserve and fee values are simulation fixtures. Local transaction hashes are not public explorer links.

## Integration

`wallet_lab/` was imported with `git subtree add --prefix=wallet_lab ... --squash` from wallet-lab commit `9211402`. The independent repository remains available. `wallet_visualization.py` exposes a router included by `orchestrator.py`; `wallet-visualization.html` is its UI. No sibling directory imports are required.

SQLite sessions live in ignored `.wallet-visualization/<uuid>/lab.sqlite3`. They contain disposable simulation seeds; public API responses return only explicitly selected fields. Never put real wallet keys in this store. UUID session IDs are local demo capabilities, not production user authentication. Mutation endpoints only operate the offline engine.

## Validation

From demo:

```sh
.venv/bin/python -m unittest test_wallet_visualization test_customer_checkout test_marketplace -v
.venv/bin/python -m unittest discover -s wallet_lab -v
```

Tests cover HTTP session isolation and input validation, secret-field omission, budgets and idempotency, payment recovery, parent ownership, sequence serialization, signature tampering, plus existing checkout and marketplace behavior. No live transfers are executed.
