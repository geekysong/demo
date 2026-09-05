"""Delivery fixtures must not be replaced by unrelated live declarations."""
import base64
import json
import unittest
from unittest.mock import Mock, patch

import marketplace


class DeliverySampleTests(unittest.TestCase):
    def test_cpi_declaration_does_not_replace_industry_wages(self):
        declaration = {
            'accepts': [{'network': 'xrpl:0', 'asset': 'XRP', 'amount': '20000'}],
            'extensions': {'bazaar': {'info': {'output': {'example': {
                'series': [{'requested': 'cpi', 'series_id': 'CUUR0000SA0'}]
            }}}}},
        }
        response = Mock(status_code=402, headers={
            'PAYMENT-REQUIRED': base64.b64encode(json.dumps(declaration).encode()).decode()
        })
        source = next(s for s in marketplace.SOURCES if s['id'] == 'T54-BLS')
        with patch.object(marketplace.requests, 'get', return_value=response):
            candidate = marketplace.fetch_candidate(source)
        self.assertEqual(candidate['advertised_sample']['series'][0]['requested'], 'cpi')
        self.assertEqual(candidate['sample_data']['metric'], 'industry_wages')
        self.assertEqual(candidate['sample_data'], marketplace.sample_for('T54-BLS'))
        self.assertTrue(candidate['sample_data']['sample'])
        self.assertIn('historical', candidate['delivery_mode'])

    def test_unavailable_source_keeps_labeled_wage_sample(self):
        with patch.object(marketplace.requests, 'get', side_effect=RuntimeError('offline')):
            candidates = marketplace.load_candidates()
        wages = next(c for c in candidates if c['id'] == 'T54-BLS')
        self.assertEqual(wages['discovery_status'], 'fallback')
        self.assertEqual(wages['sample_data']['industry']['code'], '541100')
        self.assertIn('30-day', wages['sample_note'])
        lei = next(c for c in candidates if c['id'] == 'T54-LEI')
        self.assertIn('lei', lei['sample_data'])


if __name__ == '__main__':
    unittest.main()
