import json, os, tempfile, unittest, urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread

from src.merchant_os import webhook

class TestWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        webhook.DB_PATH = os.path.join(cls.tmp.name, 'db.sqlite')
        webhook.VERIFY_TOKEN = 'test-token'
        webhook.APP_SECRET = ''
        webhook.ensure_db()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), webhook.Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path).read().decode()

    def post(self, path, obj):
        req = urllib.request.Request(self.base + path, data=json.dumps(obj).encode(), headers={'Content-Type':'application/json'}, method='POST')
        return urllib.request.urlopen(req).read().decode()

    def test_health(self):
        self.assertIn('"ok": true', self.get('/health'))

    def test_verify(self):
        self.assertEqual(self.get('/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=test-token&hub.challenge=12345'), '12345')

    def test_message_and_idempotency(self):
        payload = {'object':'whatsapp_business_account','entry':[{'changes':[{'value':{'contacts':[{'wa_id':'967700000000','profile':{'name':'Test'}}],'messages':[{'id':'wamid.TEST1','from':'967700000000','type':'text','text':{'body':'مرحبا'}}]}}]}]}
        first = json.loads(self.post('/webhooks/whatsapp', payload))
        second = json.loads(self.post('/webhooks/whatsapp', payload))
        self.assertFalse(first['processed'][0]['duplicate'])
        self.assertTrue(second['processed'][0]['duplicate'])
        self.assertEqual(first['processed'][0]['intent'], 'unknown')
        self.assertEqual(first['processed'][0]['agent'], 'general_router')
        self.assertEqual(first['processed'][0]['conversation_id'], 1)

if __name__ == '__main__': unittest.main()
