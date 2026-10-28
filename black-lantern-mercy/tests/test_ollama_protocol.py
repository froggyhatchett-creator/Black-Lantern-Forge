"""Ollama wire-protocol behavior against a LOCAL FAKE server.

This simulates the documented /api/chat NDJSON protocol. It is NOT evidence that
a real Ollama install or model works; real-model verification is separate.
"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from mercy import config
from mercy.core import MercyCore
from mercy.providers import OllamaProvider, Event, ProviderError, MockProvider
from mercy.storage import Store
from mercy.context import ContextBuilder, load_identity
from mercy.capabilities import Broker


class Fake:
    """Scriptable server. `reject_think` simulates a model without thinking support."""
    def __init__(self, lines, reject_think=False):
        self.lines, self.reject_think, self.requests = lines, reject_think, []
        fake = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fake.requests.append(body)
                if fake.reject_think and 'think' in body:
                    data = json.dumps({'error': '"fake" does not support thinking'}).encode()
                    self.send_response(400); self.send_header('Content-Length', str(len(data))); self.end_headers()
                    self.wfile.write(data); return
                self.send_response(200); self.end_headers()
                for line in fake.lines:
                    self.wfile.write((json.dumps(line) + '\n').encode()); self.wfile.flush()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = 'http://127.0.0.1:%d' % self.server.server_address[1]

    def close(self):
        self.server.shutdown(); self.server.server_close()


def chunks(*parts, thinking=()):
    out = [{'message': {'role': 'assistant', 'content': '', 'thinking': t}} for t in thinking]
    out += [{'message': {'role': 'assistant', 'content': p}} for p in parts]
    return out + [{'message': {'role': 'assistant', 'content': ''}, 'done': True}]


class OllamaProtocolTests(unittest.TestCase):
    def serve(self, *a, **k):
        fake = Fake(*a, **k)
        self.addCleanup(fake.close)
        return fake

    def stream(self, fake, **kw):
        provider = OllamaProvider('fake', fake.endpoint, **kw)
        return [e.text for e in provider.stream([{'role': 'user', 'content': 'hi'}], [])]

    def test_thinking_disabled_by_default(self):
        fake = self.serve(chunks('Hi', ' there'))
        self.assertEqual(self.stream(fake), ['Hi', ' there'])
        self.assertIs(fake.requests[0]['think'], False)

    def test_think_can_be_enabled(self):
        fake = self.serve(chunks('x'))
        self.stream(fake, think=True)
        self.assertIs(fake.requests[0]['think'], True)

    def test_thinking_tokens_never_become_visible_text(self):
        fake = self.serve(chunks('answer', thinking=['secret reasoning']))
        self.assertEqual(self.stream(fake, think=True), ['answer'])

    def test_num_ctx_sent_only_when_configured(self):
        fake = self.serve(chunks('x'))
        self.stream(fake)
        self.assertNotIn('options', fake.requests[0])
        self.stream(fake, num_ctx=8192)
        self.assertEqual(fake.requests[1]['options'], {'num_ctx': 8192})

    def test_model_without_thinking_support_falls_back_once(self):
        fake = self.serve(chunks('ok'), reject_think=True)
        self.assertEqual(self.stream(fake), ['ok'])
        self.assertEqual(['think' in r for r in fake.requests], [True, False])

    def test_unreachable_backend_fails_cleanly(self):
        fake = self.serve(chunks('ok'))
        fake.close()
        with self.assertRaises(ProviderError):
            self.stream(fake)

    def test_truncated_stream_still_fails(self):
        fake = self.serve([{'message': {'content': 'partial'}}])
        with self.assertRaises(ProviderError):
            self.stream(fake)


class ConfigThinkTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertIs(config.validate({})['think'], False)
        self.assertIs(config.validate({'think': True})['think'], True)
        with self.assertRaises(ValueError):
            config.validate({'think': 'yes'})

    def test_v02_config_without_field_loads(self):
        legacy = {'version': 2, 'provider': 'mock'}
        self.assertIs(config.validate(legacy)['think'], False)
        self.assertEqual(config.validate(legacy)['num_ctx'], 0)

    def test_num_ctx_validation(self):
        self.assertEqual(config.validate({'num_ctx': 8192})['num_ctx'], 8192)
        for bad in (-1, 100, 10**7, 8192.0, '8192', True):
            with self.assertRaises(ValueError):
                config.validate({'num_ctx': bad})


class CheckpointThrottleTests(unittest.TestCase):
    def test_burst_is_throttled_but_final_text_is_complete(self):
        class Burst(MockProvider):
            model = 'burst'
            def stream(self, messages, tools):
                for i in range(300):
                    yield Event(text='w%d ' % i)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / 'm.sqlite3')
        calls = []
        real = store.checkpoint
        store.checkpoint = lambda t, text: (calls.append(len(text)), real(t, text))[1]
        identity = load_identity(Path(__file__).parents[1] / 'mercy/identity.json')
        core = MercyCore(store, ContextBuilder(store, identity), Burst(), Broker(store, lambda c, a: True))
        answer = core.chat('go')
        self.assertLess(len(calls), 30)
        self.assertGreaterEqual(len(calls), 1)  # first token is persisted immediately
        self.assertEqual(store.history()[-1]['content'], answer)
        self.assertTrue(answer.endswith('w299 '))


if __name__ == '__main__':
    unittest.main()
