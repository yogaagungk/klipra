import os
import unittest
from unittest.mock import patch

import httpx
import jev_ranker


def fixture():
    return {'language': 'en', 'segments': [{'text': 'test', 'words': [
        {'start': i, 'end': i + 0.8, 'word': f' word{i}'} for i in range(90)
    ]}]}


class JevRankerTests(unittest.TestCase):
    def test_candidates_span_source_and_respect_bounds(self):
        clips = jev_ranker.candidates(fixture(), 90, 15, 60, 8)
        self.assertGreater(len(clips), 1)
        self.assertLessEqual(len(clips), 8)
        for c in clips:
            self.assertGreaterEqual(c['start'], 0)
            self.assertLessEqual(c['end'], 90)
            self.assertGreaterEqual(c['end'] - c['start'], 15)
            self.assertLessEqual(c['end'] - c['start'], 60)
        self.assertGreater(clips[-1]['end'], 80)

    @patch.dict(os.environ, {'JEV_API_KEY': 'test-key', 'JEV_MODEL': 'test-model'}, clear=True)
    def test_request_and_scoring(self):
        def handler(request):
            self.assertEqual(request.url, 'https://api.typesafe.ai/v1/systemone')
            self.assertEqual(request.headers['authorization'], 'Bearer test-key')
            import json
            payload = json.loads(request.content)
            self.assertEqual(payload['model'], 'test-model')
            self.assertEqual(payload['state']['transcript'], 'hello')
            return httpx.Response(200, json={'answers': {name: {'type': 'score', 'score': 2} for name in jev_ranker.DIMENSIONS}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(jev_ranker.score_candidate(client, {'text': 'hello', 'start': 0, 'end': 20}, 'en'), 50)

    @patch.dict(os.environ, {'JEV_API_KEY': 'secret'}, clear=True)
    def test_failed_or_invalid_response_is_not_accepted(self):
        candidate = {'text': 'hello', 'start': 0, 'end': 20}
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text='secret'))) as client:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as error:
                jev_ranker.score_candidate(client, candidate, 'en')
            self.assertNotIn('secret', str(error.exception))
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'answers': {}}))) as client:
            with self.assertRaises(ValueError):
                jev_ranker.score_candidate(client, candidate, 'en')

    @patch.dict(os.environ, {'HIGHLIGHT_PROVIDER': 'jev', 'JEV_API_KEY': 'key'}, clear=True)
    def test_provider_and_billing_isolation(self):
        self.assertTrue(jev_ranker.configured())
        with patch.dict(os.environ, {'BILLING_ENABLED': 'true'}):
            self.assertFalse(jev_ranker.selected())
        with patch.dict(os.environ, {'HIGHLIGHT_PROVIDER': 'gemini'}):
            self.assertFalse(jev_ranker.selected())

    @patch.dict(os.environ, {'HIGHLIGHT_PROVIDER': 'jev', 'JEV_API_KEY': 'key', 'JEV_MAX_CANDIDATES': '4'}, clear=True)
    def test_select_uses_rankings_and_returns_renderable_shape(self):
        with patch('jev_ranker.score_candidate', side_effect=[10, 80, 50, 20]):
            result = jev_ranker.select(fixture(), 90, 15, 60)
        shorts = result['shorts']
        self.assertTrue(any(x['predicted_score'] == 80 for x in shorts))
        self.assertTrue(all(x['viral_hook_text'] == '' for x in shorts))
        self.assertTrue(all(x['start'] < x['end'] for x in shorts))

if __name__ == '__main__':
    unittest.main()
