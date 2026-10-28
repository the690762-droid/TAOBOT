"""SQLite storage: jobs, events, runs."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from quality.safety import redact

DB_PATH = Path(__file__).resolve().parent / "ryan.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, request TEXT NOT NULL, project TEXT, status TEXT NOT NULL,
  plan TEXT, source TEXT, created REAL, updated REAL, result TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, ts REAL, agent TEXT, kind TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, agent TEXT, role TEXT, ok INTEGER,
  exit_code INTEGER, duration REAL, stdout TEXT, stderr TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY, path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""

# Trạng thái hợp lệ của công việc
STATUSES = ("NEW", "PLANNING", "AWAITING_APPROVAL", "APPROVED", "RUNNING",
            "REVIEWING", "DONE", "FAILED", "BLOCKED", "CANCELLED")


class DB:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def create_job(self, request, project=None, source="desktop"):
        jid = uuid.uuid4().hex[:8]
        now = time.time()
        self._q("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (jid, request, project, "NEW", None, source, now, now, None))
        self.event(jid, "system", "created", request)
        return jid

    def get_job(self, jid):
        r = self._q("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None

    def list_jobs(self, limit=50):
        return [dict(r) for r in self._q("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def set_status(self, jid, status, **fields):
        """Trả về False nếu công việc đã CANCELLED (không cho ghi đè trạng thái hủy)."""
        assert status in STATUSES, status
        sets, args = ["status=?", "updated=?"], [status, time.time()]
        for k in ("plan", "result", "project"):
            if k in fields:
                sets.append(f"{k}=?")
                v = fields[k]
                args.append(v if isinstance(v, str) or v is None else json.dumps(v, ensure_ascii=False))
        cur = self._q(f"UPDATE jobs SET {','.join(sets)} WHERE id=? AND (status!='CANCELLED' OR ?='CANCELLED')",
                      (*args, jid, status))
        if cur.rowcount == 0:
            return False
        self.event(jid, "system", "status", status)
        return True

    def event(self, jid, agent, kind, message):
        self._q("INSERT INTO events(job_id,ts,agent,kind,message) VALUES(?,?,?,?,?)",
                (jid, time.time(), agent, kind, redact(message)))

    def events(self, jid, limit=200):
        return [dict(r) for r in self._q(
            "SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?", (jid, limit))][::-1]

    def add_run(self, jid, res):
        self._q("INSERT INTO runs(job_id,agent,role,ok,exit_code,duration,stdout,stderr,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                (jid, res["agent"], res.get("role"), int(res["ok"]), res["exit_code"],
                 res["duration"], redact(res["stdout"]), redact(res["stderr"]), time.time()))

    def runs(self, jid=None, limit=100):
        if jid:
            rows = self._q("SELECT * FROM runs WHERE job_id=? ORDER BY id DESC LIMIT ?", (jid, limit))
        else:
            rows = self._q("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def add_project(self, name, path):
        self._q("INSERT OR REPLACE INTO projects VALUES(?,?)", (name, path))

    def projects(self):
        return [dict(r) for r in self._q("SELECT * FROM projects ORDER BY name")]

    def kv_get(self, k, default=None):
        r = self._q("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def kv_set(self, k, v):
        self._q("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, v))
