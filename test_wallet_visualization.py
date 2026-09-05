"""HTTP integration tests for the wallet UI. Never contact a public ledger."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import wallet_visualization as api


class WalletVisualizationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mock = patch.object(api, 'DATA_ROOT', Path(tmp.name))
        mock.start()
        self.addCleanup(mock.stop)
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)
        self.state = self.client.post('/wallets/sessions', json={}).json()
        self.base = '/wallets/sessions/' + self.state['session_id']

    def create(self, name='agent-a', budget=60000):
        return self.client.post(self.base+'/children', json={'wallet_id':name,'budget_drops':budget})

    def action(self, action, name='agent-a', ident=None, lose=False):
        return self.client.post(self.base+'/children/'+name+'/'+action,
                                json={'operation_id':ident or str(uuid.uuid4()),'lose_response':lose})

    def test_router_mounted_in_demo(self):
        import orchestrator
        client = TestClient(orchestrator.app)
        self.assertEqual(client.get('/wallets').status_code, 200)
        self.assertIn('href="/wallets"', client.get('/').text)

    def test_page_and_no_private_fields(self):
        self.assertIn('Offline sandbox', self.client.get('/wallets').text)
        self.assertEqual(self.state['mode'], 'offline_simulation')
        self.assertEqual(len(self.state['wallets']), 2)
        self.assertNotIn('seed', json.dumps(self.state))
        self.assertNotIn('blob', json.dumps(self.state))

    def test_full_flow_and_recovery(self):
        self.assertEqual(self.create().status_code,200)
        self.assertEqual(self.action('fund').json()['operation']['status'],'funded')
        result=self.action('purchase',lose=True).json()
        self.assertEqual(result['operation']['status'],'delivery_failed')
        before=result['state']['purchase_spend_drops']
        op=result['operation']['id']
        recovered=self.client.post(self.base+'/operations/'+op+'/resume',json={}).json()
        self.assertEqual(recovered['operation']['status'],'delivered')
        self.assertEqual(recovered['state']['purchase_spend_drops'],before)
        self.assertEqual(recovered['operation']['hash'],result['operation']['hash'])
        self.assertNotIn('seed',json.dumps(recovered))
        self.assertNotIn('blob',json.dumps(recovered))

    def test_validation_budget_and_idempotency(self):
        self.assertEqual(self.create(budget=-1).status_code,422)
        self.assertEqual(self.create(name='../escape').status_code,422)
        self.create(budget=20000)
        self.action('fund')
        ident=str(uuid.uuid4())
        first=self.action('purchase',ident=ident).json()
        repeated=self.action('purchase',ident=ident).json()
        self.assertEqual(first['operation']['hash'],repeated['operation']['hash'])
        self.assertEqual(self.action('purchase').status_code,409)

    def test_sessions_are_isolated(self):
        self.create()
        other=self.client.post('/wallets/sessions',json={}).json()
        self.assertNotEqual(other['session_id'],self.state['session_id'])
        self.assertEqual(len(other['wallets']),2)
        self.assertEqual(self.client.get('/wallets/sessions/'+str(uuid.uuid4())).status_code,404)
        self.assertEqual(self.client.get('/wallets/sessions/not-a-uuid').status_code,422)


if __name__=='__main__': unittest.main()
