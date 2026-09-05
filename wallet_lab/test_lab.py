import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xrpl.core.binarycodec import decode, encode
if __package__:
    from .lab import FEE, PRICE, RESERVE, make_lab
else:
    from lab import FEE, PRICE, RESERVE, make_lab


class WalletFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.store, self.ledger, self.app, self.engine = make_lab(self.path)
        self.store.create_wallet('a', 'tenant-a', 'child', 'master', PRICE * 2)
        self.store.create_wallet('b', 'tenant-a', 'child', 'master', PRICE)
        self.engine.fund('fund-a', 'master', 'a', RESERVE + 100_000, 'tenant-a')
        self.engine.fund('fund-b', 'master', 'b', RESERVE + 100_000, 'tenant-a')

    def balance(self, wallet):
        return self.ledger.account(self.store.wallet(wallet)['address'])['balance']

    def test_full_flow_real_signatures_no_network(self):
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            before = self.balance('a')
            merchant_before = self.balance('merchant')
            for child in ('a', 'b'):
                result = self.engine.purchase('buy-' + child, child, 'tenant-a')
                self.assertEqual(result['status'], 'delivered')
                tx = self.ledger.validate_signature(self.store.operation(result['id'])['blob'])
                self.assertEqual(tx['Account'], self.store.wallet(child)['address'])
                self.assertNotEqual(tx['Account'], self.store.wallet('master')['address'])
                self.assertIn('InvoiceID', tx)
            self.assertEqual(self.balance('a'), before - PRICE - FEE)
            self.assertEqual(self.balance('merchant'), merchant_before + 2 * PRICE)
            total = sum(self.balance(w) for w in ('master', 'a', 'b', 'merchant'))
            self.assertEqual(total, 20_000_000 + RESERVE - 4 * FEE)

    def test_idempotent_wallet_funding_purchase(self):
        self.assertEqual(self.store.create_wallet('a', 'tenant-a', 'child', 'master', PRICE * 2)['address'], self.store.wallet('a')['address'])
        before = self.balance('master')
        self.engine.fund('fund-a', 'master', 'a', RESERVE + 100_000, 'tenant-a')
        self.assertEqual(before, self.balance('master'))
        a = self.engine.purchase('same', 'a', 'tenant-a')
        after = self.balance('a')
        b = self.engine.purchase('same', 'a', 'tenant-a')
        self.assertEqual(a['hash'], b['hash'])
        self.assertEqual(after, self.balance('a'))
        with self.assertRaisesRegex(ValueError, 'idempotency'):
            self.engine.purchase('same', 'b', 'tenant-a')

    def test_budget_persists_restart(self):
        self.engine.purchase('one', 'b', 'tenant-a')
        _, _, _, restarted = make_lab(self.path)
        with self.assertRaisesRegex(ValueError, 'budget'):
            restarted.purchase('two', 'b', 'tenant-a')
        self.assertIsNone(self.store.operation('two'))

    def test_cross_tenant_disabled(self):
        with self.assertRaisesRegex(ValueError, 'denied'):
            self.engine.purchase('bad', 'a', 'tenant-b')
        with self.store.db() as c:
            c.execute("UPDATE wallets SET enabled=0 WHERE id='a'")
        with self.assertRaisesRegex(ValueError, 'denied'):
            self.engine.purchase('bad', 'a', 'tenant-a')
        self.assertIsNone(self.store.operation('bad'))

    def test_parent_ownership(self):
        with self.assertRaisesRegex(ValueError, 'parent'):
            self.store.create_wallet('foreign', 'tenant-b', 'child', 'master', PRICE)
        self.store.create_wallet('master-2', 'tenant-a', 'master')
        with self.assertRaisesRegex(ValueError, 'Parent mismatch'):
            self.engine.fund('bad', 'master-2', 'a', RESERVE, 'tenant-a')

    def test_unfunded(self):
        self.store.create_wallet('empty', 'tenant-a', 'child', 'master', PRICE)
        with self.assertRaisesRegex(ValueError, 'balance'):
            self.engine.purchase('bad', 'empty', 'tenant-a')

    def test_paid_response_lost_recovery_no_double_charge(self):
        self.app.state.fail_after_settlement = True
        result = self.engine.purchase('lost', 'a', 'tenant-a')
        self.assertEqual(result['status'], 'delivery_failed')
        self.assertIsNotNone(result['hash'])
        after = self.balance('a')
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.engine.purchase('second', 'a', 'tenant-a')
        _, _, _, restarted = make_lab(self.path)
        recovered = restarted.resume('lost', 'tenant-a')
        self.assertEqual(recovered['status'], 'delivered')
        self.assertEqual(recovered['hash'], result['hash'])
        self.assertEqual(after, self.balance('a'))

    def interrupted_purchase(self, ident):
        original = self.engine.merchant.get
        def interrupted(url, **kwargs):
            if 'headers' in kwargs:
                raise TimeoutError('simulated disconnect before submission')
            return original(url, **kwargs)
        with patch.object(self.engine.merchant, 'get', side_effect=interrupted):
            return self.engine.purchase(ident, 'a', 'tenant-a')

    def test_timeout_and_expiry(self):
        result = self.interrupted_purchase('unknown')
        self.assertEqual(result['status'], 'settlement_unknown')
        before = self.balance('a')
        self.ledger.advance(100)
        self.assertEqual(self.engine.resume('unknown', 'tenant-a')['status'], 'expired')
        self.assertEqual(self.balance('a'), before)
        self.assertEqual(self.engine.purchase('replacement', 'a', 'tenant-a')['status'], 'delivered')

    def test_unknown_reuses_signature(self):
        first = self.interrupted_purchase('retry')
        second = self.engine.resume('retry', 'tenant-a')
        self.assertEqual(first['hash'], second['hash'])
        self.assertEqual(second['status'], 'delivered')

    def test_quote_change_rejected_before_signing(self):
        original = self.engine.merchant.get
        def changed(url, **kwargs):
            response = original(url, **kwargs)
            data = response.json()
            data['accepts'][0]['amount'] = '99999'
            response._content = json.dumps(data).encode()
            return response
        before = self.balance('a')
        with patch.object(self.engine.merchant, 'get', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'Quote'):
                self.engine.purchase('changed', 'a', 'tenant-a')
        self.assertEqual(self.store.operation('changed')['status'], 'failed')
        self.assertIsNone(self.store.operation('changed')['blob'])
        self.assertEqual(before, self.balance('a'))

    def test_tampered_signature(self):
        self.engine.purchase('valid', 'a', 'tenant-a')
        tx = decode(self.store.operation('valid')['blob'])
        tx['Amount'] = '1'
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.ledger.submit(encode(tx))

    def test_funding_response_lost_does_not_double_fund(self):
        original = self.ledger.submit
        def lost(blob):
            original(blob)
            raise TimeoutError('funding response lost after ledger commit')
        before = self.balance('master')
        with patch.object(self.ledger, 'submit', side_effect=lost):
            first = self.engine.fund('extra', 'master', 'a', 100_000, 'tenant-a')
        self.assertEqual(first['status'], 'settlement_unknown')
        recovered = self.engine.resume('extra', 'tenant-a')
        self.assertEqual(recovered['status'], 'funded')
        self.assertEqual(first['hash'], recovered['hash'])
        self.assertEqual(self.balance('master'), before - 100_000 - FEE)

    def test_recovery_ownership(self):
        self.engine.purchase('private', 'a', 'tenant-a')
        with self.assertRaisesRegex(ValueError, 'ownership'):
            self.engine.resume('private', 'tenant-b')

    def test_disabled_pending_waits_until_expiry(self):
        first = self.interrupted_purchase('pending')
        before = self.balance('a')
        with self.store.db() as c:
            c.execute("UPDATE wallets SET enabled=0 WHERE id='a'")
        self.assertEqual(self.engine.resume('pending', 'tenant-a')['status'], 'settlement_unknown')
        self.assertIsNone(self.ledger.lookup(first['hash']))
        self.ledger.advance(100)
        self.assertEqual(self.engine.resume('pending', 'tenant-a')['status'], 'expired')
        self.assertEqual(self.balance('a'), before)

    def test_concurrent_duplicates_pay_once(self):
        before = self.balance('a')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.engine.purchase('same', 'a', 'tenant-a'), range(2)))
        self.assertTrue(all(r['status'] == 'delivered' for r in results))
        self.assertEqual(self.balance('a'), before - PRICE - FEE)

    def test_concurrent_budget_cannot_overspend(self):
        def buy(index):
            try:
                return self.engine.purchase(f'parallel-{index}', 'b', 'tenant-a')['status']
            except ValueError:
                return 'rejected'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, range(2)))
        self.assertCountEqual(results, ['delivered', 'rejected'])


if __name__ == '__main__':
    unittest.main()
