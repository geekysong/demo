"""Isolated offline wallet lab: real XRPL/x402 signatures, simulated settlement.

Never connects to a public ledger. Private seeds are disposable LOCAL TEST keys.
"""
from __future__ import annotations

import base64
import fcntl
from functools import wraps
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from xrpl.clients import JsonRpcClient
from xrpl.core.binarycodec import decode, encode_for_signing
from xrpl.core.keypairs import derive_classic_address, is_valid_message
from xrpl.models.response import Response, ResponseStatus
from xrpl.models.transactions import Payment
from xrpl.transaction import autofill, sign
from xrpl.wallet import Wallet
from x402_xrpl.client import XRPLPresignedPaymentPayer, XRPLPresignedPaymentPayerOptions
from x402_xrpl.client.presigned_payment_payer import invoice_id_to_invoice_id_field
from x402_xrpl.types import PaymentRequirements

# Explicit simulation parameters, not claims about current public Testnet reserves.
RESERVE = 1_000_000
FEE = 12
PRICE = 20_000
NETWORK = 'xrpl:1'
PRODUCT = 'business_registration_status'
TERMINAL = ('delivered', 'funded', 'expired', 'failed')


def tx_hash(blob):
    return hashlib.sha512(bytes.fromhex('54584E00' + blob)).hexdigest()[:64].upper()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        with self.db() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS wallets(
                    id TEXT PRIMARY KEY, parent TEXT REFERENCES wallets(id),
                    tenant TEXT NOT NULL, role TEXT NOT NULL, address TEXT UNIQUE NOT NULL,
                    seed TEXT NOT NULL, budget INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS operations(
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, kind TEXT NOT NULL,
                    wallet TEXT NOT NULL REFERENCES wallets(id), destination TEXT NOT NULL,
                    amount INTEGER NOT NULL, status TEXT NOT NULL,
                    invoice TEXT, quote TEXT, blob TEXT, hash TEXT UNIQUE,
                    last_ledger INTEGER, result TEXT, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_pending_per_wallet ON operations(wallet)
                    WHERE status NOT IN ('delivered','funded','expired','failed');
                CREATE TABLE IF NOT EXISTS accounts(address TEXT PRIMARY KEY, balance INTEGER, sequence INTEGER);
                CREATE TABLE IF NOT EXISTS transactions(hash TEXT PRIMARY KEY, tx TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, quote TEXT NOT NULL,
                    response TEXT, hash TEXT);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value INTEGER);
                INSERT OR IGNORE INTO metadata VALUES('ledger',1000);
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def wallet(self, ident):
        with self.db() as c:
            row = c.execute('SELECT * FROM wallets WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError('Unknown wallet')
        return dict(row)

    def operation(self, ident):
        with self.db() as c:
            row = c.execute('SELECT * FROM operations WHERE id=?', (ident,)).fetchone()
        return dict(row) if row else None

    def update(self, ident, **values):
        with self.db() as c:
            c.execute('UPDATE operations SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?',
                      (*values.values(), ident))

    def create_wallet(self, ident, tenant, role, parent=None, budget=0):
        if role not in ('master', 'child', 'merchant') or type(budget) is not int or budget < 0:
            raise ValueError('Invalid wallet configuration')
        if role == 'child':
            p = self.wallet(parent)
            if p['role'] != 'master' or p['tenant'] != tenant or not p['enabled']:
                raise ValueError('Invalid parent ownership or state')
        elif parent is not None:
            raise ValueError('Only child wallets have a parent')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM wallets WHERE id=?', (ident,)).fetchone()
            if old:
                if (old['tenant'], old['role'], old['parent'], old['budget']) != (tenant, role, parent, budget):
                    raise ValueError('Wallet idempotency conflict')
                return {k: old[k] for k in ('id', 'parent', 'tenant', 'role', 'address', 'budget')}
            w = Wallet.create()
            c.execute('INSERT INTO wallets(id,parent,tenant,role,address,seed,budget) VALUES(?,?,?,?,?,?,?)',
                      (ident, parent, tenant, role, w.classic_address, w.seed, budget))
        return {k: self.wallet(ident)[k] for k in ('id', 'parent', 'tenant', 'role', 'address', 'budget')}


class LocalLedger:
    """Small persistent direct-XRP ledger model; not a rippled implementation."""
    def __init__(self, store):
        self.store = store

    def bootstrap(self, address, balance):
        # Test fixtures only; INSERT OR IGNORE avoids minting again on restart.
        with self.store.db() as c:
            c.execute('INSERT OR IGNORE INTO accounts VALUES(?,?,1)', (address, balance))

    def account(self, address):
        with self.store.db() as c:
            row = c.execute('SELECT * FROM accounts WHERE address=?', (address,)).fetchone()
        return dict(row) if row else {'address': address, 'balance': 0, 'sequence': 0}

    @property
    def index(self):
        with self.store.db() as c:
            return c.execute("SELECT value FROM metadata WHERE key='ledger'").fetchone()[0]

    def advance(self, count):
        with self.store.db() as c:
            c.execute("UPDATE metadata SET value=value+? WHERE key='ledger'", (count,))

    def lookup(self, digest):
        with self.store.db() as c:
            row = c.execute('SELECT tx FROM transactions WHERE hash=?', (digest,)).fetchone()
        return json.loads(row[0]) if row else None

    def validate_signature(self, blob):
        tx = decode(blob)
        if tx['TransactionType'] != 'Payment' or not isinstance(tx['Amount'], str):
            raise ValueError('Only direct XRP payments supported')
        if any(k in tx for k in ('SendMax', 'Paths', 'DeliverMin')) or tx.get('Flags', 0) & 0x20000:
            raise ValueError('Unsupported payment feature')
        if derive_classic_address(tx['SigningPubKey']) != tx['Account']:
            raise ValueError('Signing account mismatch')
        if not is_valid_message(bytes.fromhex(encode_for_signing(tx)),
                                bytes.fromhex(tx['TxnSignature']), tx['SigningPubKey']):
            raise ValueError('Invalid signature')
        return tx

    def submit(self, blob):
        tx = self.validate_signature(blob)
        digest = tx_hash(blob)
        amount, fee = int(tx['Amount']), int(tx['Fee'])
        if amount <= 0 or fee != FEE or tx['Account'] == tx['Destination']:
            raise ValueError('Invalid payment amount, fee or destination')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT tx FROM transactions WHERE hash=?', (digest,)).fetchone()
            if old:
                return json.loads(old[0])
            index = c.execute("SELECT value FROM metadata WHERE key='ledger'").fetchone()[0]
            sender = c.execute('SELECT * FROM accounts WHERE address=?', (tx['Account'],)).fetchone()
            receiver = c.execute('SELECT * FROM accounts WHERE address=?', (tx['Destination'],)).fetchone()
            if tx['LastLedgerSequence'] < index + 1:
                raise ValueError('Expired transaction')
            if not sender or tx['Sequence'] != sender['sequence']:
                raise ValueError('Sequence mismatch')
            if sender['balance'] - amount - fee < RESERVE:
                raise ValueError('Insufficient spendable balance')
            if not receiver and amount < RESERVE:
                raise ValueError('Destination activation reserve missing')
            c.execute('UPDATE accounts SET balance=balance-?,sequence=sequence+1 WHERE address=?',
                      (amount + fee, tx['Account']))
            c.execute('INSERT INTO accounts VALUES(?,?,1) ON CONFLICT(address) DO UPDATE SET balance=balance+excluded.balance',
                      (tx['Destination'], amount))
            result = {'validated': True, 'hash': digest, 'tx_json': tx,
                      'ledger_index': index + 1, 'meta': {'TransactionResult': 'tesSUCCESS'}}
            c.execute('INSERT INTO transactions VALUES(?,?)', (digest, json.dumps(result)))
            c.execute("UPDATE metadata SET value=value+1 WHERE key='ledger'")
        return result


class LocalRpc(JsonRpcClient):
    """Exercises SDK autofill without opening sockets or contacting Testnet."""
    def __init__(self, ledger):
        super().__init__('http://offline.invalid')
        self.ledger = ledger

    async def _request_impl(self, request, *, timeout=10):
        method = request.to_dict()['method']
        if method == 'server_info':
            result = {'info': {'network_id': 1, 'build_version': '2.0.0'}}
        elif method == 'ledger':
            result = {'ledger_index': self.ledger.index}
        elif method == 'fee':
            result = {'drops': {'open_ledger_fee': str(FEE), 'minimum_fee': str(FEE)}}
        elif method == 'account_info':
            account = self.ledger.account(request.account)
            result = {'account_data': {'Balance': str(account['balance']), 'Sequence': account['sequence']}}
        else:
            raise ValueError(f'Unsupported offline RPC: {method}')
        return Response(status=ResponseStatus.SUCCESS, result=result)


def merchant_app(store, ledger, address):
    app = FastAPI()
    # Failure injection is confined to this in-process local simulator.
    app.state.fail_after_settlement = False

    @app.get('/data')
    def data(request: Request):
        header = request.headers.get('PAYMENT-SIGNATURE')
        if not header:
            invoice = uuid.uuid4().hex
            quote = PaymentRequirements('exact', NETWORK, str(PRICE), 'XRP', address, 60,
                                        {'invoiceId': invoice}).to_dict()
            with store.db() as c:
                c.execute('INSERT INTO invoices(id,quote) VALUES(?,?)', (invoice, json.dumps(quote)))
            return JSONResponse({'x402Version': 2, 'accepts': [quote]}, status_code=402)
        try:
            payload = json.loads(base64.b64decode(header))
            invoice, blob = payload['payload']['invoiceId'], payload['payload']['signedTxBlob']
            with store.db() as c:
                row = c.execute('SELECT * FROM invoices WHERE id=?', (invoice,)).fetchone()
            if not row or payload['x402Version'] != 2 or payload['accepted'] != json.loads(row['quote']):
                raise ValueError('Invoice or quote mismatch')
            tx = ledger.validate_signature(blob)
            quote = json.loads(row['quote'])
            if tx['Destination'] != address or tx['Amount'] != quote['amount']:
                raise ValueError('Payment destination or amount mismatch')
            if tx.get('InvoiceID') != invoice_id_to_invoice_id_field(invoice):
                raise ValueError('Invoice binding mismatch')
            if not any(m['Memo'].get('MemoData') == invoice.encode().hex().upper() for m in tx.get('Memos', [])):
                raise ValueError('Invoice memo missing')
            digest = tx_hash(blob)
            # Bind before settlement, so restart cannot reuse an invoice for another payment.
            with store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                current = c.execute('SELECT * FROM invoices WHERE id=?', (invoice,)).fetchone()
                if current['hash'] and current['hash'] != digest:
                    raise ValueError('Invoice already bound to another transaction')
                c.execute('UPDATE invoices SET hash=? WHERE id=?', (digest, invoice))
            receipt = ledger.submit(blob)  # idempotent for this exact transaction
            result = {'sample': True, 'data_type': PRODUCT,
                      'result': {'legal_name': 'Wallet Lab Example Ltd', 'entity_status': 'ACTIVE'}}
            with store.db() as c:
                c.execute('UPDATE invoices SET response=? WHERE id=?', (json.dumps(result), invoice))
            if app.state.fail_after_settlement:
                return JSONResponse({'reason': 'simulated_response_lost_after_payment'}, status_code=503)
            settlement = {'success': True, 'transaction': receipt['hash'], 'network': NETWORK}
            return JSONResponse(result, headers={'PAYMENT-RESPONSE': base64.b64encode(json.dumps(settlement).encode()).decode()})
        except (ValueError, KeyError, TypeError) as e:
            return JSONResponse({'error': str(e)}, status_code=400)

    return app


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        # Serialize the local prototype, including across processes.
        with open(self.store.path.with_suffix('.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return method(self, *args, **kwargs)
    return wrapped


class Engine:
    def __init__(self, store, ledger, merchant, merchant_address):
        self.store, self.ledger, self.merchant = store, ledger, merchant
        self.merchant_address = merchant_address
        self.rpc = LocalRpc(ledger)

    def _authorize(self, wallet_id, tenant, role):
        w = self.store.wallet(wallet_id)
        if w['tenant'] != tenant or w['role'] != role or not w['enabled']:
            raise ValueError('Wallet ownership, role or state denied')
        return w

    def _reserve(self, ident, kind, w, destination, amount):
        fingerprint = json.dumps([kind, w['id'], destination, amount])
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM operations WHERE id=?', (ident,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ValueError('Operation idempotency conflict')
                return False
            if type(amount) is not int or amount <= 0:
                raise ValueError('Amount must be positive integer drops')
            if kind == 'purchase':
                used = c.execute("SELECT COALESCE(SUM(amount),0) FROM operations WHERE wallet=? AND kind='purchase' AND status NOT IN ('expired','failed')", (w['id'],)).fetchone()[0]
                if used + amount > w['budget']:
                    raise ValueError('Purchase budget exceeded')
            if self.ledger.account(w['address'])['balance'] - RESERVE < amount + FEE:
                raise ValueError('Insufficient spendable balance')
            try:
                c.execute('INSERT INTO operations(id,fingerprint,kind,wallet,destination,amount,status) VALUES(?,?,?,?,?,?,?)',
                          (ident, fingerprint, kind, w['id'], destination, amount, 'reserved'))
            except sqlite3.IntegrityError as e:
                raise ValueError('Wallet has a pending operation; reconcile it first') from e
        return True

    def _save_signed(self, ident, blob, invoice=None, quote=None):
        tx = decode(blob)
        op = self.store.operation(ident)
        w = self.store.wallet(op['wallet'])
        if (tx['Account'], tx['Destination'], int(tx['Amount']), int(tx['Fee'])) != (w['address'], op['destination'], op['amount'], FEE):
            raise ValueError('Signed payment differs from authorized operation')
        self.store.update(ident, status='signed', blob=blob, hash=tx_hash(blob),
                          last_ledger=tx['LastLedgerSequence'], invoice=invoice,
                          quote=json.dumps(quote) if quote else None)

    @serialized
    def fund(self, ident, master, child, amount, tenant):
        w = self._authorize(master, tenant, 'master')
        ch = self._authorize(child, tenant, 'child')
        if ch['parent'] != master:
            raise ValueError('Parent mismatch')
        if self._reserve(ident, 'funding', w, ch['address'], amount):
            try:
                tx = autofill(Payment(account=w['address'], destination=ch['address'], amount=str(amount)), self.rpc)
                self._save_signed(ident, sign(tx, Wallet.from_seed(w['seed'])).blob())
            except Exception:
                self.store.update(ident, status='failed', error='Signing failed before submission')
                raise
        return self._resume(ident, tenant)

    @serialized
    def purchase(self, ident, child, tenant, amount=PRICE):
        w = self._authorize(child, tenant, 'child')
        if self._reserve(ident, 'purchase', w, self.merchant_address, amount):
            try:
                response = self.merchant.get('/data')
                if response.status_code != 402:
                    raise ValueError('Expected HTTP 402')
                accepts = response.json()['accepts']
                valid = [q for q in accepts if q['network'] == NETWORK and q['scheme'] == 'exact'
                         and q['asset'] == 'XRP' and q['payTo'] == self.merchant_address
                         and q['amount'] == str(amount) and 0 < q['maxTimeoutSeconds'] <= 60]
                if len(valid) != 1:
                    raise ValueError('Quote differs from authorized purchase')
                req = PaymentRequirements.from_dict(valid[0])
                payer = XRPLPresignedPaymentPayer(XRPLPresignedPaymentPayerOptions(
                    wallet=Wallet.from_seed(w['seed']), network=NETWORK,
                    rpc_url='http://offline.invalid', invoice_binding='both'), client=self.rpc)
                prepared = payer.prepare_payment(req)
                self._save_signed(ident, prepared.signed_tx_blob, prepared.invoice_id, valid[0])
            except Exception:
                self.store.update(ident, status='failed', error='Quote or signing failed before submission')
                raise
        return self._resume(ident, tenant)

    @serialized
    def resume(self, ident, tenant):
        return self._resume(ident, tenant)

    def _resume(self, ident, tenant):
        op = self.store.operation(ident)
        if not op:
            raise ValueError('Unknown operation')
        w = self.store.wallet(op['wallet'])
        # Recovery may reconcile an already signed payment even when the wallet is disabled.
        if w['tenant'] != tenant:
            raise ValueError('Operation ownership denied')
        if op['status'] in TERMINAL:
            return self.public(ident)
        if not op['blob']:
            # No signed blob was persisted, so this implementation could not have submitted.
            self.store.update(ident, status='failed', error='Interrupted before signed transaction persisted')
            return self.public(ident)
        settled = self.ledger.lookup(op['hash'])
        if settled is None and self.ledger.index > op['last_ledger']:
            self.store.update(ident, status='expired')
            return self.public(ident)
        # This local ledger has complete history. A real adapter must handle history gaps.
        if not w['enabled'] and settled is None:
            self.store.update(ident, status='settlement_unknown', error='Disabled; reconcile only until expiry')
            return self.public(ident)
        self.store.update(ident, status='settlement_unknown', error=None)
        try:
            if op['kind'] == 'funding':
                self.ledger.submit(op['blob'])
                data = None
            else:
                header = base64.b64encode(json.dumps({'x402Version': 2, 'accepted': json.loads(op['quote']),
                    'payload': {'signedTxBlob': op['blob'], 'invoiceId': op['invoice']}}).encode()).decode()
                response = self.merchant.get('/data', headers={'PAYMENT-SIGNATURE': header})
                if response.status_code != 200:
                    raise ValueError(f'Merchant HTTP {response.status_code}; reconciliation required')
                receipt = json.loads(base64.b64decode(response.headers['PAYMENT-RESPONSE']))
                if receipt.get('transaction') != op['hash'] or receipt.get('network') != NETWORK or receipt.get('success') is not True:
                    raise ValueError('Settlement receipt mismatch')
                data = response.json()
                if data.get('sample') is not True or data.get('data_type') != PRODUCT or not isinstance(data.get('result'), dict):
                    raise ValueError('Delivery validation failed')
            actual = self.ledger.lookup(op['hash'])
            tx = actual['tx_json'] if actual else {}
            if not actual or not actual['validated'] or actual['meta']['TransactionResult'] != 'tesSUCCESS':
                raise ValueError('Settlement unconfirmed')
            if (tx.get('Account'), tx.get('Destination'), tx.get('Amount')) != (w['address'], op['destination'], str(op['amount'])):
                raise ValueError('Independent transaction verification mismatch')
            self.store.update(ident, status='funded' if op['kind'] == 'funding' else 'delivered',
                              result=json.dumps(data), error=None)
        except Exception as e:
            paid = self.ledger.lookup(op['hash']) is not None
            self.store.update(ident, status='delivery_failed' if paid and op['kind'] == 'purchase' else 'settlement_unknown',
                              error=str(e))
        return self.public(ident)

    def public(self, ident):
        op = self.store.operation(ident)
        return {k: op[k] for k in ('id', 'kind', 'wallet', 'destination', 'amount', 'status', 'hash', 'error')}


def make_lab(path):
    store = Store(path)
    store.create_wallet('master', 'tenant-a', 'master')
    store.create_wallet('merchant', 'vendor', 'merchant')
    ledger = LocalLedger(store)
    ledger.bootstrap(store.wallet('master')['address'], 20_000_000)
    ledger.bootstrap(store.wallet('merchant')['address'], RESERVE)
    app = merchant_app(store, ledger, store.wallet('merchant')['address'])
    engine = Engine(store, ledger, TestClient(app), store.wallet('merchant')['address'])
    return store, ledger, app, engine
