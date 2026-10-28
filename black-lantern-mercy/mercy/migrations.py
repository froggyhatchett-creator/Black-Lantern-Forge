"""Forward-only, transactional schema upgrades with pre-upgrade backups."""
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

SCHEMA_VERSION = 2


def migrate(path):
    path = Path(path)
    db = sqlite3.connect(path)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError(f'Database schema {version} is newer than supported {SCHEMA_VERSION}.')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version == 0 and tables:
            raise ValueError('Unversioned nonempty database; refusing to guess its schema.')
        if version == SCHEMA_VERSION:
            return
        if version:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
            with closing(sqlite3.connect(path.with_name(f'{path.name}.pre-v2-{stamp}.bak'))) as target:
                db.backup(target)
        db.execute('BEGIN IMMEDIATE')
        try:
            if version == 0:
                db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL)')
                db.execute('CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT NOT NULL, created TEXT NOT NULL)')
                db.execute('CREATE TABLE audit (id INTEGER PRIMARY KEY, created TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)')
            db.execute("INSERT INTO conversations(id,title,created) VALUES(1,'First conversation',?)", (datetime.now(timezone.utc).isoformat(),))
            db.execute('CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id), state TEXT NOT NULL, started TEXT NOT NULL, ended TEXT, error TEXT, provider TEXT)')
            db.execute("CREATE UNIQUE INDEX one_active_turn ON turns(conversation_id) WHERE state='running'")
            db.execute('ALTER TABLE messages ADD COLUMN conversation_id INTEGER NOT NULL DEFAULT 1 REFERENCES conversations(id)')
            db.execute('ALTER TABLE messages ADD COLUMN turn_id TEXT REFERENCES turns(id)')
            db.execute("ALTER TABLE memories ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'legacy'")
            db.execute('ALTER TABLE memories ADD COLUMN source_ref TEXT')
            db.execute('ALTER TABLE memories ADD COLUMN updated TEXT')
            db.execute('ALTER TABLE audit ADD COLUMN turn_id TEXT')
            db.execute('CREATE INDEX message_context ON messages(conversation_id,id)')
            db.execute('CREATE INDEX audit_turn ON audit(turn_id,id)')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    finally:
        db.close()
