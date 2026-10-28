import multiprocessing
import time
import threading
import unittest
from pathlib import Path
import test_mercy as legacy
from mercy.runtime import ManagedProvider, Control, Cancelled, DeadlineExceeded
from mercy.providers import Event
from mercy.profile import Profile
from mercy import config


class Stuck:
    def stream(self, messages, tools):
        yield Event(text='checkpoint')
        time.sleep(30)
    def status(self):
        time.sleep(30)


def stuck_factory(settings):
    return Stuck()


class RuntimeTests(unittest.TestCase):
    setUp = legacy.MercyTests.setUp

    def test_deadline_kills_worker(self):
        provider = ManagedProvider(config.DEFAULT, Control(0.8), stuck_factory)
        start = time.monotonic()
        with self.assertRaises(DeadlineExceeded): list(provider.stream([], []))
        self.assertLess(time.monotonic() - start, 3)
        self.assertIsNotNone(provider.last_returncode)

    def test_cancellation_kills_worker(self):
        control = Control(20)
        provider = ManagedProvider(config.DEFAULT, control, stuck_factory)
        timer = threading.Timer(0.6, control.cancel)
        timer.start()
        with self.assertRaises(Cancelled): list(provider.stream([], []))
        timer.join()
        self.assertIsNotNone(provider.last_returncode)

    def test_managed_mock_contract(self):
        provider = ManagedProvider(config.DEFAULT, Control(10))
        self.assertTrue(provider.status()['available'])
        self.assertIn('Lantern', ''.join(e.text for e in provider.stream([{'role':'user','content':'Mercy?'}], [])))

    def test_profile_lock_and_release(self):
        folder = Path(self.temp.name)/'profile'
        one = Profile(folder)
        try:
            with self.assertRaises(RuntimeError): Profile(folder)
        finally:
            one.close()
        two = Profile(folder)
        two.close()

    def test_config_rejects_invalid(self):
        for change in ({'provider':'cloud'}, {'generation_timeout':float('nan')}, {'generation_timeout':True},
                       {'endpoint':'http://localhost:bad'}, {'secret':'abc'}, {'provider':'ollama'}, {'conversation_id':False}):
            with self.assertRaises(ValueError): config.validate(change)

    def test_bad_config_preserved_and_lock_released(self):
        folder = Path(self.temp.name)/'profile'
        folder.mkdir()
        (folder/'config.json').write_text('{bad')
        with self.assertRaises(ValueError): Profile(folder)
        self.assertEqual((folder/'config.json').read_text(), '{bad')
        (folder/'config.json').write_text('{}')
        profile = Profile(folder)
        profile.close()

    def test_legacy_config(self):
        value = config.validate({'provider':'mock','model':'','endpoint':'http://127.0.0.1:11434'})
        self.assertEqual(value['version'], 2)

    def test_transaction_cancel_state(self):
        control = Control(20)
        self.core.provider = ManagedProvider(config.DEFAULT, control, stuck_factory)
        def emit(part): control.cancel()
        with self.assertRaises(Cancelled): self.core.chat('hello', emit, control=control)
        self.assertEqual(self.store.turns()[0]['state'], 'cancelled')
        self.assertEqual(self.store.history()[-1]['content'], 'checkpoint')
