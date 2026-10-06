"""SQLite persistence: conversations, frozen plan versions, approvals, runs, ledger, audit."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbound  (msg_id TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS convs    (phone TEXT PRIMARY KEY, state TEXT, brief TEXT, plan_id TEXT,
                                     history TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS plans    (id TEXT, version INTEGER, owner TEXT, status TEXT, body TEXT,
                                     hash TEXT, est_tokens INTEGER, created REAL, note TEXT,
                                     PRIMARY KEY (id, version));
CREATE TABLE IF NOT EXISTS approvals(plan_id TEXT, version INTEGER, phone TEXT, ts REAL,
                                     PRIMARY KEY (plan_id, version, phone));
CREATE TABLE IF NOT EXISTS steps    (plan_id TEXT, version INTEGER, step_id TEXT, status TEXT,
                                     digest TEXT, path TEXT, tokens INTEGER, cost REAL,
                                     PRIMARY KEY (plan_id, version, step_id));
CREATE TABLE IF NOT EXISTS ledger   (ts REAL, plan_id TEXT, purpose TEXT, model TEXT, inp INTEGER,
                                     outp INTEGER, cache_r INTEGER, cache_w INTEGER, cost REAL);
CREATE TABLE IF NOT EXISTS audit    (ts REAL, actor TEXT, event TEXT, data TEXT);
"""

_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity on phones


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _x(self, sql: str, args=()) -> sqlite3.Cursor:
        with self.lock:
            return self.db.execute(sql, args)

    # --- idempotency (WhatsApp re-delivers webhooks) ------------------------
    def seen(self, msg_id: str) -> bool:
        try:
            self._x("INSERT INTO inbound VALUES (?,?)", (msg_id, time.time()))
            return False
        except sqlite3.IntegrityError:
            return True

    # --- conversations ------------------------------------------------------
    def conv(self, phone: str) -> dict:
        row = self._x("SELECT * FROM convs WHERE phone=?", (phone,)).fetchone()
        if not row:
            return {"phone": phone, "state": "cadrage", "brief": {}, "plan_id": None, "history": []}
        return {
            "phone": phone,
            "state": row["state"],
            "brief": json.loads(row["brief"] or "{}"),
            "plan_id": row["plan_id"],
            "history": json.loads(row["history"] or "[]"),
        }

    def save_conv(self, c: dict) -> None:
        self._x(
            "INSERT OR REPLACE INTO convs VALUES (?,?,?,?,?,?)",
            (c["phone"], c["state"], json.dumps(c["brief"], ensure_ascii=False), c["plan_id"],
             json.dumps(c["history"], ensure_ascii=False), time.time()),
        )

    # --- plans (each version frozen once written) ---------------------------
    def new_plan_id(self) -> str:
        while True:
            pid = "P-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(4))
            if not self._x("SELECT 1 FROM plans WHERE id=?", (pid,)).fetchone():
                return pid

    def add_plan(self, pid: str, version: int, owner: str, body: dict, h: str, est: int, note: str = "") -> None:
        self._x("UPDATE plans SET status='superseded' WHERE id=? AND status='proposed'", (pid,))
        self._x(
            "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, version, owner, "proposed", json.dumps(body, ensure_ascii=False), h, est, time.time(), note),
        )

    def plan(self, pid: str, version: int | None = None) -> dict | None:
        if version is None:
            row = self._x("SELECT * FROM plans WHERE id=? ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
        else:
            row = self._x("SELECT * FROM plans WHERE id=? AND version=?", (pid, version)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["body"] = json.loads(d["body"])
        return d

    def set_plan_status(self, pid: str, version: int, status: str) -> None:
        self._x("UPDATE plans SET status=? WHERE id=? AND version=?", (status, pid, version))

    def active_plans(self) -> list[dict]:
        rows = self._x(
            "SELECT id, version, owner, status FROM plans p WHERE version=(SELECT MAX(version) FROM plans WHERE id=p.id)"
            " AND status IN ('proposed','approved','running','delivered') ORDER BY created DESC LIMIT 20"
        ).fetchall()
        return [dict(r) for r in rows]

    def plans_with_status(self, *statuses: str) -> list[dict]:
        q = ",".join("?" * len(statuses))
        return [dict(r) for r in self._x(f"SELECT id, version, owner, status FROM plans WHERE status IN ({q})", statuses)]

    # --- approvals ----------------------------------------------------------
    def approve(self, pid: str, version: int, phone: str) -> int:
        self._x("INSERT OR IGNORE INTO approvals VALUES (?,?,?,?)", (pid, version, phone, time.time()))
        return self._x("SELECT COUNT(*) FROM approvals WHERE plan_id=? AND version=?", (pid, version)).fetchone()[0]

    # --- step results -------------------------------------------------------
    def save_step(self, pid: str, version: int, sid: str, status: str, digest: dict | None = None,
                  path: str = "", tokens: int = 0, cost: float = 0.0) -> None:
        self._x(
            "INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?,?,?,?)",
            (pid, version, sid, status, json.dumps(digest or {}, ensure_ascii=False), path, tokens, cost),
        )

    def steps(self, pid: str, version: int) -> dict[str, dict]:
        rows = self._x("SELECT * FROM steps WHERE plan_id=? AND version=?", (pid, version)).fetchall()
        return {r["step_id"]: {**dict(r), "digest": json.loads(r["digest"])} for r in rows}

    # --- ledger & audit -----------------------------------------------------
    def log_usage(self, pid: str | None, purpose: str, r) -> None:
        self._x(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), pid, purpose, r.model, r.input_tokens, r.output_tokens, r.cache_read, r.cache_write, r.cost),
        )

    def spent(self, pid: str, purpose_prefix: str = "") -> tuple[int, float]:
        row = self._x(
            "SELECT COALESCE(SUM(inp+outp+cache_r+cache_w),0), COALESCE(SUM(cost),0) FROM ledger"
            " WHERE plan_id=? AND purpose LIKE ?", (pid, purpose_prefix + "%"),
        ).fetchone()
        return int(row[0]), float(row[1])

    def audit(self, actor: str, event: str, **data) -> None:
        self._x("INSERT INTO audit VALUES (?,?,?,?)", (time.time(), actor, event, json.dumps(data, ensure_ascii=False)))
