"""工作台数据层：除文件索引外的所有业务数据，全部落本机 SQLite。"""

from __future__ import annotations

import os
import json
import sqlite3
import threading
import time
import calendar
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created REAL,
    done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS today (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT,
    text TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    tags TEXT,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    url TEXT,
    tags TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    status TEXT,
    next_step TEXT,
    updated REAL
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    model TEXT,
    created REAL,
    messages TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT,
    start TEXT,
    end TEXT,
    title TEXT,
    note TEXT,
    source TEXT DEFAULT 'manual',
    done INTEGER DEFAULT 0,
    created REAL
);
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT,
    start TEXT,
    end TEXT,
    title TEXT,
    location TEXT,
    link TEXT,
    attendees TEXT,
    note TEXT,
    remind_before INTEGER DEFAULT 10,
    reminder_id INTEGER DEFAULT 0,
    source TEXT DEFAULT 'manual',
    created REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER DEFAULT 0,
    title TEXT,
    state TEXT DEFAULT '待办',
    sort INTEGER DEFAULT 0,
    created REAL,
    done_at REAL
);
CREATE TABLE IF NOT EXISTS pomodoro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER DEFAULT 0,
    task_id INTEGER DEFAULT 0,
    minutes REAL DEFAULT 0,
    started REAL,
    ended REAL,
    title TEXT
);
CREATE TABLE IF NOT EXISTS plog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'log',
    text TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT
);
CREATE TABLE IF NOT EXISTS daylog (
    day TEXT PRIMARY KEY,
    text TEXT,
    updated REAL
);
CREATE TABLE IF NOT EXISTS lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    fields TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS room_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    data TEXT,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS clip (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL,
    text TEXT,
    done INTEGER DEFAULT 0,
    created REAL
);
CREATE TABLE IF NOT EXISTS file_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    tag TEXT,
    UNIQUE(path, tag)
);
CREATE TABLE IF NOT EXISTS kb (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    tags TEXT,
    source TEXT DEFAULT 'manual',
    source_path TEXT,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS openclaw_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    task TEXT,
    reply TEXT,
    ok INTEGER DEFAULT 1,
    mode TEXT DEFAULT 'run'
);
CREATE TABLE IF NOT EXISTS bridge_pending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    action TEXT,
    payload TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT
);
CREATE TABLE IF NOT EXISTS bridge_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    action TEXT,
    payload TEXT,
    summary TEXT,
    decision TEXT,
    actor TEXT,
    result TEXT
);
CREATE TABLE IF NOT EXISTS connector_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    type TEXT,
    name TEXT,
    title TEXT,
    ok INTEGER DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS task_tpl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    items TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS file_fav (
    path TEXT PRIMARY KEY,
    created REAL
);
CREATE TABLE IF NOT EXISTS file_open (
    path TEXT PRIMARY KEY,
    opened REAL,
    count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    md TEXT,
    tags TEXT DEFAULT '',
    fav INTEGER DEFAULT 0,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS doc_snaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    ts REAL,
    md TEXT,
    chars INTEGER DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_doc_snaps ON doc_snaps(doc_id, ts);
CREATE TABLE IF NOT EXISTS mail_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    field TEXT DEFAULT 'from',
    contains TEXT,
    tag TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS mail_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acct TEXT DEFAULT '',
    uid TEXT,
    tags TEXT DEFAULT '',
    starred INTEGER DEFAULT 0,
    created REAL,
    UNIQUE(acct, uid)
);
CREATE TABLE IF NOT EXISTS mail_body (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acct TEXT DEFAULT '',
    uid TEXT,
    subject TEXT,
    mfrom TEXT,
    mdate TEXT,
    body TEXT,
    created REAL,
    UNIQUE(acct, uid)
);
CREATE TABLE IF NOT EXISTS mail_draft (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acct TEXT DEFAULT '',
    mto TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    body TEXT DEFAULT '',
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS mail_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acct TEXT DEFAULT '',
    mto TEXT,
    subject TEXT,
    body TEXT,
    at REAL DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error TEXT DEFAULT '',
    created REAL,
    sent REAL
);
"""

# 老库加列：新库没有这些列时补上，已存在就忽略
ALTERS = [
    "ALTER TABLE today ADD COLUMN project_id INTEGER DEFAULT 0",
    "ALTER TABLE today ADD COLUMN created REAL",
    "ALTER TABLE projects ADD COLUMN note TEXT",
    "ALTER TABLE tasks ADD COLUMN due TEXT",
    # B 域：今日/任务进阶
    "ALTER TABLE today ADD COLUMN priority INTEGER DEFAULT 1",
    "ALTER TABLE today ADD COLUMN parent_id INTEGER DEFAULT 0",
    "ALTER TABLE today ADD COLUMN repeat TEXT DEFAULT ''",
    "ALTER TABLE today ADD COLUMN est REAL DEFAULT 0",
    "ALTER TABLE today ADD COLUMN act REAL DEFAULT 0",
    "ALTER TABLE today ADD COLUMN note TEXT DEFAULT ''",
    "ALTER TABLE today ADD COLUMN done_at REAL",
    "ALTER TABLE pomodoro ADD COLUMN today_id INTEGER DEFAULT 0",
    # D 域：AI 问一问
    "ALTER TABLE chats ADD COLUMN sys TEXT DEFAULT ''",
    # E 域：OpenClaw 干活
    "ALTER TABLE openclaw_runs ADD COLUMN fav INTEGER DEFAULT 0",
    "ALTER TABLE openclaw_runs ADD COLUMN agent TEXT DEFAULT ''",
    "ALTER TABLE openclaw_runs ADD COLUMN dur REAL DEFAULT 0",
    "ALTER TABLE openclaw_runs ADD COLUMN qid INTEGER DEFAULT 0",
    # H 域：日历 / 会议进阶（71-78）
    "ALTER TABLE events ADD COLUMN repeat TEXT DEFAULT ''",
    "ALTER TABLE events ADD COLUMN repeat_until TEXT DEFAULT ''",
    "ALTER TABLE events ADD COLUMN exdate TEXT DEFAULT ''",
    "ALTER TABLE events ADD COLUMN color TEXT DEFAULT ''",
    "ALTER TABLE events ADD COLUMN remind_before INTEGER DEFAULT 0",
    "ALTER TABLE events ADD COLUMN reminder_id INTEGER DEFAULT 0",
    # 75 推送通道：同一条提醒只推一次连接器
    "ALTER TABLE reminders ADD COLUMN pushed INTEGER DEFAULT 0",
]

PROMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    tags TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    note TEXT,
    sort INTEGER DEFAULT 0,
    created REAL
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER,
    day TEXT,
    created REAL,
    UNIQUE(habit_id, day)
);
"""


def _today() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


def _tomorrow() -> str:
    import datetime as _dt
    return (_dt.date.today() + _dt.timedelta(days=1)).isoformat()


# ---- 73 重复日程：规则展开 ----
# 库里只留一条原型（day + repeat），取某个窗口时现算，避免「改规则要批量改数据」。

REPEATS = ("daily", "weekdays", "weekly", "monthly", "yearly")


def _d(s: str):
    try:
        y, m, dd = (int(x) for x in (s or "").split("-"))
        return datetime.date(y, m, dd)
    except (ValueError, TypeError):
        return None


def _add_months(base: datetime.date, n: int) -> datetime.date:
    total = base.year * 12 + (base.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    return datetime.date(y, m, min(base.day, calendar.monthrange(y, m)[1]))


def expand_event(ev: dict, a: str, b: str) -> list[str]:
    """一个日程在 [a,b] 里的所有发生日（含重复规则、跳过 exdate）。"""
    base = _d(ev.get("day"))
    lo, hi = _d(a), _d(b)
    if not base or not lo or not hi:
        return []
    rep = (ev.get("repeat") or "").strip()
    ex = {x.strip() for x in (ev.get("exdate") or "").split(",") if x.strip()}
    if not rep:
        return [base.isoformat()] if lo <= base <= hi else []
    until = _d(ev.get("repeat_until"))
    if until and until < hi:
        hi = until
    if hi < max(lo, base):
        return []
    out: list[str] = []
    i = 0
    cur = base
    while cur and cur <= hi and i < 2000:
        if cur >= lo and cur.isoformat() not in ex:
            out.append(cur.isoformat())
        i += 1
        if rep == "daily":
            cur = base + datetime.timedelta(days=i)
        elif rep == "weekdays":                       # 周一到周五
            cur = base + datetime.timedelta(days=i)
            while cur.weekday() >= 5:
                i += 1
                cur = base + datetime.timedelta(days=i)
        elif rep == "weekly":
            cur = base + datetime.timedelta(days=7 * i)
        elif rep == "monthly":
            cur = _add_months(base, i)
        elif rep == "yearly":
            try:
                cur = base.replace(year=base.year + i)
            except ValueError:                        # 2/29 落在平年 → 取 2/28
                cur = base.replace(year=base.year + i, day=28)
        else:
            break
    return out


class Store:
    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.executescript(PROMPT_SCHEMA)
        for sql in ALTERS:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # 列已存在
        self.conn.commit()

    def _run(self, sql: str, args=(), fetch=True):
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall() if fetch else []
            self.conn.commit()
            return [dict(r) for r in rows]

    # ---- 快速捕捉 ----

    def inbox_add(self, text: str) -> dict:
        self._run("INSERT INTO inbox (text, created) VALUES (?,?)", (text, time.time()), False)
        return {"ok": True}

    def inbox_list(self, limit=200) -> list[dict]:
        return self._run(
            "SELECT * FROM inbox ORDER BY done, id DESC LIMIT ?", (limit,)
        )

    def inbox_done(self, id_: int, done: int) -> dict:
        self._run("UPDATE inbox SET done=? WHERE id=?", (done, id_), False)
        return {"ok": True}

    def inbox_del(self, id_: int) -> dict:
        self._run("DELETE FROM inbox WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 今日三件事 ----

    def today_list(self, day: str) -> list[dict]:
        rows = self._run(
            "SELECT t.*, COALESCE(p.name,'') AS project FROM today t "
            "LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.day=? ORDER BY t.done, t.priority, t.sort, t.id", (day,)
        )
        # 子任务进度统计挂到父任务上（n_sub / n_sub_done）
        subs = {}
        for r in rows:
            pid = int(r.get("parent_id") or 0)
            if pid:
                s = subs.setdefault(pid, [0, 0])
                s[0] += 1
                if r["done"]:
                    s[1] += 1
        for r in rows:
            c = subs.get(r["id"])
            if c:
                r["n_sub"], r["n_sub_done"] = c
        return rows

    def today_add(self, day: str, text: str, project_id: int = 0,
                  priority: int = 1, est=0, note: str = "",
                  repeat: str = "", parent_id: int = 0) -> dict:
        pri = 1 if priority is None else int(priority)   # 0 是合法优先级（P0），别被 or 吃掉
        self._run(
            "INSERT INTO today (day, text, sort, project_id, created, priority, est, note, repeat, parent_id) "
            "VALUES (?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM today WHERE day=?),?,?,?,?,?,?,?)",
            (day, text, day, int(project_id or 0), time.time(),
             pri, float(est or 0), note or "",
             repeat or "", int(parent_id or 0)),
            False,
        )
        return {"ok": True}

    def today_toggle(self, id_: int, done: int) -> dict:
        rows = self._run("SELECT * FROM today WHERE id=?", (id_,))
        if not rows:
            return {"ok": False, "error": "没有这条任务"}
        row = rows[0]
        self._run(
            "UPDATE today SET done=?, done_at=? WHERE id=?",
            (done, time.time() if done else None, id_), False,
        )
        # 重复任务：完成后在下一个周期自动重建一份新的
        if done and row.get("repeat") and not int(row.get("parent_id") or 0):
            nd = self._next_repeat_day(row["day"], row["repeat"])
            if nd:
                rp = row.get("priority")
                self.today_add(nd, row["text"], row.get("project_id") or 0,
                               1 if rp is None else int(rp), row.get("est") or 0,
                               "", row["repeat"], 0)
        # 父子联动：子任务全勾 → 父任务自动完成；取消一个 → 父任务自动取消
        pid = int(row.get("parent_id") or 0)
        if pid:
            n, ndone = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(done),0) FROM today WHERE parent_id=?", (pid,)
            ).fetchone()
            if n and ndone >= n:
                self._run("UPDATE today SET done=1, done_at=? WHERE id=? AND done=0",
                          (time.time(), pid), False)
            else:
                self._run("UPDATE today SET done=0, done_at=NULL WHERE id=?", (pid,), False)
        return {"ok": True}

    def _next_repeat_day(self, day: str, repeat: str) -> str:
        import datetime as _dt
        try:
            d = _dt.date.fromisoformat(day)
        except (ValueError, TypeError):
            return ""
        if repeat == "daily":
            return (d + _dt.timedelta(days=1)).isoformat()
        if repeat == "weekly":
            return (d + _dt.timedelta(days=7)).isoformat()
        if repeat == "monthly":
            m, y = d.month + 1, d.year
            if m > 12:
                m, y = 1, y + 1
            try:
                return d.replace(year=y, month=m).isoformat()
            except ValueError:  # 31 号落进没有 31 号的月份
                return _dt.date(y, m, 28).isoformat()
        return ""

    def today_del(self, id_: int) -> dict:
        # 连子任务一起删
        self._run("DELETE FROM today WHERE id=? OR parent_id=?", (id_, id_), False)
        return {"ok": True}

    def today_roll(self, old: str, new: str) -> dict:
        """把某天没做完的挪到另一天。"""
        self._run(
            "UPDATE today SET day=? WHERE day=? AND done=0", (new, old), False
        )
        return {"ok": True}

    def today_pending(self, day: str) -> list[dict]:
        """某天还没做完的事（用来提示「昨天有几件没勾」）。"""
        return self._run(
            "SELECT * FROM today WHERE day=? AND done=0 ORDER BY sort, id", (day,)
        )

    # ---- 任务进阶（优先级 / 子任务 / 重复 / 用时 / 番茄 / 批量 / 模板 / 统计）----

    def today_priority(self, id_: int, p: int) -> dict:
        self._run("UPDATE today SET priority=? WHERE id=?", (int(p), id_), False)
        return {"ok": True}

    def today_est(self, id_: int, est) -> dict:
        self._run("UPDATE today SET est=? WHERE id=?", (float(est or 0), id_), False)
        return {"ok": True}

    def today_note(self, id_: int, note: str) -> dict:
        self._run("UPDATE today SET note=? WHERE id=?", ((note or "").strip(), id_), False)
        return {"ok": True}

    def today_defer(self, id_: int, to_day: str = "") -> dict:
        """把任务（连子任务）推到另一天，默认明天。"""
        if not to_day:
            to_day = _tomorrow()
        self._run("UPDATE today SET day=? WHERE id=? OR parent_id=?",
                  (to_day, id_, id_), False)
        return {"ok": True, "to": to_day}

    def today_batch(self, ids, op: str) -> dict:
        if op not in ("done", "undone", "del", "defer"):
            return {"ok": False, "error": "不支持的操作"}
        ids = [int(i) for i in (ids or []) if i]
        for i in ids:
            if op == "done":
                self.today_toggle(i, 1)
            elif op == "undone":
                self.today_toggle(i, 0)
            elif op == "del":
                self.today_del(i)
            else:
                self.today_defer(i)
        return {"ok": True, "n": len(ids)}

    def today_pomo_start(self, today_id: int) -> dict:
        """对着某条任务开番茄；已有一条绑任务的番茄先自动结算。"""
        rows = self._run("SELECT * FROM today WHERE id=?", (today_id,))
        if not rows:
            return {"ok": False, "error": "没有这条任务"}
        r = self.pomodoro_running()
        if r and int(r.get("today_id") or 0):
            self.pomodoro_stop(r["id"])
        cur = self.conn.execute(
            "INSERT INTO pomodoro (project_id, task_id, title, today_id, started) VALUES (?,?,?,?,?)",
            (0, 0, rows[0]["text"], int(today_id), time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid, "started": time.time(), "today_id": int(today_id)}

    def today_pomo_stop(self) -> dict:
        """结算当前番茄；绑了任务的把分钟数记到任务 act 上。"""
        r = self.pomodoro_running()
        if not r:
            return {"ok": False, "error": "没有正在进行的番茄"}
        out = self.pomodoro_stop(r["id"])
        tid = int(r.get("today_id") or 0)
        return {"ok": True, "minutes": out.get("minutes", 0), "today_id": tid}

    def today_stats(self, days: int = 30) -> dict:
        """最近 N 天完成密度 + 完成连击。"""
        import datetime as _dt
        today = _dt.date.today()
        out = []
        for i in range(days - 1, -1, -1):
            d = (today - _dt.timedelta(days=i)).isoformat()
            n = self.conn.execute(
                "SELECT COUNT(*) FROM today WHERE day=? AND done=1", (d,)).fetchone()[0]
            out.append({"day": d, "n": n})
        streak, d = 0, today
        while True:
            n = self.conn.execute(
                "SELECT COUNT(*) FROM today WHERE day=? AND done=1", (d.isoformat(),)).fetchone()[0]
            if n:
                streak += 1
                d -= _dt.timedelta(days=1)
            elif d == today:
                d -= _dt.timedelta(days=1)  # 今天还没完成不算断
            else:
                break
        return {"streak": streak, "days": out}

    def today_tpl_list(self) -> list[dict]:
        return self._run("SELECT * FROM task_tpl ORDER BY id DESC")

    def today_tpl_save(self, name: str, items) -> dict:
        items = [i.strip() for i in (items or []) if isinstance(i, str) and i.strip()]
        self._run(
            "INSERT INTO task_tpl (name, items, created) VALUES (?,?,?)",
            ((name or "").strip() or "模板", json.dumps(items, ensure_ascii=False), time.time()),
            False,
        )
        return {"ok": True, "n": len(items)}

    def today_tpl_del(self, id_: int) -> dict:
        self._run("DELETE FROM task_tpl WHERE id=?", (id_,), False)
        return {"ok": True}

    def today_tpl_apply(self, id_: int, day: str) -> dict:
        rows = self._run("SELECT * FROM task_tpl WHERE id=?", (id_,))
        if not rows:
            return {"ok": False, "error": "没有这个模板"}
        try:
            items = json.loads(rows[0]["items"] or "[]")
        except (ValueError, TypeError):
            items = []
        for t in items:
            if isinstance(t, str) and t.strip():
                self.today_add(day, t.strip())
        return {"ok": True, "n": len(items)}

    def today_review(self, day: str) -> dict:
        """一键日回顾的原料：完成/未完/番茄/捕捉/日程/日志，一次给全。"""
        import datetime as _dt
        rows = self._run(
            "SELECT * FROM today WHERE day=? ORDER BY done, priority, sort, id", (day,))
        done = [r["text"] for r in rows if r["done"]]
        undone = [r["text"] for r in rows if not r["done"]]
        try:
            d0 = _dt.datetime.combine(_dt.date.fromisoformat(day), _dt.time.min).timestamp()
        except (ValueError, TypeError):
            d0 = 0
        d1 = d0 + 86400
        prow = self.conn.execute(
            "SELECT COALESCE(SUM(minutes),0), COUNT(*) FROM pomodoro "
            "WHERE ended IS NOT NULL AND started>=? AND started<?", (d0, d1)).fetchone()
        cap = self.conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE created>=? AND created<?", (d0, d1)).fetchone()[0]
        evs = self._run(
            "SELECT start, end, title FROM events WHERE day=? ORDER BY start", (day,))
        return {
            "day": day, "done": done, "undone": undone,
            "pomo_minutes": round(prow[0] or 0), "pomo_count": prow[1],
            "captures": cap, "events": evs, "daylog": self.daylog_get(day),
        }

    # ---- 今日什么事（按天一条的自由日志）----

    def daylog_get(self, day: str) -> str:
        r = self.conn.execute(
            "SELECT text FROM daylog WHERE day=?", (day,)
        ).fetchone()
        return r[0] if r else ""

    def daylog_save(self, day: str, text: str) -> dict:
        self._run(
            "INSERT INTO daylog (day, text, updated) VALUES (?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET text=excluded.text, updated=excluded.updated",
            (day, text, time.time()),
            False,
        )
        return {"ok": True}

    # ---- 生活专项：通用清单（设备 / 预算 / 收入共用一张表，靠 key 区分）----

    def list_items(self, key: str) -> list[dict]:
        return self._run(
            "SELECT id, fields, created FROM lists WHERE key=? ORDER BY id", (key,)
        )

    def list_add(self, key: str, fields: dict) -> dict:
        self._run(
            "INSERT INTO lists (key, fields, created) VALUES (?,?,?)",
            (key, json.dumps(fields, ensure_ascii=False), time.time()),
            False,
        )
        return {"ok": True}

    def list_del(self, id_: int) -> dict:
        self._run("DELETE FROM lists WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 房间布局 ----

    def room_list(self) -> list[dict]:
        return self._run(
            "SELECT id, name, updated FROM room_layouts ORDER BY id"
        )

    def room_get(self, rid: int) -> dict:
        rows = self._run("SELECT * FROM room_layouts WHERE id=?", (rid,))
        if not rows:
            return {}
        r = rows[0]
        r["data"] = json.loads(r.get("data") or "{}")
        return r

    def room_save(self, name: str, data: dict, rid: int = 0) -> dict:
        now = time.time()
        if rid:
            self._run(
                "UPDATE room_layouts SET name=?, data=?, updated=? WHERE id=?",
                (name, json.dumps(data, ensure_ascii=False), now, rid), False,
            )
            return {"ok": True, "id": rid}
        self._run(
            "INSERT INTO room_layouts (name, data, created, updated) VALUES (?,?,?,?)",
            (name, json.dumps(data, ensure_ascii=False), now, now), False,
        )
        return {"ok": True, "id": self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]}

    def room_del(self, rid: int) -> dict:
        self._run("DELETE FROM room_layouts WHERE id=?", (rid,), False)
        return {"ok": True}

    # ---- 剪贴板历史 ----

    def clip_add(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "空"}
        # 去重：和上一条一样就不重复存
        last = self._run("SELECT text FROM clip ORDER BY id DESC LIMIT 1")
        if last and last[0]["text"] == text:
            return {"ok": True, "dup": True}
        self._run("INSERT INTO clip (text, created) VALUES (?,?)", (text, time.time()), False)
        return {"ok": True}

    def clip_list(self, limit=200) -> list[dict]:
        return self._run("SELECT id, text, created FROM clip ORDER BY id DESC LIMIT ?", (limit,))

    def clip_del(self, cid: int) -> dict:
        self._run("DELETE FROM clip WHERE id=?", (cid,), False)
        return {"ok": True}

    def clip_clear(self) -> dict:
        self._run("DELETE FROM clip", (), False)
        return {"ok": True}

    # ---- 定时提醒 ----

    def rem_add(self, at: float, text: str) -> dict:
        cur = self.conn.execute(
            "INSERT INTO reminders (at, text, done, created) VALUES (?,?,0,?)",
            (at, (text or "").strip(), time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def rem_list(self) -> list[dict]:
        return self._run("SELECT * FROM reminders ORDER BY at")

    def rem_done(self, rid: int, done: int = 1) -> dict:
        self._run("UPDATE reminders SET done=? WHERE id=?", (done, rid), False)
        return {"ok": True}

    def rem_del(self, rid: int) -> dict:
        self._run("DELETE FROM reminders WHERE id=?", (rid,), False)
        return {"ok": True}

    # ---- 文件标签（只写元数据，不动文件）----

    def tag_add(self, path: str, tag: str) -> dict:
        tag = (tag or "").strip()
        if not tag or not path:
            return {"ok": False, "error": "空"}
        try:
            self._run("INSERT OR IGNORE INTO file_tags (path, tag) VALUES (?,?)", (path, tag), False)
        except sqlite3.IntegrityError:
            pass
        return {"ok": True}

    def tag_del(self, path: str, tag: str) -> dict:
        self._run("DELETE FROM file_tags WHERE path=? AND tag=?", (path, tag), False)
        return {"ok": True}

    def tags_all(self) -> list[dict]:
        return self._run("SELECT path, tag FROM file_tags ORDER BY id")

    def tags_distinct(self) -> list[dict]:
        return self._run(
            "SELECT tag, COUNT(*) AS n FROM file_tags GROUP BY tag ORDER BY n DESC, tag"
        )

    # ---- 文件收藏 / 打开记录（跨模块聚合）----

    def fav_toggle(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "空路径"}
        has = self._run("SELECT path FROM file_fav WHERE path=?", (path,))
        if has:
            self._run("DELETE FROM file_fav WHERE path=?", (path,), False)
            return {"ok": True, "fav": False}
        self._run("INSERT OR IGNORE INTO file_fav (path, created) VALUES (?,?)",
                  (path, time.time()), False)
        return {"ok": True, "fav": True}

    def fav_paths(self) -> list[dict]:
        return self._run("SELECT path, created FROM file_fav ORDER BY created DESC")

    def fav_set(self) -> set:
        try:
            return {r[0] for r in self.conn.execute("SELECT path FROM file_fav").fetchall()}
        except sqlite3.Error:
            return set()

    def open_log(self, path: str) -> dict:
        """记一次「打开」。同一文件多次打开只累加次数、刷新时间。"""
        if not path:
            return {"ok": False}
        self._run(
            "INSERT INTO file_open (path, opened, count) VALUES (?,?,1) "
            "ON CONFLICT(path) DO UPDATE SET opened=excluded.opened, count=count+1",
            (path, time.time()), False,
        )
        return {"ok": True}

    def open_recent(self, limit: int = 200) -> list[dict]:
        return self._run(
            "SELECT path, opened, count FROM file_open ORDER BY opened DESC LIMIT ?", (limit,)
        )

    def rename_path(self, old: str, new: str) -> dict:
        """文件改了名：收藏 / 打开记录 / 标签里的路径一起跟过去，别丢关联。"""
        for tbl in ("file_fav", "file_open", "file_tags"):
            try:
                self._run(f"UPDATE OR IGNORE {tbl} SET path=? WHERE path=?", (new, old), False)
            except sqlite3.Error:
                pass
        return {"ok": True}

    # ---- 日程 ----

    def events_list(self, month: str) -> list[dict]:
        """按月份取日程，month 形如 2026-09。重复日程会展开成多条。"""
        return self.events_range(month + "-01", month + "-31")

    def events_range(self, a: str, b: str) -> list[dict]:
        """取 [a,b] 内的日程。

        73 重复日程：库里只存一条原型，这里按规则把 [a,b] 内的每一次都摊出来，
        非首次的那几次带 virtual=1，前端据此提示「删这一次还是删全部」。
        """
        plain = self._run(
            "SELECT * FROM events WHERE COALESCE(repeat,'')='' AND day>=? AND day<=? "
            "ORDER BY day, start, id", (a, b))
        rep = self._run(
            "SELECT * FROM events WHERE COALESCE(repeat,'')<>'' AND day<=? "
            "AND (COALESCE(repeat_until,'')='' OR repeat_until>=?) "
            "ORDER BY day, start, id", (b, a))
        out = [{**ev, "occ": ev.get("day"), "base_day": ev.get("day"), "virtual": 0}
               for ev in plain]
        for ev in rep:
            for ds in expand_event(ev, a, b):
                out.append({**ev, "occ": ds, "day": ds, "base_day": ev.get("day"),
                            "virtual": 1 if ds != ev.get("day") else 0})
        out.sort(key=lambda r: (r.get("day") or "", r.get("start") or "", r.get("id") or 0))
        return out

    def event_save(self, id_: int | None, day: str, start: str, end: str,
                   title: str, note: str, source: str = "manual",
                   repeat: str = "", repeat_until: str = "", color: str = "",
                   remind_before: int = 0) -> dict:
        if not day or not title:
            return {"ok": False, "error": "日期和标题都要填"}
        rep = (repeat or "").strip()
        if rep not in REPEATS:
            rep = ""
        try:
            rb = int(remind_before or 0)
        except (TypeError, ValueError):
            rb = 0
        # 75 提醒双通道：日程也挂一条提醒（桌面通知由前端轮询 /api/reminders 出）
        old_rem = 0
        if id_:
            rows = self._run("SELECT reminder_id FROM events WHERE id=?", (id_,))
            old_rem = rows[0]["reminder_id"] if rows else 0
        if old_rem:
            self._run("DELETE FROM reminders WHERE id=?", (old_rem,), False)
        reminder_id = 0
        if rb > 0 and start:
            at = self._daystart_epoch(day, start) - rb * 60
            if at > time.time():
                reminder_id = self.rem_add(at, "日程提醒：" + title).get("id", 0)
        col = (color or "").strip()
        until = (repeat_until or "").strip()
        if id_:
            self._run(
                "UPDATE events SET day=?,start=?,end=?,title=?,note=?,source=?,repeat=?,"
                "repeat_until=?,color=?,remind_before=?,reminder_id=? WHERE id=?",
                (day, start, end, title, note, source, rep, until, col, rb,
                 reminder_id, id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO events (day,start,end,title,note,source,repeat,repeat_until,color,"
            "remind_before,reminder_id,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, start, end, title, note, source, rep, until, col, rb, reminder_id,
             time.time()))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def event_del(self, id_: int) -> dict:
        rows = self._run("SELECT reminder_id FROM events WHERE id=?", (int(id_),))
        rem = rows[0]["reminder_id"] if rows else 0
        if rem:
            self._run("DELETE FROM reminders WHERE id=?", (rem,), False)
        self._run("DELETE FROM events WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def event_exdate(self, id_: int, day: str) -> dict:
        """73 删掉重复日程里的某一次：记进 exdate，不动整条；删首次等于删整条。"""
        rows = self._run("SELECT day, exdate, COALESCE(repeat,'') AS repeat "
                         "FROM events WHERE id=?", (int(id_),))
        if not rows:
            return {"ok": False, "error": "没这条日程"}
        r = rows[0]
        base = r.get("day") or ""
        if not r.get("repeat") or day == base:
            return self.event_del(int(id_))
        ex = [x for x in (r.get("exdate") or "").split(",") if x]
        if day not in ex:
            ex.append(day)
        self._run("UPDATE events SET exdate=? WHERE id=?", (",".join(ex), int(id_)), False)
        return {"ok": True, "exdate": ",".join(ex)}

    def event_move(self, id_: int, occ: str, day: str, start: str = "",
                   end: str = "") -> dict:
        """72 拖拽改时间。重复日程拖某一次：把这一次排掉，另起一条独立日程。"""
        rows = self._run("SELECT * FROM events WHERE id=?", (int(id_),))
        if not rows:
            return {"ok": False, "error": "没这条日程"}
        ev = rows[0]
        base = ev.get("day") or ""
        occ = occ or base
        if not ev.get("repeat") or occ == base:
            self._run("UPDATE events SET day=?, start=?, end=? WHERE id=?",
                      (day, start or ev.get("start") or "", end or ev.get("end") or "",
                       int(id_)), False)
            return {"ok": True, "id": int(id_), "moved": "series"}
        self.event_exdate(int(id_), occ)
        new = self.event_save(None, day, start or ev.get("start") or "",
                              end or ev.get("end") or "", ev.get("title") or "",
                              ev.get("note") or "", ev.get("source") or "manual",
                              "", "", ev.get("color") or "", 0)
        return {"ok": True, "id": new.get("id"), "moved": "split", "from": occ}

    def today_events_map(self, day: str) -> list[dict]:
        """某天的日程 + 会议 + 到期任务，给今日页和纪要入口共用。"""
        out = self.events_range(day, day)
        for m in self._run("SELECT * FROM meetings WHERE day=? ORDER BY start, id", (day,)):
            out.append({**m, "occ": day, "base_day": day, "_m": 1, "virtual": 0})
        for t in self.tasks_due(day, day):
            out.append({**t, "occ": t.get("due"), "day": t.get("due"), "_t": 1})
        return out

    def events_stats(self, a: str, b: str) -> dict:
        """74 时长统计：日程 + 会议各占多少，按天拆开。"""
        def minutes(s: str, e: str) -> int:
            try:
                sh, sm = (int(x) for x in (s or "").split(":"))
                eh, em = (int(x) for x in (e or "").split(":"))
            except (ValueError, TypeError):
                return 0
            m = (eh * 60 + em) - (sh * 60 + sm)
            return m if m > 0 else 0

        evs = self.events_range(a, b)
        mts = self._run("SELECT * FROM meetings WHERE day>=? AND day<=? ORDER BY day", (a, b))
        by_day: dict[str, int] = {}
        ev_min = 0
        for ev in evs:
            m = minutes(ev.get("start"), ev.get("end"))
            ev_min += m
            k = ev.get("day") or ""
            by_day[k] = by_day.get(k, 0) + m
        mt_min = 0
        for mt in mts:
            m = minutes(mt.get("start"), mt.get("end"))
            mt_min += m
            k = mt.get("day") or ""
            by_day[k] = by_day.get(k, 0) + m
        return {"ok": True, "from": a, "to": b,
                "event_min": ev_min, "meet_min": mt_min, "total_min": ev_min + mt_min,
                "event_n": len(evs), "meet_n": len(mts),
                "days": [{"day": k, "min": v} for k, v in sorted(by_day.items()) if k]}

    def rem_due_unpushed(self, now: float) -> list[dict]:
        """75 还没推过连接器的到期提醒。"""
        return self._run(
            "SELECT * FROM reminders WHERE COALESCE(pushed,0)=0 AND COALESCE(done,0)=0 "
            "AND at<=? ORDER BY at", (now,))

    def rem_mark_pushed(self, rid: int) -> dict:
        self._run("UPDATE reminders SET pushed=1 WHERE id=?", (int(rid),), False)
        return {"ok": True}

    def event_done(self, id_: int, done: int) -> dict:
        self._run("UPDATE events SET done=? WHERE id=?", (done, id_), False)
        return {"ok": True}

    # ---- 会议（带会前提醒，提醒复用 reminders 表）----

    @staticmethod
    def _daystart_epoch(day: str, start: str) -> float:
        """把 'YYYY-MM-DD' + 'HH:MM' 转成本机 epoch 秒。解析不出返回 0。"""
        try:
            y, mo, d = (int(x) for x in day.split("-"))
            hh = mm = 0
            if start and ":" in start:
                p = start.split(":")
                hh = int(p[0])
                mm = int(p[1]) if len(p) > 1 else 0
            return datetime.datetime(y, mo, d, hh, mm).timestamp()
        except (ValueError, TypeError, AttributeError):
            return 0

    def meeting_save(self, id_: int | None, day: str, start: str, end: str,
                     title: str, location: str, link: str, attendees: str,
                     note: str, remind_before: int, source: str = "manual") -> dict:
        if not day or not title:
            return {"ok": False, "error": "日期和标题都要填"}
        try:
            rb = int(remind_before or 0)
        except (TypeError, ValueError):
            rb = 0
        # 旧提醒先清掉，保证一个会议对应一条提醒
        old_rem = 0
        if id_:
            rows = self._run("SELECT reminder_id FROM meetings WHERE id=?", (id_,))
            old_rem = rows[0]["reminder_id"] if rows else 0
        if old_rem:
            self._run("DELETE FROM reminders WHERE id=?", (old_rem,), False)
        # 重建会前提醒
        reminder_id = 0
        if rb > 0 and start:
            at = self._daystart_epoch(day, start) - rb * 60
            if at > time.time():
                rtxt = "会议提醒：" + title
                if location:
                    rtxt += "（地点：" + location + "）"
                if link:
                    rtxt += "  入会：" + link
                reminder_id = self.rem_add(at, rtxt).get("id", 0)
        if id_:
            self._run(
                "UPDATE meetings SET day=?,start=?,end=?,title=?,location=?,link=?,"
                "attendees=?,note=?,remind_before=?,reminder_id=?,source=? WHERE id=?",
                (day, start, end, title, location, link, attendees, note, rb,
                 reminder_id, source, id_), False,
            )
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO meetings (day,start,end,title,location,link,attendees,note,"
            "remind_before,reminder_id,source,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, start, end, title, location, link, attendees, note, rb,
             reminder_id, source, time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def meeting_list(self, month: str) -> list[dict]:
        return self._run(
            "SELECT * FROM meetings WHERE day LIKE ? ORDER BY day, start, id",
            (month + "%",),
        )

    def meeting_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM meetings WHERE id=?", (id_,))
        return rows[0] if rows else {}

    def meeting_del(self, id_: int) -> dict:
        rows = self._run("SELECT reminder_id FROM meetings WHERE id=?", (id_,))
        rem = rows[0]["reminder_id"] if rows else 0
        if rem:
            self._run("DELETE FROM reminders WHERE id=?", (rem,), False)
        self._run("DELETE FROM meetings WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 笔记 ----

    def notes_list(self) -> list[dict]:
        return self._run("SELECT * FROM notes ORDER BY updated DESC")

    def note_save(self, id_: int | None, title: str, body: str, tags: str) -> dict:
        now = time.time()
        if id_:
            self._run(
                "UPDATE notes SET title=?, body=?, tags=?, updated=? WHERE id=?",
                (title, body, tags, now, id_),
                False,
            )
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO notes (title, body, tags, created, updated) VALUES (?,?,?,?,?)",
            (title, body, tags, now, now),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def note_del(self, id_: int) -> dict:
        self._run("DELETE FROM notes WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 本地知识库 ----

    def kb_list(self) -> list[dict]:
        return self._run("SELECT * FROM kb ORDER BY updated DESC")

    def kb_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM kb WHERE id=?", (id_,))
        return rows[0] if rows else {}

    def kb_save(self, id_: int | None, title: str, body: str, tags: str,
                source: str = "manual", source_path: str = "") -> dict:
        if not title and not body:
            return {"ok": False, "error": "标题和正文不能都为空"}
        now = time.time()
        if id_:
            self._run(
                "UPDATE kb SET title=?, body=?, tags=?, source=?, source_path=?, updated=? WHERE id=?",
                (title, body, tags, source, source_path, now, id_), False,
            )
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO kb (title, body, tags, source, source_path, created, updated) "
            "VALUES (?,?,?,?,?,?,?)",
            (title, body, tags, source, source_path, now, now),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def kb_del(self, id_: int) -> dict:
        self._run("DELETE FROM kb WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- OpenClaw 运行记录（统一活动，区别于 claw 标签的 localStorage 历史）----

    def openclaw_log(self, task: str, reply: str, ok: int = 1, mode: str = "run",
                     agent: str = "", dur: float = 0, qid: int = 0) -> dict:
        self._run(
            "INSERT INTO openclaw_runs (ts, task, reply, ok, mode, agent, dur, qid) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), (task or "")[:2000], (reply or "")[:8000], int(ok), mode,
             (agent or "")[:80], float(dur or 0), int(qid or 0)),
            False,
        )
        return {"ok": True}

    def openclaw_recent(self, limit: int = 30) -> list[dict]:
        rows = self._run(
            "SELECT id, ts, task, reply, ok, mode, fav, agent, dur FROM openclaw_runs "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        for r in rows:
            r["reply"] = (r.get("reply") or "")[:240]
        return rows

    def openclaw_search(self, q: str, only: str = "all", limit: int = 50) -> list[dict]:
        """按关键词翻历史任务：任务名和结果正文都搜。only=task/reply 可缩小范围。"""
        q = (q or "").strip()
        like = "%" + q + "%"
        where = ""
        args: list = []
        if q:
            if only == "task":
                where = "WHERE task LIKE ?"
                args.append(like)
            elif only == "reply":
                where = "WHERE reply LIKE ?"
                args.append(like)
            else:
                where = "WHERE (task LIKE ? OR reply LIKE ?)"
                args += [like, like]
        args.append(int(limit))
        rows = self._run(
            "SELECT id, ts, task, reply, ok, mode, fav, agent, dur FROM openclaw_runs "
            + where + " ORDER BY id DESC LIMIT ?",
            tuple(args),
        )
        for r in rows:
            r["reply"] = (r.get("reply") or "")[:240]
        return rows

    def openclaw_fav(self, id_: int, on: int | None = None) -> dict:
        if on is None:
            cur = self._run("SELECT fav FROM openclaw_runs WHERE id=?", (int(id_),))
            if not cur:
                return {"ok": False, "error": "没这条记录"}
            on = 0 if cur[0].get("fav") else 1
        self._run("UPDATE openclaw_runs SET fav=? WHERE id=?", (int(on), int(id_)), False)
        return {"ok": True, "id": int(id_), "fav": bool(on)}

    def openclaw_favs(self, limit: int = 60) -> list[dict]:
        rows = self._run(
            "SELECT id, ts, task, reply, ok, mode, fav, agent, dur FROM openclaw_runs "
            "WHERE fav=1 ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        for r in rows:
            r["reply"] = (r.get("reply") or "")[:240]
        return rows

    def openclaw_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM openclaw_runs WHERE id=?", (int(id_),))
        return rows[0] if rows else {}

    def openclaw_stats(self, days: int = 30) -> dict:
        """成功率 / 平均 / P95 时长。时长优先用实际跑的秒数，旧记录按 0 跳过。"""
        since = time.time() - int(days) * 86400
        rows = self._run(
            "SELECT ok, dur FROM openclaw_runs WHERE ts >= ?", (since,))
        n = len(rows)
        if not n:
            return {"n": 0, "ok_n": 0, "fail_n": 0, "rate": 0,
                    "avg": 0, "p95": 0, "days": int(days), "slowest": 0}
        ok_n = sum(1 for r in rows if r.get("ok"))
        durs = sorted(float(r.get("dur") or 0) for r in rows)
        durs = [d for d in durs if d > 0]
        avg = sum(durs) / len(durs) if durs else 0
        p95 = durs[min(len(durs) - 1, int(len(durs) * 0.95))] if durs else 0
        return {
            "n": n, "ok_n": ok_n, "fail_n": n - ok_n,
            "rate": round(ok_n * 100.0 / n, 1),
            "avg": round(avg, 1), "p95": round(p95, 1),
            "slowest": round(durs[-1], 1) if durs else 0,
            "days": int(days),
        }

    # ---- 神经桥审计：每个动作留痕，谁批的、批没批、结果如何 ----

    def bridge_audit_add(self, action: str, payload: str, summary: str,
                         decision: str, actor: str = "", result: str = "") -> dict:
        self._run(
            "INSERT INTO bridge_audit (ts, action, payload, summary, decision, actor, result) "
            "VALUES (?,?,?,?,?,?,?)",
            (time.time(), (action or "")[:120], (payload or "")[:2000],
             (summary or "")[:400], decision, (actor or "")[:80], (result or "")[:1000]),
            False,
        )
        return {"ok": True}

    def bridge_audit_list(self, limit: int = 100, action: str = "") -> list[dict]:
        if action:
            return self._run(
                "SELECT * FROM bridge_audit WHERE action=? ORDER BY id DESC LIMIT ?",
                (action, int(limit)))
        return self._run("SELECT * FROM bridge_audit ORDER BY id DESC LIMIT ?", (int(limit),))

    # ---- 文档工作台：Markdown 正文 + 版本快照 + 全文搜 ----

    @staticmethod
    def _doc_snippet(md: str, n: int = 90) -> str:
        t = " ".join((md or "").split())
        return t[:n]

    def docs_list(self, q: str = "", limit: int = 200) -> list[dict]:
        """标题 + 正文一起搜；空 q 就是全部（最近的在前）。"""
        q = (q or "").strip()
        if q:
            like = "%" + q + "%"
            rows = self._run(
                "SELECT id, title, tags, fav, created, updated, md FROM docs "
                "WHERE title LIKE ? OR md LIKE ? OR tags LIKE ? ORDER BY updated DESC LIMIT ?",
                (like, like, like, int(limit)))
        else:
            rows = self._run(
                "SELECT id, title, tags, fav, created, updated, md FROM docs "
                "ORDER BY updated DESC LIMIT ?", (int(limit),))
        for r in rows:
            r["chars"] = len(r.get("md") or "")
            r["snippet"] = self._doc_snippet(r.get("md"))
            r.pop("md", None)
        return rows

    def docs_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM docs WHERE id=?", (int(id_),))
        if not rows:
            return {}
        r = rows[0]
        r["chars"] = len(r.get("md") or "")
        return r

    def docs_save(self, id_: int, title: str, md: str, note: str = "",
                  snap: bool = True) -> dict:
        """存正文；每次保存都落一个快照，于是「保存即版本」（可回滚）。"""
        now = time.time()
        title = (title or "").strip() or "未命名文档"
        md = md if isinstance(md, str) else ""
        cur = self._run("SELECT id FROM docs WHERE id=?", (int(id_ or 0),)) if id_ else []
        if cur:
            did = int(cur[0]["id"])
            self._run("UPDATE docs SET title=?, md=?, updated=? WHERE id=?",
                      (title, md, now, did), False)
            created = False
        else:
            self._run("INSERT INTO docs (title, md, tags, fav, created, updated) "
                      "VALUES (?,?,?,?,?,?)", (title, md, "", 0, now, now), False)
            did = int(self._run("SELECT last_insert_rowid() AS i")[0]["i"])
            created = True
        sid = 0
        if snap:
            sid = self._snap_add(did, md, note)
        return {"ok": True, "id": did, "created": created, "snap": sid,
                "chars": len(md), "updated": now}

    def _snap_add(self, doc_id: int, md: str, note: str = "") -> int:
        self._run("INSERT INTO doc_snaps (doc_id, ts, md, chars, note) VALUES (?,?,?,?,?)",
                  (int(doc_id), time.time(), md or "", len(md or ""),
                   (note or "")[:120]), False)
        return int(self._run("SELECT last_insert_rowid() AS i")[0]["i"])

    def docs_del(self, id_: int) -> dict:
        self._run("DELETE FROM docs WHERE id=?", (int(id_),), False)
        self._run("DELETE FROM doc_snaps WHERE doc_id=?", (int(id_),), False)
        return {"ok": True}

    def docs_fav(self, id_: int, on=None) -> dict:
        if on is None:
            cur = self._run("SELECT fav FROM docs WHERE id=?", (int(id_),))
            if not cur:
                return {"ok": False, "error": "没这篇文档"}
            on = 0 if cur[0].get("fav") else 1
        self._run("UPDATE docs SET fav=? WHERE id=?", (int(on), int(id_)), False)
        return {"ok": True, "id": int(id_), "fav": bool(on)}

    def docs_snaps(self, doc_id: int, limit: int = 50) -> list[dict]:
        return self._run(
            "SELECT id, doc_id, ts, chars, note FROM doc_snaps WHERE doc_id=? "
            "ORDER BY id DESC LIMIT ?", (int(doc_id), int(limit)))

    def docs_snap_get(self, sid: int) -> dict:
        rows = self._run("SELECT * FROM doc_snaps WHERE id=?", (int(sid),))
        return rows[0] if rows else {}

    def docs_restore(self, doc_id: int, sid: int) -> dict:
        """回滚到某个快照：先把当前正文存成新快照（免得回滚本身把现在弄丢），再覆盖。"""
        snap = self.docs_snap_get(sid)
        if not snap or int(snap.get("doc_id") or 0) != int(doc_id):
            return {"ok": False, "error": "没这个快照"}
        cur = self.docs_get(doc_id)
        if not cur:
            return {"ok": False, "error": "没这篇文档"}
        self._snap_add(doc_id, cur.get("md") or "", "回滚前的自动备份")
        self._run("UPDATE docs SET md=?, updated=? WHERE id=?",
                  (snap.get("md") or "", time.time(), int(doc_id)), False)
        return {"ok": True, "chars": len(snap.get("md") or ""),
                "restored_from": int(sid)}

    # ---- G 域：邮件（收件规则 / 本地打标 / 正文缓存 / 草稿 / 发件队列）----

    def mail_rules_list(self) -> list[dict]:
        return self._run("SELECT * FROM mail_rules ORDER BY id")

    def mail_rule_save(self, id_: int, name: str, field: str, contains: str,
                       tag: str) -> dict:
        field = field if field in ("from", "subject", "any") else "from"
        if id_:
            self._run("UPDATE mail_rules SET name=?, field=?, contains=?, tag=? WHERE id=?",
                      (name, field, contains, tag, int(id_)), False)
            return {"ok": True, "id": int(id_)}
        self._run("INSERT INTO mail_rules (name, field, contains, tag, created) "
                  "VALUES (?,?,?,?,?)", (name, field, contains, tag, time.time()), False)
        return {"ok": True, "id": int(self._run("SELECT last_insert_rowid() AS i")[0]["i"])}

    def mail_rule_del(self, id_: int) -> dict:
        self._run("DELETE FROM mail_rules WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def mail_meta_map(self, acct: str, uids: list[str]) -> dict:
        """一次把这一屏邮件的本地标记查出来（标签 / 星标）。"""
        if not uids:
            return {}
        marks = ",".join("?" * len(uids))
        rows = self._run(
            f"SELECT uid, tags, starred FROM mail_meta WHERE acct=? AND uid IN ({marks})",
            tuple([acct] + [str(x) for x in uids]))
        return {r["uid"]: {"tags": r.get("tags") or "", "starred": int(r.get("starred") or 0)}
                for r in rows}

    def mail_tag(self, acct: str, uid: str, tags: str) -> dict:
        self._run(
            "INSERT INTO mail_meta (acct, uid, tags, created) VALUES (?,?,?,?) "
            "ON CONFLICT(acct, uid) DO UPDATE SET tags=excluded.tags",
            (acct, str(uid), tags or "", time.time()), False)
        return {"ok": True, "tags": tags or ""}

    def mail_star(self, acct: str, uid: str, on=None) -> dict:
        cur = self._run("SELECT starred FROM mail_meta WHERE acct=? AND uid=?",
                        (acct, str(uid)))
        if on is None:
            on = 0 if (cur and cur[0].get("starred")) else 1
        self._run(
            "INSERT INTO mail_meta (acct, uid, starred, created) VALUES (?,?,?,?) "
            "ON CONFLICT(acct, uid) DO UPDATE SET starred=excluded.starred",
            (acct, str(uid), int(on), time.time()), False)
        return {"ok": True, "starred": bool(on)}

    def mail_body_put(self, acct: str, uid: str, subject: str, mfrom: str,
                      mdate: str, body: str) -> dict:
        self._run(
            "INSERT INTO mail_body (acct, uid, subject, mfrom, mdate, body, created) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(acct, uid) DO UPDATE SET subject=excluded.subject, "
            "mfrom=excluded.mfrom, mdate=excluded.mdate, body=excluded.body",
            (acct, str(uid), subject or "", mfrom or "", mdate or "",
             (body or "")[:200000], time.time()), False)
        return {"ok": True}

    def mail_body_search(self, q: str, limit: int = 50) -> list[dict]:
        """67 正文搜索：搜本地缓存过的邮件正文（离线也能搜）。"""
        q = (q or "").strip()
        if not q:
            return []
        like = "%" + q + "%"
        rows = self._run(
            "SELECT uid, acct, subject, mfrom, mdate, created, body FROM mail_body "
            "WHERE subject LIKE ? OR mfrom LIKE ? OR body LIKE ? "
            "ORDER BY created DESC LIMIT ?", (like, like, like, int(limit)))
        for r in rows:
            b = r.pop("body", "") or ""
            i = b.find(q)
            if i < 0:
                r["snippet"] = b[:120]
            else:
                r["snippet"] = ("…" if i > 30 else "") + b[max(0, i - 30):i + 90]
        return rows

    def mail_body_count(self) -> int:
        return int(self._run("SELECT COUNT(*) AS n FROM mail_body")[0]["n"])

    def mail_drafts(self) -> list[dict]:
        return self._run("SELECT * FROM mail_draft ORDER BY updated DESC LIMIT 200")

    def mail_draft_save(self, id_: int, acct: str, to: str, subject: str,
                        body: str) -> dict:
        now = time.time()
        if id_:
            self._run("UPDATE mail_draft SET mto=?, subject=?, body=?, updated=? WHERE id=?",
                      (to or "", subject or "", body or "", now, int(id_)), False)
            return {"ok": True, "id": int(id_)}
        self._run("INSERT INTO mail_draft (acct, mto, subject, body, created, updated) "
                  "VALUES (?,?,?,?,?,?)", (acct, to or "", subject or "", body or "", now, now),
                  False)
        return {"ok": True, "id": int(self._run("SELECT last_insert_rowid() AS i")[0]["i"])}

    def mail_draft_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM mail_draft WHERE id=?", (int(id_),))
        return rows[0] if rows else {}

    def mail_draft_del(self, id_: int) -> dict:
        self._run("DELETE FROM mail_draft WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def mail_outbox_add(self, acct: str, to: str, subject: str, body: str,
                        at: float = 0, status: str = "pending") -> dict:
        now = time.time()
        self._run(
            "INSERT INTO mail_outbox (acct, mto, subject, body, at, status, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (acct, to or "", subject or "", body or "", float(at or 0), status, now), False)
        return {"ok": True, "id": int(self._run("SELECT last_insert_rowid() AS i")[0]["i"])}

    def mail_outbox_list(self, limit: int = 100) -> list[dict]:
        rows = self._run("SELECT * FROM mail_outbox ORDER BY id DESC LIMIT ?", (int(limit),))
        for r in rows:
            r.pop("body", None)
        return rows

    def mail_outbox_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM mail_outbox WHERE id=?", (int(id_),))
        return rows[0] if rows else {}

    def mail_outbox_due(self, now: float) -> list[dict]:
        return self._run(
            "SELECT * FROM mail_outbox WHERE status='pending' AND at<=? ORDER BY at", (now,))

    def mail_outbox_mark(self, id_: int, status: str, error: str = "") -> dict:
        self._run("UPDATE mail_outbox SET status=?, error=?, sent=? WHERE id=?",
                  (status, (error or "")[:600], time.time(), int(id_)), False)
        return {"ok": True}

    def mail_outbox_cancel(self, id_: int) -> dict:
        self._run("UPDATE mail_outbox SET status='canceled' WHERE id=? AND status='pending'",
                  (int(id_),), False)
        return {"ok": True}

    def mail_outbox_pending(self) -> int:
        return int(self._run(
            "SELECT COUNT(*) AS n FROM mail_outbox WHERE status='pending'")[0]["n"])

    # ---- 连接器推送日志：每次推送留痕，成功失败都可查 ----

    def connector_push_log(self, ctype: str, name: str, title: str, ok: bool, error: str = "") -> dict:
        self._run(
            "INSERT INTO connector_log (ts, type, name, title, ok, error) VALUES (?,?,?,?,?,?)",
            (time.time(), ctype or "", name or "", (title or "")[:200], 1 if ok else 0, (error or "")[:500]),
            False,
        )
        return {"ok": True}

    def connector_push_recent(self, limit: int = 50) -> list[dict]:
        return self._run(
            "SELECT id, ts, type, name, title, ok, error FROM connector_log "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )

    # ---- 神经桥：OpenClaw 提交的工作台写操作，先入待审队列，用户确认后才执行 ----
    def bridge_enqueue(self, action: str, payload: dict) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO bridge_pending (ts, action, payload, status) VALUES (?,?,?,?)",
                (time.time(), action, json.dumps(payload, ensure_ascii=False), "pending"),
            )
            self.conn.commit()
            return cur.lastrowid

    def bridge_pending_list(self) -> list[dict]:
        rows = self._run(
            "SELECT id, ts, action, payload, status, result FROM bridge_pending "
            "WHERE status='pending' ORDER BY id DESC"
        )
        for r in rows:
            try:
                r["payload"] = json.loads(r.get("payload") or "{}")
            except Exception:
                r["payload"] = {}
        return rows

    def bridge_get(self, id_: int) -> dict | None:
        rows = self._run("SELECT * FROM bridge_pending WHERE id=?", (id_,))
        return rows[0] if rows else None

    def bridge_resolve(self, id_: int, status: str, result: str = "") -> dict:
        self._run(
            "UPDATE bridge_pending SET status=?, result=? WHERE id=?",
            (status, (result or "")[:2000], id_),
            False,
        )
        return {"ok": True}

    # ---- 链接 ----

    def links_list(self) -> list[dict]:
        return self._run("SELECT * FROM links ORDER BY id DESC")

    def link_add(self, title: str, url: str, tags: str) -> dict:
        self._run(
            "INSERT INTO links (title, url, tags, created) VALUES (?,?,?,?)",
            (title, url, tags, time.time()),
            False,
        )
        return {"ok": True}

    def link_del(self, id_: int) -> dict:
        self._run("DELETE FROM links WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 项目 ----

    def projects_list(self) -> list[dict]:
        return self._run("SELECT * FROM projects ORDER BY id")

    def project_save(self, id_: int | None, name: str, status: str, next_step: str) -> dict:
        now = time.time()
        if id_:
            self._run(
                "UPDATE projects SET name=?, status=?, next_step=?, updated=? WHERE id=?",
                (name, status, next_step, now, id_),
                False,
            )
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO projects (name, status, next_step, updated) VALUES (?,?,?,?)",
            (name, status, next_step, now),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def project_del(self, id_: int) -> dict:
        self._run("DELETE FROM projects WHERE id=?", (id_,), False)
        self._run("DELETE FROM tasks WHERE project_id=?", (id_,), False)
        self._run("DELETE FROM plog WHERE project_id=?", (id_,), False)
        return {"ok": True}

    def projects_board(self) -> list[dict]:
        """项目卡片 + 任务进度 + 累计番茄分钟，一次给全。"""
        rows = self._run("SELECT * FROM projects ORDER BY id")
        for p in rows:
            pid = p["id"]
            p["n_task"] = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id=?", (pid,)).fetchone()[0]
            p["n_done"] = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id=? AND state='已完成'",
                (pid,)).fetchone()[0]
            p["n_doing"] = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id=? AND state='在做'",
                (pid,)).fetchone()[0]
            p["mins"] = round(self.conn.execute(
                "SELECT COALESCE(SUM(minutes),0) FROM pomodoro WHERE project_id=?",
                (pid,)).fetchone()[0] or 0)
        return rows

    # ---- 任务看板 ----

    def tasks_list(self, project_id: int = 0) -> list[dict]:
        if project_id:
            return self._run(
                "SELECT * FROM tasks WHERE project_id=? ORDER BY sort, id", (project_id,))
        return self._run("SELECT * FROM tasks ORDER BY project_id, sort, id")

    def task_save(self, id_: int | None, project_id: int, title: str, state: str,
                  due: str = "") -> dict:
        if not title:
            return {"ok": False, "error": "任务名不能为空"}
        if id_:
            self._run("UPDATE tasks SET project_id=?, title=?, state=?, due=? WHERE id=?",
                      (int(project_id or 0), title, state or "待办", due or "", id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO tasks (project_id, title, state, due, sort, created) "
            "VALUES (?,?,?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE project_id=?),?)",
            (int(project_id or 0), title, state or "待办", due or "",
             int(project_id or 0), time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def task_state(self, id_: int, state: str) -> dict:
        now = time.time() if state == "已完成" else None
        self._run("UPDATE tasks SET state=?, done_at=COALESCE(?, done_at) WHERE id=?",
                  (state, now, id_), False)
        return {"ok": True}

    def task_due(self, id_: int, due: str) -> dict:
        self._run("UPDATE tasks SET due=? WHERE id=?", (due or "", id_), False)
        return {"ok": True}

    def tasks_due(self, a: str, b: str) -> list[dict]:
        """某段日期内到期的未完成任务（日历要把它们画上去）。"""
        return self._run(
            "SELECT t.*, COALESCE(p.name,'') AS project FROM tasks t "
            "LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.due<>'' AND t.due IS NOT NULL AND t.due>=? AND t.due<=? "
            "AND t.state<>'已完成' ORDER BY t.due, t.id", (a, b))

    def task_del(self, id_: int) -> dict:
        self._run("DELETE FROM tasks WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 番茄钟 ----

    def pomodoro_start(self, project_id: int, task_id: int, title: str, today_id: int = 0) -> dict:
        cur = self.conn.execute(
            "INSERT INTO pomodoro (project_id, task_id, title, today_id, started) VALUES (?,?,?,?,?)",
            (int(project_id or 0), int(task_id or 0), title or "",
             int(today_id or 0), time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid, "started": time.time()}

    def pomodoro_stop(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM pomodoro WHERE id=?", (id_,))
        if not rows:
            return {"ok": False, "error": "没有这条记录"}
        mins = (time.time() - (rows[0]["started"] or time.time())) / 60.0
        self._run("UPDATE pomodoro SET ended=?, minutes=? WHERE id=?",
                  (time.time(), round(mins, 1), id_), False)
        # 绑了任务的番茄：时长直接记到任务的「实际用时」上
        tid = int(rows[0].get("today_id") or 0)
        if tid:
            self._run("UPDATE today SET act=COALESCE(act,0)+? WHERE id=?",
                      (round(mins, 1), tid), False)
        return {"ok": True, "minutes": round(mins, 1)}

    def pomodoro_running(self) -> dict | None:
        rows = self._run(
            "SELECT * FROM pomodoro WHERE ended IS NULL ORDER BY id DESC LIMIT 1")
        return rows[0] if rows else None

    def pomodoro_list(self, limit: int = 30) -> list[dict]:
        return self._run(
            "SELECT m.*, COALESCE(p.name,'') AS project FROM pomodoro m "
            "LEFT JOIN projects p ON p.id=m.project_id "
            "WHERE m.ended IS NOT NULL ORDER BY m.id DESC LIMIT ?", (limit,))

    def pomodoro_today(self) -> dict:
        import datetime as _dt
        day0 = _dt.datetime.combine(_dt.date.today(), _dt.time.min).timestamp()
        mins = self.conn.execute(
            "SELECT COALESCE(SUM(minutes),0) FROM pomodoro WHERE ended IS NOT NULL AND started>=?",
            (day0,)).fetchone()[0] or 0
        n = self.conn.execute(
            "SELECT COUNT(*) FROM pomodoro WHERE ended IS NOT NULL AND started>=?",
            (day0,)).fetchone()[0]
        return {"minutes": round(mins), "count": n}

    # ---- 迭代记录 / 里程碑 ----

    def plog_list(self, project_id: int = 0, limit: int = 200) -> list[dict]:
        if project_id:
            return self._run(
                "SELECT * FROM plog WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (project_id, limit))
        return self._run("SELECT * FROM plog ORDER BY id DESC LIMIT ?", (limit,))

    def plog_add(self, project_id: int, text: str, kind: str = "log") -> dict:
        if not text:
            return {"ok": False, "error": "内容不能为空"}
        self._run("INSERT INTO plog (project_id, kind, text, created) VALUES (?,?,?,?)",
                  (int(project_id or 0), kind or "log", text, time.time()), False)
        return {"ok": True}

    def plog_del(self, id_: int) -> dict:
        self._run("DELETE FROM plog WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 对话 ----

    def chat_save(self, title: str, model: str, messages: list,
                  id_: int | None = None, sys_: str = "") -> dict:
        """有 id 就更新同一条对话，没有才新建 —— 否则每轮都存会刷出一堆重复历史。"""
        import json
        blob = json.dumps(messages, ensure_ascii=False)
        if id_:
            self._run("UPDATE chats SET title=?, model=?, messages=?, sys=? WHERE id=?",
                      (title, model, blob, sys_ or "", id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO chats (title, model, created, messages, sys) VALUES (?,?,?,?,?)",
            (title, model, time.time(), blob, sys_ or ""),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def chat_list(self) -> list[dict]:
        rows = self._run("SELECT id, title, model, created, sys FROM chats ORDER BY id DESC LIMIT 100")
        return rows

    def chat_get(self, id_: int) -> dict:
        import json
        rows = self._run("SELECT * FROM chats WHERE id=?", (id_,))
        if not rows:
            return {}
        r = rows[0]
        try:
            r["messages"] = json.loads(r["messages"])
        except (json.JSONDecodeError, TypeError):
            r["messages"] = []
        return r

    # ---- Prompt 库 ----

    def prompts_list(self) -> list[dict]:
        return self._run("SELECT * FROM prompts ORDER BY id DESC LIMIT 200")

    def prompt_save(self, id_: int | None, title: str, body: str, tags: str) -> dict:
        if not title or not body:
            return {"ok": False, "error": "标题和内容都要填"}
        if id_:
            self._run("UPDATE prompts SET title=?, body=?, tags=? WHERE id=?",
                      (title, body, tags, id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO prompts (title, body, tags, created) VALUES (?,?,?,?)",
            (title, body, tags, time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def prompt_del(self, id_: int) -> dict:
        self._run("DELETE FROM prompts WHERE id=?", (id_,), False)
        return {"ok": True}

    # ---- 备份 ----

    BACKUP_TABLES = ("inbox", "today", "notes", "links", "projects", "chats",
                     "events", "tasks", "pomodoro", "plog", "prompts",
                     "habits", "checkins", "kv", "daylog", "lists", "room_layouts",
                     "clip", "reminders", "file_tags", "kb")

    def export_all(self) -> dict:
        """把所有业务表倒成可 JSON 化的字典 —— 备份和搬家都靠它。"""
        out = {"v": 1, "at": time.time(), "tables": {}}
        for t in self.BACKUP_TABLES:
            try:
                out["tables"][t] = self._run(f"SELECT * FROM {t}")
            except sqlite3.OperationalError:
                continue  # 表还没建（老库）
        return out

    def import_all(self, data: dict, mode: str = "merge") -> dict:
        """把备份导回来。mode=merge 追加（默认，安全）；mode=replace 先清空再灌。"""
        tables = (data or {}).get("tables") or {}
        if not tables:
            return {"ok": False, "error": "文件里没有数据"}
        done = {}
        for t, rows in tables.items():
            if t not in self.BACKUP_TABLES or not isinstance(rows, list):
                continue
            try:
                if mode == "replace":
                    self._run(f"DELETE FROM {t}", (), False)
                n = 0
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    # 保留 id：INSERT OR REPLACE 按主键覆盖，
                    # 同一份备份导两次是幂等的，不会把数据翻倍
                    cols = [c for c in r.keys()]
                    qs = ",".join("?" * len(cols))
                    sql = f"INSERT OR REPLACE INTO {t} ({','.join(cols)}) VALUES ({qs})"
                    try:
                        self._run(sql, [r[c] for c in cols], False)
                        n += 1
                    except sqlite3.Error:
                        continue
                done[t] = n
            except sqlite3.OperationalError:
                continue
        return {"ok": True, "imported": done, "mode": mode}

    # ---- 习惯打卡 ----

    def habits_list(self) -> list[dict]:
        rows = self._run("SELECT * FROM habits ORDER BY sort, id")
        for h in rows:
            h["done_today"] = self.conn.execute(
                "SELECT COUNT(*) FROM checkins WHERE habit_id=? AND day=?",
                (h["id"], _today())).fetchone()[0]
            h["streak"] = self._streak(h["id"])
        return rows

    def habit_save(self, id_: int | None, name: str, note: str) -> dict:
        if not name:
            return {"ok": False, "error": "习惯名不能为空"}
        if id_:
            self._run("UPDATE habits SET name=?, note=? WHERE id=?", (name, note, id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO habits (name, note, sort, created) "
            "VALUES (?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM habits),?)",
            (name, note, time.time()))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def habit_del(self, id_: int) -> dict:
        self._run("DELETE FROM habits WHERE id=?", (id_,), False)
        self._run("DELETE FROM checkins WHERE habit_id=?", (id_,), False)
        return {"ok": True}

    def habit_toggle(self, id_: int, day: str) -> dict:
        ex = self._run("SELECT id FROM checkins WHERE habit_id=? AND day=?", (id_, day))
        if ex:
            self._run("DELETE FROM checkins WHERE id=?", (ex[0]["id"],), False)
            return {"ok": True, "on": False, "streak": self._streak(id_)}
        self._run("INSERT INTO checkins (habit_id, day, created) VALUES (?,?,?)",
                  (id_, day, time.time()), False)
        return {"ok": True, "on": True, "streak": self._streak(id_)}

    def _streak(self, habit_id: int) -> int:
        """连续打卡天数：从今天（或昨天）往回数。"""
        import datetime as _dt
        days = {r["day"] for r in self._run(
            "SELECT day FROM checkins WHERE habit_id=?", (habit_id,))}
        if not days:
            return 0
        d = _dt.date.today()
        if d.isoformat() not in days:
            d -= _dt.timedelta(days=1)      # 今天还没打，从昨天算起
            if d.isoformat() not in days:
                return 0
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= _dt.timedelta(days=1)
        return n

    # ---- 键值（存 UI 状态等） ----

    def kv_get(self, k: str, default=""):
        rows = self._run("SELECT v FROM kv WHERE k=?", (k,))
        return rows[0]["v"] if rows else default

    def kv_set(self, k: str, v) -> dict:
        self._run("INSERT OR REPLACE INTO kv (k,v) VALUES (?,?)", (k, str(v)), False)
        return {"ok": True}

    def counts(self) -> dict:
        out = {}
        for t in ("inbox", "today", "notes", "links", "projects", "chats", "events", "meetings", "tasks", "habits", "kb"):
            out[t] = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out["today_undone"] = self.conn.execute(
            "SELECT COUNT(*) FROM today WHERE done=0 AND day=?", (_today(),)).fetchone()[0]
        return out
