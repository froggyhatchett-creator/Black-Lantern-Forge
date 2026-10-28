import sqlite3
import unittest
import test_mercy as legacy


class StorageV2Tests(unittest.TestCase):
    setUp = legacy.MercyTests.setUp


def test_turn_recovery(self):
    turn = self.store.begin_turn(1, 'hello')
    self.store.checkpoint(turn, 'partial survives')
    self.assertEqual(self.store.recover(), [turn])
    self.assertEqual(self.store.history()[-1]['state'], 'interrupted')
    self.assertEqual(self.store.history()[-1]['content'], 'partial survives')
    self.assertEqual(self.store.recover(), [])
    self.assertNotIn('hello', str(self.core.context.build('next')))


def test_conversation_isolation(self):
    other = self.store.new_conversation('Second')
    self.core.chat('unique first')
    self.core.chat('unique second', conversation_id=other)
    self.assertNotIn('unique first', str(self.core.context.build('next', other)))


def test_finish_atomic_and_terminal(self):
    turn = self.store.begin_turn(1, 'test')
    self.store.finish_turn(turn, 'done')
    with self.assertRaises(ValueError): self.store.checkpoint(turn, 'late')
    self.assertEqual(self.store.turns()[0]['state'], 'complete')
    self.assertEqual(self.store.history()[-1]['content'], 'done')


def test_memory_provenance_delete(self):
    turn = self.store.begin_turn(1, 'remember')
    self.store.finish_turn(turn, 'done')
    ident = self.store.remember('violet fire', 'conversation', turn)
    self.assertEqual(self.store.memories()[0]['source_ref'], turn)
    self.store.forget(ident)
    self.assertNotIn('violet fire', str(self.store.audits()))
    self.assertFalse(self.store.retrieve('violet'))


def test_migration_v1(self):
    path = self.path.with_name('legacy.db')
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,state TEXT,created TEXT); CREATE TABLE memories(id INTEGER PRIMARY KEY,content TEXT,created TEXT); CREATE TABLE audit(id INTEGER PRIMARY KEY,created TEXT,data TEXT); INSERT INTO messages VALUES(1,'user','old','complete','then'); INSERT INTO memories VALUES(1,'legacy note','then'); PRAGMA user_version=1;")
    db.close()
    from mercy.storage import Store
    migrated = Store(path)
    self.assertEqual(migrated.history()[0]['content'], 'old')
    self.assertEqual(migrated.memories()[0]['source_kind'], 'legacy')
    self.assertEqual(len(list(path.parent.glob('legacy.db.pre-v2-*.bak'))), 1)
    Store(path)
    self.assertEqual(len(list(path.parent.glob('legacy.db.pre-v2-*.bak'))), 1)


def test_unknown_schema_rejected(self):
    with self.store.connect() as db: db.execute('PRAGMA user_version=99')
    from mercy.storage import Store
    with self.assertRaises(ValueError): Store(self.path)


for _fn in (test_turn_recovery, test_conversation_isolation, test_finish_atomic_and_terminal,
            test_memory_provenance_delete, test_migration_v1, test_unknown_schema_rejected):
    setattr(StorageV2Tests, _fn.__name__, _fn)
