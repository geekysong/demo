import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock
import marketplace
import policy_filter
import orchestrator
from procurement_checks import validate_quote, confirm_payment, validate_delivery, decision_record


class ProcurementChecks(unittest.TestCase):
    def setUp(self):
        self.c = marketplace.fallback_candidates()[0]
        self.q = dict(scheme='exact', network='xrpl:1', asset='XRP', payTo='merchant', amount='20000', maxTimeoutSeconds=60)

    def test_quote_substitution_and_budgets(self):
        self.assertEqual(validate_quote(self.q, self.c, 'merchant', policy_filter.POLICY, 0)['status'], 'pass')
        for field, value in [('scheme','other'),('network','xrpl:0'),('asset','RLUSD'),('payTo','attacker'),('amount','20001'),('amount','-1'),('amount',True)]:
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                validate_quote({**self.q, field:value}, self.c, 'merchant', policy_filter.POLICY, 0)
        for p, spent in [({'per_tx_cap_drops':1},0), ({'per_applicant_cumulative_cap_drops':20000},1)]:
            with self.assertRaises(ValueError):
                validate_quote(self.q,self.c,'merchant',p,spent)

    def test_chain_success_must_bind_actual_payment(self):
        tx=dict(validated=True, TransactionType='Payment', Account='buyer', Destination='merchant', Amount='20000',meta={'TransactionResult':'tesSUCCESS','delivered_amount':'20000'})
        self.assertTrue(confirm_payment(tx,'buyer','merchant',20000))
        for change in [{'Account':'other'},{'Destination':'other'},{'Amount':'1'},{'Flags':0x20000},{'validated':False},{'meta':{'TransactionResult':'tesSUCCESS','delivered_amount':'1'}}]:
            self.assertFalse(confirm_payment({**tx,**change},'buyer','merchant',20000))
        self.assertTrue(confirm_payment({'validated':True,'meta':tx['meta'],'tx_json':tx},'buyer','merchant',20000))

    def test_historical_wages_rejected_and_lei_uncertified(self):
        wages=orchestrator._mirror_payload('T54-BLS')
        result=validate_delivery(wages,'industry_income_benchmarks','US',30,datetime(2026,9,5,tzinfo=timezone.utc))
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name']=='freshness'),'fail')
        lei=validate_delivery(orchestrator._mirror_payload('T54-LEI'),'business_registration_status','US',30)
        self.assertEqual(lei['status'],'unknown')
        self.assertEqual(validate_delivery({'result':[]},'x','US',30)['status'],'rejected')

    def test_changed_quote_never_reaches_signer(self):
        response=Mock(status_code=402)
        response.json.return_value={'accepts':[{**self.q,'payTo':'attacker'}]}
        with patch.object(orchestrator.marketplace,'load_candidates',return_value=[self.c]), patch.object(orchestrator,'query_balance',return_value=1000000), patch.object(orchestrator.requests,'get',return_value=response), patch.object(orchestrator,'append_audit') as audit, patch.object(orchestrator,'XRPLPresignedPaymentPayer') as signer, patch.object(orchestrator.time,'sleep'), patch.object(orchestrator,'get_applicant_spent',return_value=0):
            orchestrator.run_real_flow(1,'test','default','test','test',612,self.c['category'],'US',30)
            signer.assert_not_called()
            self.assertEqual(orchestrator.get_state()['phase'],'failed')
            self.assertEqual(audit.call_args.args[0]['payment_status'],'not_started')
            self.assertIn('Quote rejected',orchestrator.get_state()['error'])

    def test_paid_sample_requires_review_without_platform_fee(self):
        c = marketplace.fallback_candidates()[1]
        q = {**self.q, 'payTo': orchestrator.PAY_TO}
        quote = Mock(status_code=402)
        quote.json.return_value = {'accepts': [q]}
        delivery = Mock(status_code=200, headers={'PAYMENT-RESPONSE': 'fixture'})
        delivery.json.return_value = orchestrator._mirror_payload(c['id'])
        buyer = orchestrator.Wallet.from_seed(orchestrator.BUYER_SEED).classic_address
        tx = dict(validated=True, TransactionType='Payment', Account=buyer,
                  Destination=orchestrator.PAY_TO, Amount='20000',
                  meta={'TransactionResult':'tesSUCCESS','delivered_amount':'20000'})
        with patch.object(orchestrator.marketplace,'load_candidates',return_value=[c]), patch.object(orchestrator,'query_balance',return_value=1000000), patch.object(orchestrator.requests,'get',side_effect=[quote,delivery]), patch.object(orchestrator,'append_audit') as audit, patch.object(orchestrator,'XRPLPresignedPaymentPayer'), patch.object(orchestrator,'add_relay_comment',return_value='signed-fixture'), patch.object(orchestrator,'decode_payment_response',return_value={'transaction':'A'*64}), patch.object(orchestrator,'JsonRpcClient') as rpc, patch.object(orchestrator.time,'sleep'), patch.object(orchestrator,'get_applicant_spent',return_value=0), patch.object(orchestrator,'add_applicant_spend') as spend, patch.object(orchestrator.billing,'bill_purchase') as bill:
            rpc.return_value.request.return_value.result = tx
            orchestrator.run_real_flow(1,'test','default','test','test',612,c['category'],'US',30)
            state=orchestrator.get_state()
            self.assertEqual(state['phase'],'delivery_needs_review',state.get('error'))
            self.assertEqual(state['payment_status'],'confirmed')
            self.assertEqual(state['validation_status'],'rejected')
            spend.assert_called_once_with('test',20000)
            bill.assert_not_called()
            self.assertEqual(audit.call_args.args[0]['validation_status'],'rejected')

    def test_decision_is_explicitly_rule_based(self):
        d=decision_record(self.c,[],{'data_type':self.c['category']},policy_filter.POLICY)
        self.assertEqual(d['mode'],'deterministic_policy')
        self.assertIn('lowest price',d['explanation'])

if __name__=='__main__': unittest.main()
