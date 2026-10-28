import json
import queue
import sqlite3
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_mercy as legacy
from mercy.application import ApplicationService
from mercy.profile import Profile
from mercy.storage import Store
from mercy.runtime import DeadlineExceeded


class ApplicationTests(unittest.TestCase):
    setUp = legacy.MercyTests.setUp

    def service(self):
        service = ApplicationService(Path(self.temp.name)/'profile')
        self.addCleanup(service.close)
        return service

    def wait(self, app, permission=None):
        records = []
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                kind, value = app.events.get(timeout=0.05)
                records.append((kind, value))
                if kind == 'permission' and permission is not None:
                    app.respond(value.id, permission)
                if kind == 'done':
                    return records
            except queue.Empty:
                pass
        self.fail('Application operation did not settle')

    def test_controller_mock_conversation_and_sessions(self):
        app = self.service()
        app.send('Mercy?')
        events = self.wait(app)
        self.assertIn('text', [k for k,v in events])
        app.new_conversation('New')
        self.assertEqual(app.store.history(conversation_id=app.config['conversation_id']), [])
        app.send('Hello')
        self.wait(app)
        self.assertEqual(len(app.store.history()), 2)

    def test_controller_permission_one_use(self):
        app = self.service()
        for decision in (False, True, False):
            app.send('/time')
            self.wait(app, decision)
        records = [json.loads(r['data']) for r in app.store.audits()]
        self.assertEqual(sum(r.get('execution') == 'succeeded' for r in records), 1)
        self.assertEqual(sum(r.get('authorization') == 'denied' for r in records), 2)
        self.assertTrue(all(r.get('turn_id') for r in records))

    def test_permission_deadline_and_stale_approval(self):
        app = self.service()
        app.configure({**app.config, 'generation_timeout': 1})
        app.send('/time')
        events = self.wait(app)
        requests = [v for k,v in events if k == 'permission']
        self.assertTrue(requests)
        self.assertEqual(app.store.turns()[-1]['state'], 'timed_out')
        self.assertFalse(app.respond(requests[0].id, True))
        self.assertFalse(any('succeeded' in r['data'] for r in app.store.audits()))

    def test_cancel_pending_permission(self):
        app = self.service()
        app.send('/time')
        deadline = time.monotonic() + 8
        while app.pending is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIsNotNone(app.pending)
        app.cancel()
        self.wait(app)
        self.assertEqual(app.store.turns()[-1]['state'], 'cancelled')

    def test_config_while_busy_rejected(self):
        app = self.service()
        app.send('/time')
        with self.assertRaises(RuntimeError): app.configure(app.config)
        with self.assertRaises(RuntimeError): app.new_conversation('No')
        app.cancel()
        self.wait(app)

    def test_config_replace_failure_preserves_file(self):
        app = self.service()
        app.configure(app.config)
        path = app.profile.path/'config.json'
        before = path.read_bytes()
        with patch('mercy.config.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError): app.configure({**app.config, 'generation_timeout': 42})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(app.config['generation_timeout'], 60)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_actual_crash_and_profile_recovery(self):
        folder = Path(self.temp.name)/'crash'
        script = "import sys,os; from mercy.profile import Profile; p=Profile(sys.argv[1]); t=p.store.begin_turn(1,'crash user'); p.store.checkpoint(t,'saved partial'); os._exit(7)"
        result = subprocess.run([sys.executable, '-c', script, str(folder)], timeout=10)
        self.assertEqual(result.returncode, 7)
        profile = Profile(folder)
        try:
            self.assertEqual(len(profile.recovered), 1)
            self.assertEqual(profile.store.history()[-1]['content'], 'saved partial')
            self.assertEqual(profile.store.history()[-1]['state'], 'interrupted')
        finally:
            profile.close()

    def test_migration_rollback(self):
        path = Path(self.temp.name)/'broken.db'
        db = sqlite3.connect(path)
        db.executescript('CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,state TEXT,created TEXT); PRAGMA user_version=1;')
        db.close()
        with self.assertRaises(sqlite3.OperationalError): Store(path)
        db = sqlite3.connect(path)
        try:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertEqual(tables, ['messages'])
            self.assertNotIn('turn_id', [r[1] for r in db.execute('PRAGMA table_info(messages)')])
        finally:
            db.close()

    def test_begin_turn_rolls_back_on_bad_session(self):
        with self.assertRaises(sqlite3.IntegrityError): self.store.begin_turn(999, 'bad')
        self.assertEqual(self.store.history(), [])
        self.assertEqual(self.store.turns(), [])

    def test_memory_transaction_rolls_back_on_audit_failure(self):
        with patch.object(self.store, '_audit', side_effect=OSError('disk error')):
            with self.assertRaises(OSError): self.store.remember('not committed')
        self.assertFalse(self.store.memories())
