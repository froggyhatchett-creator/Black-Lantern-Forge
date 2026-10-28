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

    def test_num_ctx_always_sent_default_8192(self):
        fake = self.serve(chunks('x'))
        self.stream(fake)
        self.assertEqual(fake.requests[0]['options']['num_ctx'], 8192)
        self.stream(fake, num_ctx=16384)
        self.assertEqual(fake.requests[1]['options']['num_ctx'], 16384)

    def test_num_ctx_sent_on_think_fallback_retry(self):
        fake = self.serve(chunks('ok'), reject_think=True)
        self.stream(fake)
        self.assertEqual([r['options']['num_ctx'] for r in fake.requests], [8192, 8192])

    def test_unsupported_num_ctx_rejected_by_provider(self):
        for bad in (0, None, -1, 4095, 131073, 8192.0, '8192', True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                OllamaProvider('fake', 'http://127.0.0.1:1', num_ctx=bad)

    def test_oversized_prompt_refused_before_any_request(self):
        fake = self.serve(chunks('x'))
        provider = OllamaProvider('fake', fake.endpoint, num_ctx=4096)
        with self.assertRaises(ProviderError) as ctx:
            list(provider.stream([{'role': 'system', 'content': 'identity'}, {'role': 'user', 'content': 'x' * 20000}], []))
        self.assertIn('context window', str(ctx.exception))
        self.assertEqual(fake.requests, [])

    def test_prompt_that_filled_the_window_is_reported_not_silent(self):
        lines = chunks('answer')
        lines[-1]['prompt_eval_count'] = 4096  # server evaluated exactly a full window: it clipped the prompt
        fake = self.serve(lines)
        with self.assertRaises(ProviderError) as ctx:
            self.stream(fake, num_ctx=4096)
        self.assertIn('truncat', str(ctx.exception))

    def test_normal_prompt_count_is_accepted(self):
        lines = chunks('answer')
        lines[-1]['prompt_eval_count'] = 600
        fake = self.serve(lines)
        self.assertEqual(self.stream(fake, num_ctx=4096), ['answer'])

    def test_worker_path_passes_num_ctx(self):
        from mercy.runtime import ManagedProvider, Control
        fake = self.serve(chunks('hi'))
        settings = {'provider': 'ollama', 'model': 'fake', 'endpoint': fake.endpoint, 'think': False, 'num_ctx': 12288}
        events = list(ManagedProvider(settings, Control(30)).stream([{'role': 'user', 'content': 'hi'}], []))
        self.assertEqual([e.text for e in events], ['hi'])
        self.assertEqual(fake.requests[0]['options']['num_ctx'], 12288)

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
        self.assertEqual(config.validate(legacy)['num_ctx'], 8192)

    def test_default_is_8192(self):
        self.assertEqual(config.DEFAULT['num_ctx'], 8192)

    def test_num_ctx_validation_bounds(self):
        for good in (4096, 8192, 131072):
            self.assertEqual(config.validate({'num_ctx': good})['num_ctx'], good)
        for bad in (0, -1, 4095, 131073, 262144, 8192.0, '8192', True, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config.validate({'num_ctx': bad})

    def test_previous_build_zero_meaning_unset_migrates_to_default(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'config.json'
        path.write_text(json.dumps({'version': 2, 'provider': 'mock', 'num_ctx': 0}))
        self.assertEqual(config.load(path)['num_ctx'], 8192)


class ContextBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'm.sqlite3')
        self.identity = load_identity(Path(__file__).parents[1] / 'mercy/identity.json')

    def test_budget_never_exceeds_window_and_identity_survives(self):
        from mercy.context import window_budget
        from mercy.providers import estimate_tokens
        broker = Broker(self.store, lambda c, a: True)
        from mercy.capabilities import register_defaults
        from mercy.platform import HostPlatform
        register_defaults(broker, HostPlatform())
        tools = broker.schemas()
        for i in range(60):
            self.store.message('user' if i % 2 == 0 else 'assistant', ('filler %d ' % i) * 60)
        for window in (4096, 8192, 32768):
            messages = ContextBuilder(self.store, self.identity, budget=window_budget(window, tools)).build('hello')
            self.assertEqual(messages[0]['role'], 'system')
            self.assertIn('You are Mercy', messages[0]['content'])
            self.assertLessEqual(estimate_tokens(messages, tools), window - 512, window)

    def test_identity_that_cannot_fit_fails_loudly(self):
        from mercy.context import window_budget
        huge = dict(self.identity, instructions='x' * 12000)
        with self.assertRaises(ValueError):
            ContextBuilder(self.store, huge, budget=window_budget(4096, [])).build('hi')

    def test_service_derives_budget_from_configured_window(self):
        from mercy.application import ApplicationService
        from mercy.context import window_budget
        service = ApplicationService(Path(self.tmp.name) / 'p')
        self.addCleanup(service.close)
        self.assertEqual(service.context_budget({'provider': 'ollama', 'num_ctx': 4096}),
                         window_budget(4096, service.broker.schemas()))
        self.assertEqual(service.context_budget({'provider': 'mock', 'num_ctx': 4096}), 16000)


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
