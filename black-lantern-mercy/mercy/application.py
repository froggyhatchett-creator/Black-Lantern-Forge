"""UI-independent application service. No Tk imports or model-granted permission."""
import queue
import threading
import uuid
from dataclasses import dataclass, field
from .profile import Profile
from .context import ContextBuilder, load_identity, window_budget, DEFAULT_BUDGET
from .capabilities import Broker, register_defaults
from .core import MercyCore
from .platform import HostPlatform
from .runtime import Control, ManagedProvider


@dataclass
class PermissionRequest:
    capability: str
    purpose: str
    permission: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    decision: bool = False
    resolved: threading.Event = field(default_factory=threading.Event)


class ApplicationService:
    def __init__(self, path, platform=None):
        self.profile = Profile(path)
        self.store = self.profile.store
        self.events = queue.Queue()
        self.platform = platform or HostPlatform()
        self._lock = threading.Lock()
        self.busy = False
        self.closed = False
        self.control = None
        self.thread = None
        self.pending = None
        self.broker = Broker(self.store, self._authorize)
        register_defaults(self.broker, self.platform)

    @property
    def config(self):
        return dict(self.profile.config)

    def configure(self, config):
        with self._lock:
            if self.busy or self.closed:
                raise RuntimeError('Wait for the current operation to finish.')
            identity = load_identity(self.profile.path / 'identity.json')
            if len(identity['instructions']) + len(str(identity.get('vocabulary', {}))) > 8000:
                raise ValueError('Identity exceeds context budget.')
            self.profile.save_config(config)
            self.profile.identity = identity

    def select_conversation(self, ident):
        self.configure({**self.config, 'conversation_id': ident})

    def new_conversation(self, title):
        with self._lock:
            if self.busy or self.closed:
                raise RuntimeError('Wait for the current operation to finish.')
            ident = self.store.new_conversation(title)
            self.profile.save_config({**self.config, 'conversation_id': ident})
            return ident

    def context_budget(self, settings):
        if settings['provider'] != 'ollama':
            return DEFAULT_BUDGET
        return window_budget(settings['num_ctx'], self.broker.schemas())

    def _start(self, operation, timeout):
        with self._lock:
            if self.busy or self.closed:
                raise RuntimeError('An operation is already active or the profile is closed.')
            self.busy = True
            self.control = Control(timeout)
            def run():
                try:
                    operation(self.control)
                except Exception as exc:
                    self.events.put(('error', str(exc)))
                finally:
                    with self._lock:
                        self.pending = None
                        self.busy = False
                    self.events.put(('done', None))
            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()

    def check_status(self):
        settings = self.config
        self._start(lambda control: self.events.put(('status', ManagedProvider(settings, control).status())), settings['status_timeout'])

    def send(self, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise ValueError('Enter 1–4000 characters.')
        settings = self.config
        def operation(control):
            provider = ManagedProvider(settings, control)
            context = ContextBuilder(self.store, self.profile.identity, budget=self.context_budget(settings))
            self.broker.check_control = control.check
            core = MercyCore(self.store, context, provider, self.broker)
            core.chat(text, lambda part: self.events.put(('text', part)), settings['conversation_id'], control)
            self.events.put(('status', {'detail': 'Ready', 'models': [provider.model]}))
        self._start(operation, settings['generation_timeout'])

    def _authorize(self, capability, arguments):
        self.control.check()
        request = PermissionRequest(capability.name, capability.purpose, capability.permission)
        with self._lock:
            self.pending = request
        self.events.put(('permission', request))
        try:
            while not request.resolved.wait(0.04):
                self.control.check()
            self.control.check()
            return request.decision is True
        finally:
            with self._lock:
                self.pending = None

    def respond(self, request_id, allow):
        with self._lock:
            request = self.pending
            if not request or request.id != request_id or request.resolved.is_set():
                return False
            self.control.check()
            request.decision = allow is True
            request.resolved.set()
            return True

    def cancel(self):
        with self._lock:
            if self.control:
                self.control.cancel()

    def close(self, timeout=2):
        self.cancel()
        if self.thread:
            self.thread.join(timeout)
        if self.busy:
            return False
        self.closed = True
        self.profile.close()
        return True
