import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
import test_mercy as legacy
from mercy.runtime import ManagedProvider, Control, DeadlineExceeded
from mercy.providers import ProviderError, Event
from mercy import config
from mercy.profile import Profile
from mercy.context import load_identity
from mercy.storage import Store
from test_runtime_v2 import stuck_factory


class Crashes:
    def stream(self, messages, tools):
        os._exit(9)
        yield Event()


def crash_factory(settings):
    return Crashes()


class FailureTests(unittest.TestCase):
    setUp = legacy.MercyTests.setUp

    def test_unexpected_provider_exit(self):
        provider = ManagedProvider(config.DEFAULT, Control(5), crash_factory)
        with self.assertRaises(ProviderError): list(provider.stream([], []))
        self.assertIsNotNone(provider.last_returncode)

    def test_status_deadline(self):
        provider = ManagedProvider(config.DEFAULT, Control(0.5), stuck_factory)
        with self.assertRaises(DeadlineExceeded): provider.status()
        self.assertIsNotNone(provider.last_returncode)

    @unittest.skipUnless(os.name == 'nt', 'Windows process handle verification')
    def test_worker_exits_when_parent_crashes(self):
        import ctypes
        script = "import os; from mercy.runtime import ManagedProvider,Control; from mercy.config import DEFAULT; from test_runtime_v2 import stuck_factory; p=ManagedProvider(DEFAULT,Control(20),stuck_factory); i=p.stream([],[]); next(i); print(p.last_pid,flush=True); os._exit(7)"
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join(sys.path)
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        pid = int(result.stdout.strip())
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
            finally:
                kernel.CloseHandle(handle)

    def test_timeout_preserves_partial_turn(self):
        control = Control(1)
        self.core.provider = ManagedProvider(config.DEFAULT, control, stuck_factory)
        with self.assertRaises(DeadlineExceeded): self.core.chat('time out', control=control)
        self.assertEqual(self.store.turns()[-1]['state'], 'timed_out')
        self.assertEqual(self.store.history()[-1]['content'], 'checkpoint')

    def test_profile_lock_cross_process(self):
        folder = Path(self.temp.name)/'locked'
        profile = Profile(folder)
        try:
            script = 'import sys; from mercy.profile import Profile; Profile(sys.argv[1])'
            result = subprocess.run([sys.executable, '-c', script, str(folder)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already open', result.stderr)
        finally:
            profile.close()

    def test_session_selection_persists(self):
        folder = Path(self.temp.name)/'session'
        profile = Profile(folder)
        ident = profile.store.new_conversation('Retained title')
        profile.save_config({**profile.config, 'conversation_id': ident})
        profile.close()
        reopened = Profile(folder)
        try:
            self.assertEqual(reopened.config['conversation_id'], ident)
            self.assertEqual(reopened.store.conversations()[0]['title'], 'Retained title')
        finally:
            reopened.close()

    def test_memory_deletion_rolls_back_with_failed_audit(self):
        from unittest.mock import patch
        ident = self.store.remember('preserve until deletion succeeds')
        with patch.object(self.store, '_audit', side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.store.forget(ident)
        self.assertEqual(len(self.store.memories()), 1)

    def test_invalid_memory_reference(self):
        with self.assertRaises(ValueError): self.store.remember('note', 'conversation', 'nonexistent')
        self.assertFalse(self.store.memories())

    def test_identity_field_validation(self):
        for change in ({'name':[]}, {'instructions':''}, {'version':True}, {'vocabulary':{'a':[]}}):
            path = Path(self.temp.name)/'identity.json'
            path.write_text(json.dumps({**self.identity, **change}), encoding='utf-8')
            with self.assertRaises(ValueError): load_identity(path)

    def test_unversioned_database_rejected(self):
        path = Path(self.temp.name)/'unknown.db'
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE important(value TEXT)')
        db.close()
        with self.assertRaises(ValueError): Store(path)

    def test_audit_paging_and_turn_filter(self):
        for ident in ('a', 'b'):
            self.store.audit({'turn_id': ident, 'event':'test'})
        self.assertEqual(len(self.store.audits(turn_id='a')), 1)
        self.assertNotEqual(self.store.audits(limit=1)[0]['id'], self.store.audits(limit=1, offset=1)[0]['id'])
