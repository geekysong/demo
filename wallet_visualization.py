"""Local wallet visualization. All balances and settlements are simulated.

Run IDs are unguessable capabilities for isolated disposable sessions. Public
snapshots intentionally omit seeds and signed transaction blobs.
"""
from pathlib import Path
from typing import Annotated
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from wallet_lab.lab import FEE, PRICE, RESERVE, Store, make_lab

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / '.wallet-visualization'
router = APIRouter(prefix='/wallets', tags=['wallet-visualization'])


class ChildRequest(BaseModel):
    wallet_id: Annotated[str, Field(pattern=r'^agent-[a-z0-9-]{1,24}$')]
    budget_drops: Annotated[int, Field(strict=True, ge=PRICE, le=1_000_000)] = PRICE * 2


class ActionRequest(BaseModel):
    operation_id: uuid.UUID
    lose_response: bool = False


def session_path(session_id: uuid.UUID):
    path = DATA_ROOT / str(session_id) / 'lab.sqlite3'
    if not path.is_file():
        raise HTTPException(404, 'Wallet session not found. Start a new session.')
    return path


def snapshot(path, session_id):
    store = Store(path)
    with store.db() as c:
        c.execute('BEGIN')
        wallet_rows = c.execute('SELECT id,parent,role,address,budget,enabled FROM wallets ORDER BY rowid').fetchall()
        operations = [dict(r) for r in c.execute('''SELECT id,kind,wallet,destination,amount,status,hash,error,result
            FROM operations ORDER BY rowid DESC''')]
        accounts = {r['address']: r['balance'] for r in c.execute('SELECT address,balance FROM accounts')}
        txs = [json.loads(r['tx']) for r in c.execute('SELECT tx FROM transactions')]
    actual_spent = {}
    for tx in txs:
        t = tx['tx_json']
        actual_spent[t['Account']] = actual_spent.get(t['Account'], 0) + int(t['Amount'])
    wallets = []
    for row in wallet_rows:
        w = dict(row)
        balance = accounts.get(w['address'], 0)
        committed = sum(o['amount'] for o in operations if o['wallet'] == w['id'] and o['kind'] == 'purchase'
                        and o['status'] not in ('failed', 'expired'))
        w.update(balance_drops=balance, active=w['address'] in accounts,
                 spendable_drops=max(0, balance-RESERVE), committed_drops=committed,
                 spent_drops=actual_spent.get(w['address'], 0) if w['role'] == 'child' else 0,
                 remaining_budget_drops=max(0, w['budget']-committed))
        wallets.append(w)
    for op in operations:
        raw = op.pop('result')
        op['data'] = json.loads(raw) if raw else None
    return {'session_id': str(session_id), 'mode': 'offline_simulation',
            'price_drops': PRICE, 'reserve_drops': RESERVE, 'fee_drops': FEE,
            'wallets': wallets, 'operations': operations,
            'fees_paid_drops': len(txs)*FEE,
            'purchase_spend_drops': sum(w['spent_drops'] for w in wallets if w['role']=='child')}


@router.get('')
def page():
    return FileResponse(ROOT / 'wallet-visualization.html')


@router.post('/sessions', status_code=201)
def create_session():
    ident = uuid.uuid4()
    path = DATA_ROOT / str(ident) / 'lab.sqlite3'
    make_lab(path)
    return snapshot(path, ident)


@router.get('/sessions/{session_id}')
def get_session(session_id: uuid.UUID):
    return snapshot(session_path(session_id), session_id)


@router.post('/sessions/{session_id}/children')
def create_child(session_id: uuid.UUID, body: ChildRequest):
    path = session_path(session_id)
    store = Store(path)
    try:
        store.create_wallet(body.wallet_id, 'tenant-a', 'child', 'master', body.budget_drops)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return snapshot(path, session_id)


@router.post('/sessions/{session_id}/children/{wallet_id}/{action}')
def act(session_id: uuid.UUID, wallet_id: str, action: str, body: ActionRequest):
    path = session_path(session_id)
    if action not in ('fund', 'purchase'):
        raise HTTPException(422, 'Unknown wallet action')
    store, _, merchant, engine = make_lab(path)
    try:
        if action == 'fund':
            result = engine.fund(str(body.operation_id), 'master', wallet_id, RESERVE+100_000, 'tenant-a')
        else:
            merchant.state.fail_after_settlement = body.lose_response
            result = engine.purchase(str(body.operation_id), wallet_id, 'tenant-a')
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'operation': result, 'state': snapshot(path, session_id)}


@router.post('/sessions/{session_id}/operations/{operation_id}/resume')
def resume(session_id: uuid.UUID, operation_id: uuid.UUID):
    path = session_path(session_id)
    _, _, _, engine = make_lab(path)
    try:
        result = engine.resume(str(operation_id), 'tenant-a')
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'operation': result, 'state': snapshot(path, session_id)}
