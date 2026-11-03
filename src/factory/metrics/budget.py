"""Persistent campaign rounds; explicit reauthorization never erases past calls."""

import sqlite3
import time
import math
import os
from contextlib import contextmanager, closing
from pathlib import Path

from contracts import ErrorCode, FactoryError


class CallBudget:
    def __init__(self, path: Path, limit=None, *, lock_timeout=None):
        if limit is not None and (type(limit) is not int or not 0 < limit <= 600):
            raise ValueError("campaign cap must be between 1 and 600")
        self.path = Path(path)
        self.lock_timeout = float(
            os.environ.get("FACTORY_BUDGET_LOCK_TIMEOUT", "30")
            if lock_timeout is None else lock_timeout
        )
        if not math.isfinite(self.lock_timeout) or self.lock_timeout <= 0:
            raise ValueError("positive finite budget lock timeout required")
        if self.path.is_symlink():
            raise ValueError("budget path must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Configure writers only. read_campaign deliberately never changes journal mode.
        with closing(sqlite3.connect(self.path, timeout=self.lock_timeout)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS budget(limit_calls INTEGER NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                call_key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, status TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0)""")
            row = db.execute("SELECT limit_calls FROM budget").fetchone()
            if row is None:
                db.execute("INSERT INTO budget VALUES (?)", (60 if limit is None else limit,))
            elif type(row[0]) is not int or not 0 < row[0] <= 600:
                raise ValueError("invalid persisted campaign cap")
            elif limit is not None and row[0] != limit:
                raise ValueError("campaign budget is immutable; do not reset it between tasks")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=self.lock_timeout, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, key, input_hash):
        with self.transaction() as db:
            has_rounds = _has_rounds(db)
            round_id = _active_round(db)
            old = db.execute("SELECT input_hash" + (",round_id" if has_rounds else "") + " FROM calls WHERE call_key=?", (key,)).fetchone()
            if old:
                if old[0] != input_hash:
                    raise ValueError("campaign call key conflict")
                return old[1] if has_rounds else 1
            used = db.execute("SELECT COUNT(*) FROM calls" + (" WHERE round_id=?" if has_rounds else ""), (round_id,) if has_rounds else ()).fetchone()[0]
            cap = db.execute("SELECT limit_calls FROM budget").fetchone()[0]
            if used >= cap:
                raise FactoryError(ErrorCode.BUDGET_EXHAUSTED, "campaign model call cap reached")
            if has_rounds:
                db.execute("INSERT INTO calls(call_key,input_hash,status,sent,round_id) VALUES (?,?,'RESERVED',0,?)", (key, input_hash, round_id))
            else:
                db.execute("INSERT INTO calls VALUES (?,?,'RESERVED',0)", (key, input_hash))
            return round_id

    def mark(self, key, status):
        with self.transaction() as db:
            db.execute("UPDATE calls SET status=?,sent=MAX(sent,?) WHERE call_key=?",
                       (status, int(status == "SENT"), key))

    def authorize_round(self, limit, authorization_id):
        """Only an explicit user action may create a new authorization round."""
        if type(limit) is not int or limit not in (60, 150, 300, 600):
            raise ValueError("round limit must be 60, 150, 300 or 600")
        if not isinstance(authorization_id, str) or not 1 <= len(authorization_id) <= 100:
            raise ValueError("bounded authorization ID required")
        with self.transaction() as db:
            if not _has_rounds(db):
                legacy_limit = db.execute("SELECT limit_calls FROM budget").fetchone()[0]
                db.execute("CREATE TABLE budget_rounds (round_id INTEGER PRIMARY KEY, limit_calls INTEGER NOT NULL, started_at REAL, authorization_id TEXT NOT NULL UNIQUE)")
                db.execute("INSERT INTO budget_rounds VALUES (1,?,NULL,'legacy')", (legacy_limit,))
                # Existing input hashes, statuses and sent flags are untouched.
                db.execute("ALTER TABLE calls ADD COLUMN round_id INTEGER NOT NULL DEFAULT 1")
                db.execute("CREATE INDEX calls_round ON calls(round_id)")
            old = db.execute("SELECT round_id,limit_calls FROM budget_rounds WHERE authorization_id=?", (authorization_id,)).fetchone()
            if old:
                if old[1] != limit:
                    raise ValueError("authorization ID conflict")
                return old[0]
            round_id = _active_round(db) + 1
            db.execute("INSERT INTO budget_rounds VALUES (?,?,?,?)", (round_id, limit, time.time(), authorization_id))
            db.execute("UPDATE budget SET limit_calls=?", (limit,))
            return round_id

    def summary(self):
        return read_campaign(self.path)


def _has_rounds(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='budget_rounds'").fetchone() is not None


def _active_round(db):
    return db.execute("SELECT MAX(round_id) FROM budget_rounds").fetchone()[0] if _has_rounds(db) else 1


def read_campaign(path):
    """Read current and historical rounds without creating/migrating a ledger."""
    path = Path(path)
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT limit_calls FROM budget").fetchone()
        if row is None:
            return None
        if type(row[0]) is not int or not 0 < row[0] <= 600:
            raise ValueError("invalid persisted campaign cap")
        has_rounds = _has_rounds(db)
        current = _active_round(db)
        where, values = (" WHERE round_id=?", (current,)) if has_rounds else ("", ())
        used, sent = db.execute("SELECT COUNT(*),COALESCE(SUM(sent),0) FROM calls" + where, values).fetchone()
        lifetime = db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        history = []
        if has_rounds:
            for number, cap, started in db.execute("SELECT round_id,limit_calls,started_at FROM budget_rounds ORDER BY round_id DESC"):
                count = db.execute("SELECT COUNT(*) FROM calls WHERE round_id=?", (number,)).fetchone()[0]
                history.append({"轮次": number, "上限": cap, "已预约": count, "剩余": max(0, cap-count), "当前轮": number == current, "开始时间": started})
        else:
            history = [{"轮次": 1, "上限": row[0], "已预约": used, "剩余": max(0, row[0]-used), "当前轮": True, "开始时间": None}]
    return {"limit": row[0], "reserved": used, "used": used, "sent": sent, "remaining": max(0, row[0]-used),
            "round": current, "lifetime_reserved": lifetime, "rounds": history,
            "accounting": "reservations include uncertain requests; new rounds require explicit authorization; no history erased"}
