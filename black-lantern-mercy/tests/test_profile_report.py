import hashlib
import importlib.util
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from mercy.capabilities import Broker, register_defaults
from mercy.context import ContextBuilder, load_identity
from mercy.core import MercyCore
from mercy.platform import HostPlatform
from mercy.providers import Event
from mercy.runtime import Control
from mercy.storage import Store

spec = importlib.util.spec_from_file_location('profile_report', Path(__file__).parents[1] / 'tools/profile_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class Scripted:
    model = 'scripted'
    def __init__(self, call):
        self.call = call
    def stream(self, messages, tools):
        yield Event(text='ok') if messages[-1]['role'] == 'tool' else Event(tool=self.call)


class ProfileReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir / 'mercy.sqlite3')
        (self.dir / 'config.json').write_text('{"version": 2}')

    def run_turn(self, call, authorize, timeout=5):
        control = Control(timeout)
        broker = Broker(self.store, lambda c, a: authorize(control)); broker.check_control = control.check
        register_defaults(broker, HostPlatform())
        identity = load_identity(Path(__file__).parents[1] / 'mercy/identity.json')
        try:
            MercyCore(self.store, ContextBuilder(self.store, identity), Scripted(call), broker).chat('time?', control=control)
        except Exception:
            pass

    def diagnose(self):
        out = io.StringIO()
        with redirect_stdout(out), patch('sys.argv', ['x', '--profile', str(self.dir), '--diagnose']):
            self.assertEqual(report.main(), 0)
        return out.getvalue()

    def test_deadline_during_permission_wait(self):
        def wait(control):
            while True:
                time.sleep(0.02); control.check()
        self.run_turn({'function': {'name': 'current_time', 'arguments': {}}}, wait, timeout=1)
        self.assertIn('DEADLINE reached', self.diagnose())

    def test_validation_rejection_before_any_prompt(self):
        self.run_turn({'function': {'index': 0, 'name': 'current_time', 'arguments': {}}}, lambda c: True)
        self.assertIn('REJECTED by Mercy', self.diagnose())

    def test_denied_permission_is_complete_not_listed_as_error(self):
        self.run_turn({'function': {'name': 'current_time', 'arguments': {}}}, lambda c: False)
        self.assertIn('none', self.diagnose())

    def test_report_is_read_only(self):
        self.store.remember('keep me')
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.dir.iterdir()}
        self.diagnose()
        self.assertEqual(files, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.dir.iterdir()})


if __name__ == '__main__':
    unittest.main()
