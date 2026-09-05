"""Local-demo customer checkout: mock fiat or independently verified Testnet XRP.

Checkout IDs are unguessable bearer capabilities. No card details or wallet keys
are accepted. SQLite preserves payment/hash consumption across server restarts.
"""
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / '.checkout.sqlite3'
TESTNET_RPC = 'https://s.altnet.rippletest.net:51234/'
AMOUNT_DROPS = '100000'
KINDS = {'business_registration_status', 'industry_income_benchmarks'}
router = APIRouter()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS checkouts (
        id TEXT PRIMARY KEY, data_type TEXT NOT NULL, method TEXT NOT NULL,
        status TEXT NOT NULL, destination TEXT NOT NULL, tag INTEGER NOT NULL UNIQUE,
        created REAL NOT NULL, tx_hash TEXT UNIQUE, payer TEXT, run_id INTEGER,
        request_id TEXT, procurement TEXT NOT NULL DEFAULT 'not_started')''')
    return conn


def fetch(checkout_id):
    with db() as c:
        row = c.execute('SELECT * FROM checkouts WHERE id=?', (checkout_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Checkout not found')
    return dict(row)


def public(row):
    return {**row, 'amount_drops': AMOUNT_DROPS, 'amount_xrp': '0.10',
            'fiat_amount': '0.50', 'fiat_currency': 'USD', 'network': 'Testnet',
            'mock': row['method'] == 'fiat',
            'expires_at': row['created'] + 1800}


class Create(BaseModel):
    method: str
    data_type: str


@router.post('/checkout')
def create(body: Create):
    if body.method not in {'wallet', 'fiat'} or body.data_type not in KINDS:
        raise HTTPException(400, 'Unsupported payment method or data product')
    # Customer pays Relay's procurement wallet, not the vendor mirror.
    from xrpl.wallet import Wallet
    destination = Wallet.from_seed(os.environ['XRPL_BUYER_SEED']).classic_address
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('INSERT INTO checkouts(id,data_type,method,status,destination,tag,created) VALUES(?,?,?,?,?,?,?)',
                  (token, body.data_type, body.method, 'pending', destination,
                   secrets.randbelow(2**32), time.time()))
    return public(fetch(token))


@router.get('/checkout/{checkout_id}')
def get(checkout_id: str):
    return public(fetch(checkout_id))


class MockResult(BaseModel):
    outcome: str


@router.post('/checkout/{checkout_id}/mock')
def mock(checkout_id: str, body: MockResult):
    row = fetch(checkout_id)
    if row['method'] != 'fiat':
        raise HTTPException(400, 'Mock endpoint cannot confirm a wallet payment')
    if body.outcome not in {'paid', 'declined', 'cancelled'}:
        raise HTTPException(400, 'Unknown mock outcome')
    if row['status'] == 'paid':
        return public(row)
    if time.time() > row['created'] + 1800:
        raise HTTPException(410, 'Checkout expired. Create another checkout.')
    with db() as c:
        c.execute("UPDATE checkouts SET status=? WHERE id=? AND status IN ('pending','declined')",
                  (body.outcome, checkout_id))
    return public(fetch(checkout_id))


class Verify(BaseModel):
    tx_hash: str


def validate_transaction(row, result):
    tx = result.get('tx_json', result)
    meta = result.get('meta')
    if not result.get('validated') or not isinstance(meta, dict):
        raise HTTPException(409, 'Transaction not validated yet. Recheck this same hash; do not pay again.')
    if meta.get('TransactionResult') != 'tesSUCCESS':
        raise HTTPException(400, 'Transaction did not succeed')
    if (tx.get('TransactionType') != 'Payment' or tx.get('Destination') != row['destination']
            or tx.get('DestinationTag') != row['tag']
            or tx.get('Amount', tx.get('DeliverMax')) != AMOUNT_DROPS
            or meta.get('delivered_amount') != AMOUNT_DROPS
            or int(tx.get('Flags', 0)) & 0x00020000
            or tx.get('Account') == row['destination']):
        raise HTTPException(400, 'Payment does not match this order: destination, tag or exact delivered amount is wrong')
    return tx.get('Account')


@router.post('/checkout/{checkout_id}/verify')
def verify(checkout_id: str, body: Verify):
    row = fetch(checkout_id)
    if row['method'] != 'wallet':
        raise HTTPException(400, 'Not a wallet checkout')
    if row['status'] == 'paid':
        return public(row)
    tx_hash = body.tx_hash.strip().upper()
    if not re.fullmatch(r'[A-F0-9]{64}', tx_hash):
        raise HTTPException(400, 'Enter a valid 64-character transaction hash')
    try:
        response = requests.post(TESTNET_RPC, json={'method': 'tx', 'params': [{'transaction': tx_hash}]}, timeout=20)
        response.raise_for_status()
        result = response.json()['result']
    except (requests.RequestException, ValueError, KeyError):
        raise HTTPException(503, 'Testnet verification unavailable. Keep this hash and recheck; do not pay again.')
    if result.get('error'):
        raise HTTPException(409, 'Transaction not found on Testnet yet. Recheck this hash; do not pay again.')
    payer = validate_transaction(row, result)
    try:
        with db() as c:
            c.execute("UPDATE checkouts SET status='paid', tx_hash=?, payer=? WHERE id=? AND status='pending'",
                      (tx_hash, payer, checkout_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Transaction already used by another checkout')
    return public(fetch(checkout_id))


def claim(checkout_id, data_type, run_id, request_id):
    """Called under the orchestrator run lock; returns prior run on retries."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM checkouts WHERE id=?', (checkout_id,)).fetchone()
        if not row or row['status'] != 'paid':
            raise HTTPException(402, 'Complete customer payment before starting procurement')
        if row['data_type'] != data_type:
            raise HTTPException(409, 'This payment belongs to another data product')
        if row['request_id']:
            return {'started': True, 'run_id': row['run_id'], 'request_id': row['request_id'], 'reused': True}
        c.execute("UPDATE checkouts SET run_id=?, request_id=?, procurement='starting' WHERE id=?",
                  (run_id, request_id, checkout_id))
    return None


def finish(checkout_id, phase):
    # This demo does not automatically reverse a confirmed blockchain payment.
    outcome = 'sample_delivered' if phase == 'delivered' else 'needs_review'
    with db() as c:
        c.execute('UPDATE checkouts SET procurement=? WHERE id=?', (outcome, checkout_id))


@router.get('/checkout-page')
def checkout_page():
    return FileResponse(ROOT / 'customer-checkout.html', headers={'Cache-Control': 'no-store'})


@router.get('/checkout-sdk.js')
def wallet_sdk():
    return FileResponse(ROOT / 'assets/vendor/gemwallet-api-3.8.0.js', media_type='text/javascript')
