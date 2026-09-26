"""工作台数据层：除文件索引外的所有业务数据，全部落本机 SQLite。"""

from __future__ import annotations

import os
import json
import sqlite3
import threading
import time
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
"""

# 老库加列：新库没有这些列时补上，已存在就忽略
ALTERS = [
    "ALTER TABLE today ADD COLUMN project_id INTEGER DEFAULT 0",
    "ALTER TABLE today ADD COLUMN created REAL",
    "ALTER TABLE projects ADD COLUMN note TEXT",
    "ALTER TABLE tasks ADD COLUMN due TEXT",
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
        return self._run(
            "SELECT t.*, COALESCE(p.name,'') AS project FROM today t "
            "LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.day=? ORDER BY t.sort, t.id", (day,)
        )

    def today_add(self, day: str, text: str, project_id: int = 0) -> dict:
        self._run(
            "INSERT INTO today (day, text, sort, project_id, created) "
            "VALUES (?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM today WHERE day=?),?,?)",
            (day, text, day, int(project_id or 0), time.time()),
            False,
        )
        return {"ok": True}

    def today_toggle(self, id_: int, done: int) -> dict:
        self._run("UPDATE today SET done=? WHERE id=?", (done, id_), False)
        return {"ok": True}

    def today_del(self, id_: int) -> dict:
        self._run("DELETE FROM today WHERE id=?", (id_,), False)
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

    # ---- 日程 ----

    def events_list(self, month: str) -> list[dict]:
        """按月份取日程，month 形如 2026-09。"""
        return self._run(
            "SELECT * FROM events WHERE day LIKE ? ORDER BY day, start, id",
            (month + "%",),
        )

    def events_range(self, a: str, b: str) -> list[dict]:
        return self._run(
            "SELECT * FROM events WHERE day>=? AND day<=? ORDER BY day, start, id",
            (a, b),
        )

    def event_save(self, id_: int | None, day: str, start: str, end: str,
                   title: str, note: str, source: str = "manual") -> dict:
        if not day or not title:
            return {"ok": False, "error": "日期和标题都要填"}
        if id_:
            self._run(
                "UPDATE events SET day=?, start=?, end=?, title=?, note=?, source=? WHERE id=?",
                (day, start, end, title, note, source, id_),
                False,
            )
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO events (day, start, end, title, note, source, created) VALUES (?,?,?,?,?,?,?)",
            (day, start, end, title, note, source, time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def event_del(self, id_: int) -> dict:
        self._run("DELETE FROM events WHERE id=?", (id_,), False)
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

    def openclaw_log(self, task: str, reply: str, ok: int = 1, mode: str = "run") -> dict:
        self._run(
            "INSERT INTO openclaw_runs (ts, task, reply, ok, mode) VALUES (?,?,?,?,?)",
            (time.time(), (task or "")[:2000], (reply or "")[:8000], int(ok), mode),
            False,
        )
        return {"ok": True}

    def openclaw_recent(self, limit: int = 30) -> list[dict]:
        rows = self._run(
            "SELECT id, ts, task, reply, ok, mode FROM openclaw_runs "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        for r in rows:
            r["reply"] = (r.get("reply") or "")[:240]
        return rows

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

    def pomodoro_start(self, project_id: int, task_id: int, title: str) -> dict:
        cur = self.conn.execute(
            "INSERT INTO pomodoro (project_id, task_id, title, started) VALUES (?,?,?,?)",
            (int(project_id or 0), int(task_id or 0), title or "", time.time()),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid, "started": time.time()}

    def pomodoro_stop(self, id_: int) -> dict:
        rows = self._run("SELECT started FROM pomodoro WHERE id=?", (id_,))
        if not rows:
            return {"ok": False, "error": "没有这条记录"}
        mins = (time.time() - (rows[0]["started"] or time.time())) / 60.0
        self._run("UPDATE pomodoro SET ended=?, minutes=? WHERE id=?",
                  (time.time(), round(mins, 1), id_), False)
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

    def chat_save(self, title: str, model: str, messages: list, id_: int | None = None) -> dict:
        """有 id 就更新同一条对话，没有才新建 —— 否则每轮都存会刷出一堆重复历史。"""
        import json
        blob = json.dumps(messages, ensure_ascii=False)
        if id_:
            self._run("UPDATE chats SET title=?, model=?, messages=? WHERE id=?",
                      (title, model, blob, id_), False)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO chats (title, model, created, messages) VALUES (?,?,?,?)",
            (title, model, time.time(), blob),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def chat_list(self) -> list[dict]:
        rows = self._run("SELECT id, title, model, created FROM chats ORDER BY id DESC LIMIT 100")
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
        return out
