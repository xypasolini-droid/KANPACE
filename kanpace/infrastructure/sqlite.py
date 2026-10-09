"""SQLite persistence and explicit transaction scopes for one factory instance.

The existing schema, JSON records and compatibility reads stay unchanged.
Application services receive a connection and never commit individual writes.
Opening persistence never creates business settings, personnel or demo orders.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading

from kanpace.core.errors import APIError
from kanpace.core.records import part_aliases, project_aliases, task_aliases


_transaction_context = threading.local()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class SQLiteRepository:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads = self.data_dir / 'uploads'
        self.uploads.mkdir(exist_ok=True)
        self.db_path = self.data_dir / 'cabinet-flow.sqlite3'
        with self.connect() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('CREATE TABLE IF NOT EXISTS entities (kind TEXT NOT NULL,id TEXT PRIMARY KEY,project_id TEXT,data TEXT NOT NULL)')
            con.execute('CREATE INDEX IF NOT EXISTS entities_project ON entities(kind,project_id)')
            con.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            marker=con.execute("SELECT value FROM config WHERE key='factory_instance'").fetchone()
            self.instance_id=json.loads(marker['value']).get('id') if marker else None

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def all(self, con, kind, project_id=None):
        if project_id:
            rows = con.execute('SELECT data FROM entities WHERE kind=? AND project_id=? ORDER BY rowid', (kind, project_id))
        else:
            rows = con.execute('SELECT data FROM entities WHERE kind=? ORDER BY rowid', (kind,))
        items = [json.loads(row['data']) for row in rows]
        return [task_aliases(item) for item in items] if kind == 'tasks' else [project_aliases(item) for item in items] if kind == 'projects' else items

    def get(self, con, kind, identifier):
        row = con.execute('SELECT data FROM entities WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if not row:
            raise APIError(404, '未找到记录：' + identifier)
        item = json.loads(row['data'])
        return task_aliases(item) if kind == 'tasks' else project_aliases(item) if kind == 'projects' else item

    def put(self, con, kind, item):
        if kind == 'parts':
            part_aliases(item)
        elif kind == 'tasks':
            task_aliases(item)
        elif kind == 'projects':
            project_aliases(item)
        con.execute('INSERT INTO entities(kind,id,project_id,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,project_id=excluded.project_id',
            (kind, item['id'], item.get('project_id'), json.dumps(item, ensure_ascii=False, allow_nan=False)))
        return item

    def settings(self, con):
        return json.loads(con.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0])

    def active_parts(self, con, project_id):
        return [p for p in self.all(con, 'parts', project_id) if not p.get('archived')]

    def active_tasks(self, con, project_id):
        return [t for t in self.all(con, 'tasks', project_id) if not t.get('archived')]

    @contextmanager
    def _transaction(self, *, write, query_only=True):
        # Nested independent connections would otherwise commit independently or
        # wait on our own write lock. Services must reuse the caller's connection.
        active = getattr(_transaction_context, 'databases', None)
        if active is None:
            active = _transaction_context.databases = set()
        database = str(self.db_path)
        if database in active:
            raise RuntimeError('Nested transaction for the same database; reuse the current connection')
        active.add(database)
        try:
            with self.connect() as con:
                if not write and query_only:
                    con.execute('PRAGMA query_only=ON')
                con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield con
        finally:
            active.remove(database)

    @contextmanager
    def read_transaction(self, *, query_only=True):
        """Yield one snapshot connection; reject writes by default and always close."""
        with self._transaction(write=False, query_only=query_only) as con:
            yield con

    @contextmanager
    def write_transaction(self):
        """Commit all writes together, or roll all of them back on any exception."""
        with self._transaction(write=True) as con:
            yield con
