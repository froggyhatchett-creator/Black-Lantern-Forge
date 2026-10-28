"""Bound provider calls without changing the inference contract or granting tools.

Children receive messages/schema only. Capability execution stays in the parent.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from .providers import MockProvider, OllamaProvider, ProviderError, Event


class Cancelled(ProviderError):
    turn_state = 'cancelled'


class DeadlineExceeded(ProviderError):
    turn_state = 'timed_out'


class Control:
    def __init__(self, timeout):
        self.cancelled = threading.Event()
        self.deadline = time.monotonic() + timeout

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled('Generation cancelled.')
        if time.monotonic() >= self.deadline:
            raise DeadlineExceeded('Operation exceeded its configured deadline.')


def mock_factory(settings):
    return MockProvider()


def ollama_factory(settings):
    return OllamaProvider(settings['model'], settings['endpoint'],
                          settings.get('think', False), settings.get('num_ctx', 0))


REGISTRY = {'mock': mock_factory, 'ollama': ollama_factory}


class ManagedProvider:
    def __init__(self, settings, control, factory=None):
        self.settings, self.control = dict(settings), control
        self.factory = factory or REGISTRY[settings['provider']]
        self.model = settings['model'] or 'offline-demo'
        self.last_pid = None
        self.last_returncode = None

    def _run(self, operation, messages=None, tools=None):
        self.control.check()
        if '<locals>' in self.factory.__qualname__:
            raise ValueError('Provider factories must be top-level trusted functions.')
        payload = {'module': self.factory.__module__, 'factory': self.factory.__name__,
                   'settings': self.settings, 'operation': operation, 'messages': messages, 'tools': tools}
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if isinstance(p, str))
        process = subprocess.Popen([sys.executable, '-m', 'mercy.worker'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.last_pid = process.pid
        events, stop = queue.Queue(maxsize=32), threading.Event()
        def put(item):
            while not stop.is_set():
                try:
                    events.put(item, timeout=0.04)
                    return
                except queue.Full:
                    pass
        def read():
            try:
                process.stdin.write(json.dumps(payload) + '\n')
                process.stdin.flush()  # Kept open as the worker's parent-liveness channel.
                while not stop.is_set():
                    line = process.stdout.readline(1_000_001)
                    if not line:
                        put(('error', 'Provider process exited before completion.'))
                        return
                    if len(line) > 1_000_000:
                        put(('error', 'Provider event exceeds size limit.'))
                        return
                    put(json.loads(line))
            except (OSError, ValueError) as exc:
                put(('error', 'Provider transport failed: ' + type(exc).__name__))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while True:
                self.control.check()
                try:
                    kind, value = events.get(timeout=0.04)
                except queue.Empty:
                    continue
                self.control.check()
                if kind == 'done':
                    return
                if kind == 'error':
                    raise ProviderError(value)
                if kind == 'event':
                    if not isinstance(value, dict) or not isinstance(value.get('text'), str):
                        raise ProviderError('Invalid provider event.')
                    yield Event(text=value['text'], tool=value.get('tool'))
                elif kind == 'value':
                    yield value
                else:
                    raise ProviderError('Unknown provider event.')
        finally:
            stop.set()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
            reader.join(0.5)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
            self.last_returncode = process.returncode

    def stream(self, messages, tools):
        yield from self._run('stream', messages, tools)

    def status(self):
        values = list(self._run('status'))
        if not values or not isinstance(values[0], dict):
            raise ProviderError('Invalid provider status.')
        return values[0]
