import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .migrations import migrate


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Persistence only. The profile owner decides when startup recovery is safe."""
    def __init__(self, path):
        self.path = str(path)
        migrate(path)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def conversations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM conversations ORDER BY id DESC')]

    def new_conversation(self, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError('Conversation title must contain 1–120 characters.')
        with self.connect() as db:
            return db.execute('INSERT INTO conversations(title,created) VALUES(?,?)', (title.strip(), now())).lastrowid

    def message(self, role, content, state='complete', conversation_id=1):
        with self.connect() as db:
            db.execute('INSERT INTO messages(role,content,state,created,conversation_id) VALUES(?,?,?,?,?)',
                       (role, content, state, now(), conversation_id))

    def history(self, limit=40, conversation_id=1):
        with self.connect() as db:
            return [dict(r) for r in reversed(db.execute(
                'SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?',
                (conversation_id, limit)).fetchall())]

    def begin_turn(self, conversation_id, text, provider='unknown'):
        turn = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO turns(id,conversation_id,state,started,provider) VALUES(?,?,?,?,?)',
                       (turn, conversation_id, 'running', now(), provider))
            for role, content, state in [('user', text, 'complete'), ('assistant', '', 'streaming')]:
                db.execute('INSERT INTO messages(role,content,state,created,conversation_id,turn_id) VALUES(?,?,?,?,?,?)',
                           (role, content, state, now(), conversation_id, turn))
        return turn

    def checkpoint(self, turn, text):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM turns WHERE id=? AND state='running'", (turn,)).fetchone():
                raise ValueError('Turn is no longer running.')
            db.execute("UPDATE messages SET content=? WHERE turn_id=? AND role='assistant'", (text, turn))

    def finish_turn(self, turn, text, state='complete', error=None):
        if state not in ('complete', 'failed', 'cancelled', 'timed_out', 'interrupted'):
            raise ValueError('Invalid terminal turn state.')
        with self.connect() as db:
            changed = db.execute("UPDATE turns SET state=?,ended=?,error=? WHERE id=? AND state='running'",
                                 (state, now(), error, turn)).rowcount
            if changed != 1:
                raise ValueError('Turn is no longer running.')
            db.execute("UPDATE messages SET content=?,state=? WHERE turn_id=? AND role='assistant'",
                       (text, state, turn))

    def recover(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM turns WHERE state='running'")]
            db.execute("UPDATE messages SET state='interrupted' WHERE role='assistant' AND turn_id IN (SELECT id FROM turns WHERE state='running')")
            db.execute("UPDATE turns SET state='interrupted',ended=?,error='Application stopped before completion' WHERE state='running'", (now(),))
            return ids

    def turns(self, conversation_id=1):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM turns WHERE conversation_id=? ORDER BY started', (conversation_id,))]

    def remember(self, content, source_kind='user', source_ref=None):
        if not isinstance(content, str):
            raise ValueError('Memory must be text.')
        content = content.strip()
        if not content or len(content) > 2000:
            raise ValueError('Memory must contain 1–2000 characters.')
        if source_kind not in ('user', 'conversation', 'import'):
            raise ValueError('Invalid memory source.')
        if source_ref is not None and (not isinstance(source_ref, str) or len(source_ref) > 120):
            raise ValueError('Source reference must be short text.')
        if re.search(r'(?i)(api[_ -]?key|password|secret|token)\s*[:=]|-----BEGIN .*PRIVATE KEY|\bsk-[A-Za-z0-9]{16,}', content):
            raise ValueError('Possible credential detected. Do not store secrets in Mercy.')
        with self.connect() as db:
            if source_kind == 'conversation' and not db.execute('SELECT 1 FROM turns WHERE id=?', (source_ref,)).fetchone():
                raise ValueError('Conversation memory must refer to an existing turn.')
            ident = db.execute('INSERT INTO memories(content,created,source_kind,source_ref,updated) VALUES(?,?,?,?,?)',
                               (content, now(), source_kind, source_ref, now())).lastrowid
            self._audit(db, {'event': 'memory_created', 'memory_id': ident, 'source_kind': source_kind, 'source_ref': source_ref})
            return ident

    def memories(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM memories ORDER BY id')]

    def forget(self, memory_id):
        with self.connect() as db:
            if db.execute('DELETE FROM memories WHERE id=?', (memory_id,)).rowcount:
                self._audit(db, {'event': 'memory_deleted', 'memory_id': memory_id})

    def retrieve(self, query, limit=5):
        terms = set(re.findall(r'\w{3,}', query.lower()))
        scored = [(len(terms & set(re.findall(r'\w{3,}', m['content'].lower()))), m) for m in self.memories()]
        return [m for score, m in sorted(scored, key=lambda x: (-x[0], -x[1]['id'])) if score][:limit]

    def _audit(self, db, data):
        return db.execute('INSERT INTO audit(created,data,turn_id) VALUES(?,?,?)',
                          (now(), json.dumps(data), data.get('turn_id'))).lastrowid

    def audit(self, data):
        with self.connect() as db:
            return self._audit(db, data)

    def audits(self, limit=200, offset=0, turn_id=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM audit WHERE (? IS NULL OR turn_id=?) ORDER BY id DESC LIMIT ? OFFSET ?',
                (turn_id, turn_id, limit, offset))]
