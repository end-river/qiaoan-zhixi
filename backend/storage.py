"""Local persistence. Paths are anchored to the project, never the shell cwd."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('BRIDGE_DATA_DIR', ROOT / 'runtime'))

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'bridge.db', timeout=15)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL)')
    return db

def save(kind, body, identifier=None):
    identifier = identifier or uuid.uuid4().hex
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?,?)', (identifier, kind, json.dumps(body, ensure_ascii=False, allow_nan=False), datetime.now(timezone.utc).isoformat()))
    return {'id': identifier, **body}

def get(kind, identifier):
    with connect() as db:
        row = db.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind, identifier)).fetchone()
    if row is None:
        raise KeyError(identifier)
    return {'id': identifier, **json.loads(row[0])}

def listing(kind):
    with connect() as db:
        rows = db.execute('SELECT id, body FROM objects WHERE kind=? ORDER BY created DESC', (kind,)).fetchall()
    return [{'id': i, **json.loads(b)} for i, b in rows]
