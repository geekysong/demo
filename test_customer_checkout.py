"""Payment correctness tests. RPC is stubbed: these tests never move funds."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import customer_checkout as checkout
import orchestrator


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(checkout, 'DB_PATH', Path(self.tmp.name) / 'checkout.db')
        self.patch.start()
        self.client = TestClient(orchestrator.app)
        orchestrator.set_state(phase='idle')
        orchestrator.RUN_ACTIVE = False

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def order(self, method='fiat'):
        return self.client.post('/checkout', json={'method':method,'data_type':'business_registration_status'}).json()

    def pay(self, order, outcome='paid'):
        return self.client.post('/checkout/'+order['id']+'/mock', json={'outcome':outcome})

    def transaction(self, order):
        return {'validated':True, 'TransactionType':'Payment', 'Destination':order['destination'],
                'DestinationTag':order['tag'], 'Amount':'100000', 'Account':'rTestPayer',
                'meta':{'TransactionResult':'tesSUCCESS','delivered_amount':'100000'}}

    def verify(self, order, result, hash='A'*64):
        with patch.object(checkout.requests, 'post') as rpc:
            rpc.return_value.json.return_value={'result':result}
            return self.client.post('/checkout/'+order['id']+'/verify', json={'tx_hash':hash})

    def test_payment_required_and_no_wallet_mock_bypass(self):
        self.assertEqual(self.client.post('/run', json={}).status_code,402)
        o=self.order('wallet')
        self.assertEqual(self.pay(o).status_code,400)
        self.assertEqual(self.client.post('/run',json={'checkout_id':o['id']}).status_code,402)

    def test_mock_decline_retry_cancel_and_idempotency(self):
        o=self.order()
        self.assertEqual(self.pay(o,'declined').json()['status'],'declined')
        self.assertEqual(self.pay(o).json()['status'],'paid')
        self.assertEqual(self.pay(o,'cancelled').json()['status'],'paid')
        cancelled=self.order()
        self.pay(cancelled,'cancelled')
        self.assertEqual(self.pay(cancelled).json()['status'],'cancelled')

    def test_exact_testnet_payment_and_duplicate_confirmation(self):
        o=self.order('wallet'); result=self.transaction(o)
        self.assertEqual(self.verify(o,result).json()['status'],'paid')
        self.assertEqual(self.verify(o,result).json()['tx_hash'],'A'*64)
        another=self.order('wallet')
        self.assertEqual(self.verify(another,self.transaction(another)).status_code,409)

    def test_wrong_recipient_tag_amount_partial_failed_unvalidated(self):
        for change in [{'Destination':'wrong'}, {'DestinationTag':1}, {'Amount':'1'}, {'Flags':131072},
                       {'validated':False}, {'meta':{'TransactionResult':'tecFAIL','delivered_amount':'100000'}},
                       {'meta':{'TransactionResult':'tesSUCCESS','delivered_amount':'1'}}]:
            o=self.order('wallet'); result={**self.transaction(o),**change}
            self.assertIn(self.verify(o,result).status_code,[400,409])
            self.assertEqual(checkout.fetch(o['id'])['status'],'pending')

    def test_product_binding_and_single_procurement(self):
        o=self.order();self.pay(o)
        with patch.object(orchestrator.threading,'Thread') as worker:
            bad=self.client.post('/run',json={'checkout_id':o['id'],'data_type':'industry_income_benchmarks'})
            self.assertEqual(bad.status_code,409)
            first=self.client.post('/run',json={'checkout_id':o['id']})
            second=self.client.post('/run',json={'checkout_id':o['id']})
            self.assertEqual(first.status_code,200)
            self.assertEqual(first.json()['request_id'],second.json()['request_id'])
            self.assertTrue(second.json()['reused'])
            self.assertEqual(worker.return_value.start.call_count,1)

    def test_failure_keeps_payment_visible(self):
        o=self.order();self.pay(o);checkout.finish(o['id'],'failed')
        row=checkout.fetch(o['id'])
        self.assertEqual(row['status'],'paid');self.assertEqual(row['procurement'],'needs_review')

    def test_pages_and_sdk(self):
        self.assertIn('Choose how you pay',self.client.get('/').text)
        self.assertIn('Simulate payment',self.client.get('/checkout-page').text)
        self.assertEqual(self.client.get('/checkout-sdk.js').status_code,200)

if __name__=='__main__':unittest.main()
