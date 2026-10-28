import json
import tempfile
import shutil
import uuid
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mercy.storage import Store
from mercy.context import load_identity, ContextBuilder
from mercy.providers import MockProvider, OllamaProvider, ProviderError, Event
from mercy.capabilities import Broker, Capability, register_defaults
from mercy.platform import HostPlatform
from mercy.core import MercyCore


class MercyTests(unittest.TestCase):
    def setUp(self):
        # Default mkdir permissions also work in restricted Windows test hosts.
        class TestDirectory:
            name = str(Path(tempfile.gettempdir()) / ('mercy-test-' + uuid.uuid4().hex))
        self.temp = TestDirectory()
        Path(self.temp.name).mkdir()
        self.addCleanup(shutil.rmtree, self.temp.name)
        self.path = Path(self.temp.name) / 'memory.sqlite3'
        self.store = Store(self.path)
        self.identity = load_identity(Path(__file__).parents[1] / 'mercy/identity.json')
        self.broker = Broker(self.store, lambda c, a: True)
        register_defaults(self.broker, HostPlatform())
        self.core = MercyCore(self.store, ContextBuilder(self.store, self.identity), MockProvider(), self.broker)

    def call(self, name='current_time', arguments=None):
        return {'function': {'name': name, 'arguments': {} if arguments is None else arguments}}

    def test_identity(self):
        self.assertEqual(self.identity['name'], 'Mercy')
        self.assertIn('battery', self.identity['vocabulary'])

    def test_invalid_identity(self):
        p = Path(self.temp.name) / 'bad.json'
        p.write_text('{}')
        with self.assertRaises(ValueError): load_identity(p)

    def test_memory_restart(self):
        self.store.remember('My favorite project is a cryptsy compiler.')
        self.assertEqual(Store(self.path).memories()[0]['content'], self.store.memories()[0]['content'])

    def test_conversation_restart(self):
        answer = self.core.chat('Mercy?')
        self.assertEqual(Store(self.path).history()[-1]['content'], answer)

    def test_context_selects(self):
        self.store.remember('Compiler project uses LLVM')
        self.store.remember('Tea is pleasant')
        self.store.message('user', 'compiler')
        context = self.core.context.build('compiler')
        self.assertIn('LLVM', str(context))
        self.assertNotIn('Tea is pleasant', str(context))

    def test_context_bounded(self):
        for _ in range(100): self.store.message('user', 'x' * 1000)
        context = self.core.context.build('x')
        self.assertLessEqual(sum(len(m['content']) for m in context), 16000)

    def test_retriever_substitution(self):
        context = ContextBuilder(self.store, self.identity, lambda q: [{'content': 'semantic seam'}])
        self.assertIn('semantic seam', str(context.build('anything')))

    def test_provider_substitution(self):
        class Other:
            def stream(self, messages, tools): yield Event(text='Another engine, same Mercy')
        self.core.provider = Other()
        self.assertEqual(self.core.chat('Hello'), 'Another engine, same Mercy')
        self.assertEqual(self.identity['name'], 'Mercy')

    def test_streaming_mock(self):
        parts = []
        answer = self.core.chat('Mercy?', parts.append)
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(parts), answer)

    def test_registration(self):
        self.assertEqual(len(self.broker.schemas()), 3)
        with self.assertRaises(ValueError): register_defaults(self.broker, HostPlatform())

    def test_validation(self):
        for args in ({'command': 'anything'}, 'oops', [], 7):
            self.assertIn('error', self.broker.execute(self.call(arguments=args)))

    def test_approval(self):
        self.assertIn('time', self.broker.execute(self.call()))
        self.assertIn('approved', self.store.audits()[0]['data'])

    def test_denial_no_execution(self):
        executed = []
        self.broker.register(Capability('spy', 'Test', 'test', lambda: executed.append(True)))
        self.broker.authorize = lambda c, a: False
        self.assertEqual(self.broker.execute(self.call('spy'))['error'], 'Permission denied')
        self.assertEqual(executed, [])
        self.assertIn('denied', self.store.audits()[0]['data'])

    def test_truthy_is_not_approval(self):
        self.broker.authorize = lambda c, a: 'yes'
        self.assertIn('error', self.broker.execute(self.call()))

    def test_audit(self):
        self.broker.execute(self.call())
        rows = self.store.audits()
        self.assertEqual(len(rows), 3)
        record = json.loads(rows[0]['data'])
        self.assertEqual(record['execution'], 'succeeded')
        self.assertEqual(record['arguments'], {})
        self.assertIn('created', rows[0])

    def test_malformed_requests(self):
        for req in (None, [], 'shell', {}, {'function': None}, self.call('shell'), {'function': {'name': []}}):
            self.assertIn('error', self.broker.execute(req))

    def test_tool_loop(self):
        answer = self.core.chat('/time')
        self.assertIn('time', answer)
        self.assertTrue(self.store.audits())

    def test_denial_inference_continues(self):
        self.broker.authorize = lambda c, a: False
        self.assertIn('Permission denied', self.core.chat('/time'))

    def test_partial_failure(self):
        class Broken:
            def stream(self, messages, tools):
                yield Event(text='partial')
                raise ProviderError('offline')
        self.core.provider = Broken()
        with self.assertRaises(ProviderError): self.core.chat('Hello')
        self.assertEqual(self.store.history()[-1]['state'], 'failed')
        self.assertNotIn('partial', str(self.core.context.build('Hello')))

    def test_empty_response(self):
        class Empty:
            def stream(self, messages, tools): return iter([])
        self.core.provider = Empty()
        with self.assertRaises(ProviderError): self.core.chat('Hello')

    def test_loop_limit(self):
        call = self.call()
        class Loop:
            def stream(self, messages, tools): yield Event(tool=call)
        self.core.provider = Loop()
        with self.assertRaises(ProviderError): self.core.chat('Loop')
        self.assertEqual(len(self.store.audits()), 10)  # Includes the v0.2 rejected-round record.

    def test_credential_rejection(self):
        with self.assertRaises(ValueError): self.store.remember('password=bad')
        self.assertFalse(self.store.memories())

    def test_rejected_args_redacted(self):
        self.broker.execute(self.call(arguments={'password': 'sensitive-value'}))
        self.assertNotIn('sensitive-value', str(self.store.audits()))

    def test_delete_memory(self):
        self.store.remember('hello')
        self.store.forget(self.store.memories()[0]['id'])
        self.assertFalse(Store(self.path).memories())

    def test_endpoint_guard(self):
        for endpoint in ('https://example.com', 'http://example.com', 'http://user:pass@localhost', 'http://localhost/a'):
            with self.assertRaises(ValueError): OllamaProvider('m', endpoint)

    def test_failed_audit_prevents_execution(self):
        called = []
        self.broker.registry['current_time'].implementation = lambda: called.append(True)
        def fail(data): raise OSError('disk full')
        self.store.audit = fail
        with self.assertRaises(OSError): self.broker.execute(self.call())
        self.assertEqual(called, [])

    def test_input_limits(self):
        for text in ('', 'x' * 4001):
            with self.assertRaises(ValueError): self.core.chat(text)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'ok'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"models":[{"name":"test:latest"}]}')
            def do_POST(self):
                owner.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200); self.end_headers()
                if owner.mode == 'bad': self.wfile.write(b'not-json\n'); return
                self.wfile.write(b'{"message":{"content":"Hello"},"done":false}\n')
                if owner.mode != 'truncated':
                    self.wfile.write(b'{"message":{"content":" Mercy"},"done":true}\n')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.provider = OllamaProvider('test:latest', f'http://127.0.0.1:{self.server.server_port}')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def test_status(self):
        self.assertTrue(self.provider.status()['available'])

    def test_missing_model(self):
        self.provider.model = 'absent'
        self.assertFalse(self.provider.status()['available'])

    def test_http_stream(self):
        self.assertEqual(''.join(e.text for e in self.provider.stream([], [])), 'Hello Mercy')
        self.assertTrue(self.payload['stream'])
        self.assertEqual(self.payload['model'], 'test:latest')

    def test_truncated(self):
        self.mode = 'truncated'
        with self.assertRaises(ProviderError): list(self.provider.stream([], []))

    def test_malformed(self):
        self.mode = 'bad'
        with self.assertRaises(ProviderError): list(self.provider.stream([], []))


if __name__ == '__main__': unittest.main()
