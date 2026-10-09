"""SQLite persistence: conversations, message history, frozen plan versions, approvals, runs, ledger, audit."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbound  (msg_id TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS convs    (user TEXT PRIMARY KEY, state TEXT, brief TEXT, plan_id TEXT,
                                     history TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS plans    (id TEXT, version INTEGER, owner TEXT, status TEXT, body TEXT,
                                     hash TEXT, est_tokens INTEGER, created REAL, note TEXT,
                                     PRIMARY KEY (id, version));
CREATE TABLE IF NOT EXISTS approvals(plan_id TEXT, version INTEGER, user TEXT, ts REAL,
                                     PRIMARY KEY (plan_id, version, user));
CREATE TABLE IF NOT EXISTS steps    (plan_id TEXT, version INTEGER, step_id TEXT, status TEXT,
                                     digest TEXT, path TEXT, tokens INTEGER, cost REAL,
                                     PRIMARY KEY (plan_id, version, step_id));
CREATE TABLE IF NOT EXISTS ledger   (ts REAL, plan_id TEXT, purpose TEXT, model TEXT, inp INTEGER,
                                     outp INTEGER, cache_r INTEGER, cache_w INTEGER, cost REAL);
CREATE TABLE IF NOT EXISTS audit    (ts REAL, actor TEXT, event TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, author TEXT,
                                     kind TEXT, body TEXT, meta TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS messages_user ON messages (user, id);
CREATE TABLE IF NOT EXISTS blocked  (user TEXT PRIMARY KEY, ts REAL, by_user TEXT);
"""

_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity when typed by hand


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

    # --- idempotency (clients retry: each message carries a client-side id) ------------------------
    def seen(self, msg_id: str) -> bool:
        try:
            self._x("INSERT INTO inbound VALUES (?,?)", (msg_id, time.time()))
            return False
        except sqlite3.IntegrityError:
            return True

    # --- conversations ------------------------------------------------------
    def conv(self, user: str) -> dict:
        row = self._x("SELECT * FROM convs WHERE user=?", (user,)).fetchone()
        if not row:
            return {"user": user, "state": "cadrage", "brief": {}, "plan_id": None, "history": []}
        return {
            "user": user,
            "state": row["state"],
            "brief": json.loads(row["brief"] or "{}"),
            "plan_id": row["plan_id"],
            "history": json.loads(row["history"] or "[]"),
        }

    def save_conv(self, c: dict) -> None:
        self._x(
            "INSERT OR REPLACE INTO convs VALUES (?,?,?,?,?,?)",
            (c["user"], c["state"], json.dumps(c["brief"], ensure_ascii=False), c["plan_id"],
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
    def approve(self, pid: str, version: int, user: str) -> int:
        self._x("INSERT OR IGNORE INTO approvals VALUES (?,?,?,?)", (pid, version, user, time.time()))
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

    # --- message history (what each user sees, on any device) ---------------
    def add_message(self, user: str, author: str, kind: str, body: str, meta: dict | None = None) -> dict:
        ts = time.time()
        cur = self._x(
            "INSERT INTO messages (user, author, kind, body, meta, ts) VALUES (?,?,?,?,?,?)",
            (user, author, kind, body, json.dumps(meta or {}, ensure_ascii=False), ts),
        )
        return {"id": cur.lastrowid, "author": author, "kind": kind, "body": body, "meta": meta or {}, "ts": ts}

    def messages(self, user: str, after: int = 0, limit: int = 200) -> list[dict]:
        rows = self._x(
            "SELECT * FROM (SELECT * FROM messages WHERE user=? AND id>? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (user, after, limit),
        ).fetchall()
        return [{"id": r["id"], "author": r["author"], "kind": r["kind"], "body": r["body"],
                 "meta": json.loads(r["meta"]), "ts": r["ts"]} for r in rows]

    def message(self, msg_id: int) -> dict | None:
        r = self._x("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        return {**dict(r), "meta": json.loads(r["meta"])} if r else None

    # --- administration ------------------------------------------------------
    def is_blocked(self, user: str) -> bool:
        return self._x("SELECT 1 FROM blocked WHERE user=?", (user,)).fetchone() is not None

    def set_blocked(self, user: str, blocked: bool, by: str) -> None:
        if blocked:
            self._x("INSERT OR REPLACE INTO blocked VALUES (?,?,?)", (user, time.time(), by))
        else:
            self._x("DELETE FROM blocked WHERE user=?", (user,))

    def overview(self) -> dict:
        """Per-person activity and spend, for the admin panel."""
        usage = {
            r["user"]: (int(r["tokens"]), float(r["cost"]))
            for r in self._x(
                """SELECT u AS user, SUM(t) AS tokens, SUM(c) AS cost FROM (
                       SELECT CASE WHEN l.plan_id IS NULL THEN substr(l.purpose, instr(l.purpose, ':') + 1)
                                   ELSE (SELECT owner FROM plans p WHERE p.id = l.plan_id LIMIT 1) END AS u,
                              l.inp + l.outp + l.cache_r + l.cache_w AS t, l.cost AS c
                       FROM ledger l) GROUP BY u"""
            )
        }
        activity = {
            r["user"]: (r["n"], r["last"])
            for r in self._x("SELECT user, COUNT(*) AS n, MAX(ts) AS last FROM messages WHERE author='u' GROUP BY user")
        }
        blocked = {r["user"] for r in self._x("SELECT user FROM blocked")}
        names = set(usage) | set(activity) | blocked | {r["user"] for r in self._x("SELECT user FROM convs")}
        people = [
            {"user": n, "messages": activity.get(n, (0, None))[0], "last": activity.get(n, (0, None))[1],
             "tokens": usage.get(n, (0, 0.0))[0], "cost": round(usage.get(n, (0, 0.0))[1], 4), "blocked": n in blocked}
            for n in names if n
        ]
        people.sort(key=lambda p: (p["last"] or 0), reverse=True)
        plans = [dict(r) for r in self._x(
            "SELECT id, version, owner, status, est_tokens, created FROM plans p"
            " WHERE version=(SELECT MAX(version) FROM plans WHERE id=p.id) ORDER BY created DESC LIMIT 50"
        )]
        return {
            "people": people,
            "plans": plans,
            "totals": {"tokens": sum(p["tokens"] for p in people), "cost": round(sum(p["cost"] for p in people), 4)},
        }

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
