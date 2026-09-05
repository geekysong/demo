"""Run the complete isolated offline demo and write a public, seed-free report."""
import json
import uuid
from pathlib import Path
if __package__:
    from .lab import FEE, PRICE, RESERVE, make_lab
else:
    from lab import FEE, PRICE, RESERVE, make_lab

ROOT = Path(__file__).resolve().parent


def main():
    run_id = uuid.uuid4().hex[:12]
    path = ROOT / '.runtime' / run_id / 'lab.sqlite3'
    store, ledger, app, engine = make_lab(path)
    wallets = [store.create_wallet('agent-a', 'tenant-a', 'child', 'master', 3 * PRICE),
               store.create_wallet('agent-b', 'tenant-a', 'child', 'master', PRICE)]
    steps = []
    for child in ('agent-a', 'agent-b'):
        steps.append(engine.fund('fund-' + child, 'master', child, RESERVE + 100_000, 'tenant-a'))
        steps.append(engine.purchase('buy-' + child, child, 'tenant-a'))
    try:
        engine.purchase('over-budget', 'agent-b', 'tenant-a')
        raise AssertionError('Budget violation was allowed')
    except ValueError as exc:
        steps.append({'id': 'over-budget', 'status': 'rejected_before_signing', 'reason': str(exc)})
    app.state.fail_after_settlement = True
    lost = engine.purchase('recoverable', 'agent-a', 'tenant-a')
    steps.append(lost)
    balance_before_recovery = ledger.account(store.wallet('agent-a')['address'])['balance']
    store, ledger, _, restarted = make_lab(path)
    recovered = restarted.resume('recoverable', 'tenant-a')
    steps.append(recovered)
    assert lost['status'] == 'delivery_failed' and recovered['status'] == 'delivered'
    assert lost['hash'] == recovered['hash']
    assert ledger.account(store.wallet('agent-a')['address'])['balance'] == balance_before_recovery
    balances = {ident: ledger.account(store.wallet(ident)['address'])['balance']
                for ident in ('master', 'agent-a', 'agent-b', 'merchant')}
    assert sum(balances.values()) == 20_000_000 + RESERVE - 5 * FEE
    assert all(s['status'] in ('funded', 'delivered') for s in steps[:4])
    report = {
        'mode': 'OFFLINE_SIMULATION', 'run_id': run_id,
        'real': ['independent XRPL keys', 'XRPL Payment signatures and verification',
                 'x402 SDK invoice binding', 'in-process HTTP 402/retry', 'SQLite persistence'],
        'simulated': ['ledger consensus', 'fund balances and reserves', 'facilitator settlement', 'vendor data'],
        'public_testnet_used': False, 'master_address': store.wallet('master')['address'],
        'children': wallets, 'steps': steps, 'balances_drops': balances,
        'recovery_charged_again': False, 'simulated_fees_burned_drops': 5 * FEE,
        'sample_delivery': json.loads(store.operation('recoverable')['result']),
    }
    output = ROOT / 'reports' / 'latest.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('OFFLINE_SIMULATION — no public ledger or real funds used')
    for step in steps:
        print(f"{step['id']}: {step['status']}")
    print('Restart recovery: same transaction hash; no second charge')
    print('Report:', output)


if __name__ == '__main__':
    main()
