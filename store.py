"""工作台数据层：除文件索引外的所有业务数据，全部落本机 SQLite。"""

from __future__ import annotations

import os
import json
import re
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
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER DEFAULT 0,
    title TEXT,
    day TEXT DEFAULT '',
    pct INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    sort INTEGER DEFAULT 0,
    created REAL
);
-- 87 全文检索：自建倒排索引
-- 不用 FTS5 的默认分词器 —— 它把一整串中文当成一个 token（unicode61），
-- 「怎么备份」搜不到「备份」；trigram 又要至少 3 个字。所以自己做
-- 「ASCII 词 + 中文单字 + 中文二元组」的倒排，2 个字的中文词也能命中。
CREATE TABLE IF NOT EXISTS kb_index (
    kb_id INTEGER,
    term TEXT
);
CREATE INDEX IF NOT EXISTS kb_index_term ON kb_index(term);
-- 88 双链：[[标题]] 解析出来的有向边（存标题，另存解析到的 id 便于反查）
CREATE TABLE IF NOT EXISTS kb_links (
    src_id INTEGER,
    dst_title TEXT,
    dst_id INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS kb_links_src ON kb_links(src_id);
CREATE INDEX IF NOT EXISTS kb_links_dst ON kb_links(dst_id);
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
-- K 域：生活（95-104）
-- 95 记账：收支流水（kind 支出/收入），分类汇总与月度对比都从这张表算
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT,
    kind TEXT DEFAULT '支出',
    amount REAL DEFAULT 0,
    category TEXT DEFAULT '',
    note TEXT,
    created REAL
);
CREATE INDEX IF NOT EXISTS ledger_day ON ledger(day);
-- 97 设备台账 / 99 充电区：一台设备一条，charge 就是充电状态
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    kind TEXT DEFAULT '',
    zone TEXT DEFAULT '',
    bought TEXT DEFAULT '',
    warranty INTEGER DEFAULT 0,
    price REAL DEFAULT 0,
    charge TEXT DEFAULT '',
    note TEXT,
    created REAL
);
-- 100 网络拓扑：设备-交换机-端口，parent 指向上游
CREATE TABLE IF NOT EXISTS net_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    kind TEXT DEFAULT '',
    parent INTEGER DEFAULT 0,
    port TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    note TEXT,
    created REAL
);
-- 101 采购清单：想买 / 比价 / 已购
CREATE TABLE IF NOT EXISTS wishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price REAL DEFAULT 0,
    shop TEXT DEFAULT '',
    url TEXT DEFAULT '',
    priority INTEGER DEFAULT 2,
    status TEXT DEFAULT '想要',
    bought_at TEXT DEFAULT '',
    note TEXT,
    created REAL
);
-- 104 体重简记：一天最多一条，同天再记就覆盖
CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT,
    kg REAL DEFAULT 0,
    note TEXT,
    created REAL
);
CREATE INDEX IF NOT EXISTS weights_day ON weights(day);

-- L 域：系统工具（105-114）
CREATE TABLE IF NOT EXISTS crons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    kind TEXT DEFAULT 'cmd',      -- cmd / claw
    payload TEXT,                 -- 命令或给 OpenClaw 的任务
    sched TEXT,                   -- HH:MM / every:N / every:Nh / 5 段 cron
    enabled INTEGER DEFAULT 1,
    notify INTEGER DEFAULT 0,     -- 跑完把结果推到连接器
    last_run REAL,
    last_ok INTEGER,
    last_out TEXT,
    runs INTEGER DEFAULT 0,
    oks INTEGER DEFAULT 0,
    created REAL
);
CREATE TABLE IF NOT EXISTS wlog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,                   -- info / ok / warn / err
    src TEXT,                     -- 来源（cron / server / kb …）
    msg TEXT,
    created REAL
);
CREATE INDEX IF NOT EXISTS wlog_created ON wlog(created);

-- M 域：技能库（115-120）
CREATE TABLE IF NOT EXISTS skill_fav (
    key TEXT PRIMARY KEY,           -- 来源|名字
    created REAL
);
CREATE TABLE IF NOT EXISTS skill_runs (
    key TEXT PRIMARY KEY,
    name TEXT,
    src TEXT,
    runs INTEGER DEFAULT 0,
    last_run REAL,
    last_ok INTEGER DEFAULT 1,
    created REAL
);
CREATE TABLE IF NOT EXISTS skill_dirs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    label TEXT,
    created REAL
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
    # I 域：项目进阶（79-86）
    "ALTER TABLE projects ADD COLUMN archived INTEGER DEFAULT 0",
    "ALTER TABLE projects ADD COLUMN deadline TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN color TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN kind TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN created REAL",
    # J 域：资料 / 知识库（87-94）
    "ALTER TABLE kb ADD COLUMN status TEXT DEFAULT '待读'",
    "ALTER TABLE kb ADD COLUMN fav INTEGER DEFAULT 0",
    "ALTER TABLE kb ADD COLUMN summary TEXT DEFAULT ''",
    "ALTER TABLE kb ADD COLUMN read_at REAL",
    # L 域：系统工具（105-114）
    "ALTER TABLE clip ADD COLUMN pinned INTEGER DEFAULT 0",
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


# ---- 108 定时任务：cron 简版 ----------
# 支持四种写法：HH:MM（每天） / every:N（每 N 分钟） / every:Nh（每 N 小时）
# / 标准 5 段（分 时 日 月 周，字段支持 * , a-b  a */n）。周里 0=周日。

def _cron_field_ok(expr: str) -> bool:
    expr = (expr or "").strip()
    if not expr:
        return False
    for part in expr.split(","):
        part = part.strip()
        if part == "*":
            continue
        m = re.match(r"^\*/(\d+)$", part)
        if m:
            if int(m.group(1)) <= 0:
                return False
            continue
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            if int(m.group(1)) > int(m.group(2)):
                return False
            continue
        if part.isdigit():
            continue
        return False
    return True


def _cron_valid(spec: str) -> bool:
    spec = (spec or "").strip()
    if not spec:
        return False
    if re.match(r"^every:\d+[mh]?$", spec, re.I):
        return True
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", spec)     # HH:MM（每天这个点）
    if m:
        return 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59
    parts = spec.split()
    if len(parts) == 5:
        return all(_cron_field_ok(x) for x in parts)
    return False


def _cron_field_hit(expr: str, val: int) -> bool:
    expr = (expr or "").strip()
    if expr == "*":
        return True
    for part in expr.split(","):
        part = part.strip()
        m = re.match(r"^\*/(\d+)$", part)
        if m:
            n = int(m.group(1))
            if n > 0 and val % n == 0:
                return True
            continue
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            if int(m.group(1)) <= val <= int(m.group(2)):
                return True
            continue
        if part.isdigit() and int(part) == val:
            return True
    return False


def _cron_match(spec: str, dt, last: float, now: float) -> bool:
    spec = (spec or "").strip()
    m = re.match(r"^every:(\d+)([mh]?)$", spec, re.I)
    if m:
        n = int(m.group(1))
        step = n * (3600 if (m.group(2) or "m").lower() == "h" else 60)
        return step > 0 and now - (last or 0) >= step
    parts = spec.split()
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", spec)       # HH:MM
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if dt.hour != h or dt.minute != mi:
            return False
        return now - (last or 0) >= 60                 # 同一分钟内只跑一次
    if len(parts) == 5:
        mi, hh, dom, mon, dow = parts
        if not (_cron_field_hit(mi, dt.minute) and _cron_field_hit(hh, dt.hour)
                and _cron_field_hit(dom, dt.day) and _cron_field_hit(mon, dt.month)
                and _cron_field_hit(dow, (dt.weekday() + 1) % 7)):
            return False
        return now - (last or 0) >= 60
    return False


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


# ---- 84 项目模板：新项目自带一份起手清单 ----
# 不做数据库表，模板是「出厂设定」，改起来简单，也不会被误删。

PROJECT_TEMPLATES = [
    {"key": "blank", "name": "空白项目", "desc": "什么都不带，自己搭",
     "tasks": [], "milestones": []},
    {"key": "code", "name": "写代码", "desc": "需求 → 骨架 → 跑通 → 打磨 → 发布",
     "tasks": ["想清楚要解决什么问题", "搭出能跑的最小骨架", "打通主流程", "处理边界与报错", "写清怎么用"],
     "milestones": [{"title": "最小可用", "pct": 40}, {"title": "功能齐全", "pct": 80},
                    {"title": "能给别人用", "pct": 100}]},
    {"key": "study", "name": "啃一本书 / 一门课", "desc": "通读 → 笔记 → 输出",
     "tasks": ["先翻一遍目录，画个地图", "逐章精读并做笔记", "整理成一篇自己的话", "回头补漏"],
     "milestones": [{"title": "读完一半", "pct": 50}, {"title": "笔记成篇", "pct": 85},
                    {"title": "能讲给别人听", "pct": 100}]},
    {"key": "writing", "name": "写东西", "desc": "选题 → 资料 → 初稿 → 改 → 定稿",
     "tasks": ["定选题和角度", "收集材料", "写初稿（先写完再改）", "改结构", "改字句"],
     "milestones": [{"title": "初稿完成", "pct": 60}, {"title": "定稿", "pct": 100}]},
    {"key": "life", "name": "生活小事", "desc": "查 → 定 → 办 → 收尾",
     "tasks": ["先查清楚要什么", "比价 / 定方案", "下单 / 动手", "收货检查"],
     "milestones": [{"title": "方案定了", "pct": 50}, {"title": "办完", "pct": 100}]},
]


def project_templates() -> list[dict]:
    return PROJECT_TEMPLATES


# ---- 87 全文检索：自己做分词，中文按「单字 + 二元组」切 ----

_KB_ASCII = re.compile(r"[0-9a-z_]+")
_KB_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_KB_LINK = re.compile(r"\[\[([^\[\]\n]{1,80})\]\]")
KB_STATUS = ("待读", "在读", "已读")


def kb_terms(text: str) -> set[str]:
    """把一段文字切成可检索的词：ASCII 词（>=2 字符）+ 中文单字 + 中文二元组。"""
    t = (text or "").lower()
    out: set[str] = set()
    for m in _KB_ASCII.finditer(t):
        w = m.group(0)
        if len(w) >= 2:
            out.add(w)
    for m in _KB_CJK.finditer(t):
        s = m.group(0)
        for ch in s:
            out.add(ch)
        for i in range(len(s) - 1):
            out.add(s[i:i + 2])
    return out


def kb_extract_links(body: str) -> list[str]:
    """88 双链：抽出正文里所有 [[标题]]，去重保序。"""
    seen, out = set(), []
    for m in _KB_LINK.finditer(body or ""):
        t = m.group(1).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def kb_snippet(body: str, terms: set[str], width: int = 70) -> str:
    """搜到哪就从哪截一段，让结果里能看出为什么命中。"""
    b = (body or "").replace("\n", " ")
    low = b.lower()
    best = -1
    for t in terms:
        p = low.find(t)
        if p >= 0 and (best < 0 or p < best):
            best = p
    if best < 0:
        return b[:width * 2] + ("…" if len(b) > width * 2 else "")
    a = max(0, best - width)
    z = min(len(b), best + width)
    return ("…" if a > 0 else "") + b[a:z] + ("…" if z < len(b) else "")


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

    def kb_list(self, status: str = "", fav: int = -1) -> list[dict]:
        sql = "SELECT * FROM kb WHERE 1=1"
        args = []
        if status:
            sql += " AND COALESCE(status,'待读')=?"
            args.append(status)
        if fav in (0, 1):
            sql += " AND COALESCE(fav,0)=?"
            args.append(fav)
        sql += " ORDER BY updated DESC"
        return self._run(sql, tuple(args))

    def kb_get(self, id_: int) -> dict:
        rows = self._run("SELECT * FROM kb WHERE id=?", (id_,))
        return rows[0] if rows else {}

    def _kb_apply_links(self, kb_id: int, body: str) -> int:
        """88 把正文里的 [[标题]] 落成边；能对上已有标题的就顺手解析出 id。"""
        self._run("DELETE FROM kb_links WHERE src_id=?", (int(kb_id),), False)
        n = 0
        for title in kb_extract_links(body):
            rows = self._run("SELECT id FROM kb WHERE title=? ORDER BY id LIMIT 1", (title,))
            dst = int(rows[0]["id"]) if rows else 0
            self._run("INSERT INTO kb_links (src_id, dst_title, dst_id) VALUES (?,?,?)",
                      (int(kb_id), title, dst), False)
            n += 1
        return n

    def kb_reindex(self, kb_id: int, title: str, body: str, tags: str) -> int:
        """87 重建这一条的倒排索引。"""
        self._run("DELETE FROM kb_index WHERE kb_id=?", (int(kb_id),), False)
        # 标题权重更高：出现两次（简单加权）
        terms = kb_terms(title + "\n" + title + "\n" + (body or "") + "\n" + (tags or ""))
        if not terms:
            return 0
        self._run_many("INSERT INTO kb_index (kb_id, term) VALUES (?,?)",
                       [(int(kb_id), t) for t in terms])
        return len(terms)

    def _run_many(self, sql: str, seq):
        with self._lock:
            self.conn.executemany(sql, seq)
            self.conn.commit()
        return True

    def _kb_resolve_links(self, title: str, kb_id: int) -> int:
        """新条目落库后，把别人指向它的 [[标题]] 补上 dst_id。"""
        self._run("UPDATE kb_links SET dst_id=? WHERE dst_title=? AND COALESCE(dst_id,0)=0",
                  (int(kb_id), title), False)
        rows = self._run("SELECT COUNT(*) c FROM kb_links WHERE dst_title=?", (title,))
        return int(rows[0]["c"]) if rows else 0

    def kb_save(self, id_: int | None, title: str, body: str, tags: str,
                source: str = "manual", source_path: str = "",
                status: str = "", fav: int | None = None) -> dict:
        if not title and not body:
            return {"ok": False, "error": "标题和正文不能都为空"}
        now = time.time()
        st = status if status in KB_STATUS else ""
        if id_:
            old = self.kb_get(int(id_))
            self._run(
                "UPDATE kb SET title=?, body=?, tags=?, source=?, source_path=?, updated=?, "
                "status=COALESCE(NULLIF(?,''), status), fav=COALESCE(?, fav) WHERE id=?",
                (title, body, tags, source, source_path, now, st,
                 None if fav is None else int(fav), int(id_)), False,
            )
            # 改了标题/正文就重建索引与链接
            if (old.get("title") or "") != title or (old.get("body") or "") != body \
                    or (old.get("tags") or "") != tags:
                self.kb_reindex(int(id_), title, body, tags)
                self._kb_apply_links(int(id_), body)
            # 改了标题：别人按旧标题链进来的边，dst_id 要清掉（旧标题已不存在）
            old_title = old.get("title") or ""
            if old_title and old_title != title:
                self._run("UPDATE kb_links SET dst_id=0 WHERE dst_title=? AND dst_id=?",
                          (old_title, int(id_)), False)
            self._kb_resolve_links(title, int(id_))
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO kb (title, body, tags, source, source_path, status, fav, summary, "
            "created, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, body, tags, source, source_path, st or "待读",
             0 if fav is None else int(fav), "", now, now),
        )
        self.conn.commit()
        kid = cur.lastrowid
        self.kb_reindex(kid, title, body, tags)
        self._kb_apply_links(kid, body)
        self._kb_resolve_links(title, kid)
        return {"ok": True, "id": kid}

    def kb_del(self, id_: int) -> dict:
        self._run("DELETE FROM kb WHERE id=?", (int(id_),), False)
        self._run("DELETE FROM kb_index WHERE kb_id=?", (int(id_),), False)
        self._run("DELETE FROM kb_links WHERE src_id=?", (int(id_),), False)
        self._run("UPDATE kb_links SET dst_id=0 WHERE dst_id=?", (int(id_),), False)
        return {"ok": True}

    # ---- 87 搜索 ----

    def kb_search(self, q: str, limit: int = 40) -> dict:
        """倒排 AND 检索：所有词都命中的条目才算，按命中词数排序。"""
        terms = kb_terms(q)
        if not terms:
            return {"ok": True, "rows": [], "q": q, "n_terms": 0}
        tl = sorted(terms)[:64]          # 词太多时截断，防止 SQL 参数爆炸
        ph = ",".join("?" for _ in tl)
        sql = (f"SELECT kb_id, COUNT(*) c FROM kb_index WHERE term IN ({ph}) "
               "GROUP BY kb_id HAVING c=?" )
        rows = self._run(sql, tuple(tl) + (len(tl),))
        if not rows:
            return {"ok": True, "rows": [], "q": q, "n_terms": len(tl)}
        score = {int(r["kb_id"]): int(r["c"]) for r in rows}
        ids = list(score.keys())
        if not ids:
            return {"ok": True, "rows": [], "q": q, "n_terms": len(tl)}
        ph2 = ",".join("?" for _ in ids)
        got = self._run(f"SELECT * FROM kb WHERE id IN ({ph2})", tuple(ids))
        for g in got:
            g["score"] = score.get(int(g["id"]), 0)
            g["snippet"] = kb_snippet(g.get("body") or "", terms)
        got.sort(key=lambda g: (-g["score"], -(g.get("updated") or 0)))
        return {"ok": True, "rows": got[:limit], "q": q, "n_terms": len(tl),
                "total": len(got), "index_size": self._kb_index_size()}

    def _kb_index_size(self) -> int:
        rows = self._run("SELECT COUNT(*) c FROM kb_index")
        return int(rows[0]["c"]) if rows else 0

    def kb_reindex_all(self) -> dict:
        """把库里已有的资料全部重建索引（老数据没索引时用）。"""
        rows = self._run("SELECT id, title, body, tags FROM kb")
        for r in rows:
            self.kb_reindex(int(r["id"]), r.get("title") or "", r.get("body") or "",
                            r.get("tags") or "")
            self._kb_apply_links(int(r["id"]), r.get("body") or "")
            self._kb_resolve_links(r.get("title") or "", int(r["id"]))
        return {"ok": True, "n": len(rows), "index_size": self._kb_index_size()}

    # ---- 88 双链 ----

    def kb_backlinks(self, id_: int) -> list[dict]:
        """谁链到了我（按 id 或标题都对得上）。"""
        row = self.kb_get(int(id_))
        title = row.get("title") or ""
        return self._run(
            "SELECT l.src_id AS id, k.title, k.updated FROM kb_links l "
            "JOIN kb k ON k.id=l.src_id "
            "WHERE l.src_id<>? AND (l.dst_id=? OR (COALESCE(l.dst_id,0)=0 AND l.dst_title=?)) "
            "ORDER BY k.updated DESC", (int(id_), int(id_), title))

    def kb_outlinks(self, id_: int) -> list[dict]:
        """我链到了谁。目标改名后这里要如实报「不存在」，不能拿旧 id 硬顶。"""
        rows = self._run("SELECT * FROM kb_links WHERE src_id=? ORDER BY dst_title",
                         (int(id_),))
        out = []
        for l in rows:
            t = self.kb_get(int(l["dst_id"])) if l.get("dst_id") else {}
            alive = bool(t) and (t.get("title") or "") == (l.get("dst_title") or "")
            out.append({"title": l.get("dst_title"), "id": (l.get("dst_id") or 0) if alive else 0,
                        "exists": alive, "updated": t.get("updated") if alive else None})
        return out

    def kb_link_graph(self) -> dict:
        """全库双链图：节点 + 边，给前端画个简图/列表。"""
        nodes = self._run("SELECT id, title, tags FROM kb ORDER BY id")
        edges = self._run("SELECT src_id, dst_id, dst_title FROM kb_links")
        return {"ok": True, "nodes": nodes, "edges": edges,
                "dangling": sorted({e["dst_title"] for e in edges if not e.get("dst_id")})}

    # ---- 89 阅读队列 ----

    def kb_status(self, id_: int, status: str) -> dict:
        if status not in KB_STATUS:
            return {"ok": False, "error": "状态只能是 " + "/".join(KB_STATUS)}
        read_at = time.time() if status == "已读" else None
        self._run("UPDATE kb SET status=?, read_at=COALESCE(?, read_at), updated=? WHERE id=?",
                  (status, read_at, time.time(), int(id_)), False)
        return {"ok": True, "status": status}

    def kb_queue(self) -> dict:
        rows = self._run("SELECT COALESCE(status,'待读') s, COUNT(*) c FROM kb GROUP BY s")
        cnt = {r["s"]: int(r["c"]) for r in rows}
        return {"ok": True, "待读": cnt.get("待读", 0), "在读": cnt.get("在读", 0),
                "已读": cnt.get("已读", 0), "total": sum(cnt.values())}

    # ---- 90 AI 摘要卡 ----

    def kb_set_summary(self, id_: int, summary: str) -> dict:
        self._run("UPDATE kb SET summary=?, updated=? WHERE id=?",
                  (summary or "", time.time(), int(id_)), False)
        return {"ok": True}

    # ---- 91 标签批量 ----

    def kb_tags_bulk(self, ids: list[int], op: str, tag: str = "") -> dict:
        """多选改标签：add 追加 / remove 去掉 / replace 整体换成 tag。"""
        tag = (tag or "").strip()
        n = 0
        for i in ids or []:
            row = self.kb_get(int(i))
            if not row:
                continue
            cur = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
            if op == "replace":
                new = [tag] if tag else []
            elif op == "remove":
                new = [t for t in cur if t != tag]
            else:                                   # add
                new = cur + ([tag] if tag and tag not in cur else [])
            txt = ",".join(new)
            self._run("UPDATE kb SET tags=?, updated=? WHERE id=?",
                      (txt, time.time(), int(i)), False)
            self.kb_reindex(int(i), row.get("title") or "", row.get("body") or "", txt)
            n += 1
        return {"ok": True, "n": n}

    # ---- 92 相关推荐 ----

    def kb_related(self, id_: int, limit: int = 5) -> list[dict]:
        """同标签最近的几篇（按共有标签数排序），没有标签就按命中词兜底。"""
        me = self.kb_get(int(id_))
        tags = {t.strip() for t in (me.get("tags") or "").split(",") if t.strip()}
        others = [r for r in self._run("SELECT * FROM kb WHERE id<>?", (int(id_),))
                  if r.get("id") != int(id_)]
        scored = []
        for r in others:
            ot = {t.strip() for t in (r.get("tags") or "").split(",") if t.strip()}
            common = len(tags & ot)
            # 标题/正文的词重叠也算一点分
            ov = len(kb_terms((me.get("title") or "") + (me.get("body") or "")[:400])
                     & kb_terms((r.get("title") or "") + (r.get("body") or "")[:400]))
            scored.append((common * 10 + min(ov, 20), r))
        scored.sort(key=lambda x: (-x[0], -(x[1].get("updated") or 0)))
        return [r for s, r in scored if s > 0][:limit]

    # ---- 93 整库导出 ----

    def kb_export(self) -> list[dict]:
        """整库导出：每条资料一条，带标题/标签/状态/正文，交给上层打成 zip 或 md。"""
        rows = self._run("SELECT * FROM kb ORDER BY updated DESC")
        out = []
        for r in rows:
            out.append({
                "name": self._safe_name(r.get("title") or ("kb-%s" % r.get("id"))),
                "md": "# %s\n\n- 标签：%s\n- 状态：%s\n- 来源：%s%s\n- 更新：%s\n\n%s\n" % (
                    r.get("title") or "(无标题)",
                    r.get("tags") or "—",
                    r.get("status") or "待读",
                    r.get("source") or "manual",
                    (" " + (r.get("source_path") or "")) if r.get("source_path") else "",
                    datetime.datetime.fromtimestamp(r.get("updated") or 0).strftime("%Y-%m-%d %H:%M"),
                    r.get("body") or ""),
            })
        return out

    @staticmethod
    def _safe_name(s: str) -> str:
        bad = '\\/:*?"<>|\r\n\t'
        t = "".join("_" if c in bad else c for c in (s or "")).strip().strip(".")
        return (t or "kb")[:60]

    # ---- 94 收藏集 ----

    def kb_fav(self, id_: int, on: int = 1) -> dict:
        self._run("UPDATE kb SET fav=? WHERE id=?", (1 if on else 0, int(id_)), False)
        return {"ok": True, "fav": 1 if on else 0}

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

    def projects_list(self, archived: int = 0) -> list[dict]:
        """archived: -1 全部 / 0 未归档 / 1 只看归档。"""
        if archived < 0:
            return self._run("SELECT * FROM projects ORDER BY archived, id")
        return self._run("SELECT * FROM projects WHERE COALESCE(archived,0)=? ORDER BY id",
                         (int(archived),))

    def project_save(self, id_: int | None, name: str, status: str, next_step: str,
                     deadline: str = "", color: str = "", template: str = "") -> dict:
        """84 新建时可带模板：一并把默认任务和里程碑种下去。"""
        now = time.time()
        if id_:
            self._run(
                "UPDATE projects SET name=?, status=?, next_step=?, deadline=?, color=?, "
                "updated=? WHERE id=?",
                (name, status, next_step, deadline or "", color or "", now, id_),
                False,
            )
            self.plog_add(id_, "改了项目信息（状态：%s）" % (status or "未设"), "auto")
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO projects (name, status, next_step, deadline, color, kind, archived, "
            "updated, created) VALUES (?,?,?,?,?,?,0,?,?)",
            (name, status, next_step, deadline or "", color or "", template or "", now, now),
        )
        self.conn.commit()
        pid = cur.lastrowid
        self.plog_add(pid, "建了这个项目", "auto")
        if template:
            self.apply_template(pid, template)
        return {"ok": True, "id": pid, "template": template or ""}

    def apply_template(self, pid: int, key: str) -> dict:
        """84 给项目种模板：任务进看板，里程碑进里程碑表。"""
        tpl = next((t for t in PROJECT_TEMPLATES if t["key"] == key), None)
        if not tpl or key == "blank":
            return {"ok": False, "error": "没有这个模板"}
        for title in tpl["tasks"]:
            self.task_save(None, pid, title, "待办", "", quiet=True)
        for i, ms in enumerate(tpl["milestones"]):
            self.milestone_save(None, pid, ms["title"], "", int(ms.get("pct") or 0), i,
                                quiet=True)
        self.plog_add(pid, "套用了模板「%s」：%d 个任务、%d 个里程碑"
                      % (tpl["name"], len(tpl["tasks"]), len(tpl["milestones"])), "auto")
        return {"ok": True, "n_task": len(tpl["tasks"]), "n_ms": len(tpl["milestones"])}

    def project_archive(self, id_: int, on: int = 1) -> dict:
        """82 归档：做完的收起来，不删数据。"""
        self._run("UPDATE projects SET archived=?, updated=? WHERE id=?",
                  (1 if on else 0, time.time(), int(id_)), False)
        self.plog_add(int(id_), "归档了" if on else "从归档里放回来了", "auto")
        return {"ok": True, "archived": 1 if on else 0}

    def project_del(self, id_: int) -> dict:
        self._run("DELETE FROM projects WHERE id=?", (id_,), False)
        self._run("DELETE FROM tasks WHERE project_id=?", (id_,), False)
        self._run("DELETE FROM plog WHERE project_id=?", (id_,), False)
        self._run("DELETE FROM milestones WHERE project_id=?", (id_,), False)
        return {"ok": True}

    def _last_active(self, pid: int) -> float:
        """80 停滞预警：项目上最后一次有动静是什么时候。"""
        row = self.conn.execute("SELECT updated, created FROM projects WHERE id=?", (pid,)).fetchone()
        cands = [row["updated"] if row else 0, row["created"] if row else 0]
        for sql in ("SELECT MAX(created) m FROM plog WHERE project_id=?",
                    "SELECT MAX(created) m FROM tasks WHERE project_id=?",
                    "SELECT MAX(done_at) m FROM tasks WHERE project_id=?",
                    "SELECT MAX(created) m FROM milestones WHERE project_id=?",
                    "SELECT MAX(ended) m FROM pomodoro WHERE project_id=?"):
            try:
                v = self.conn.execute(sql, (pid,)).fetchone()[0]
                if v:
                    cands.append(v)
            except sqlite3.OperationalError:
                pass
        return float(max(cands) or 0)

    def projects_board(self, stale_days: int | None = None) -> list[dict]:
        """项目卡片 + 任务进度 + 番茄分钟 + 里程碑完成度 + 停滞天数，一次给全。

        stale_days 不传就读配置（kv.projectStaleDays，默认 7 天）。
        """
        if stale_days is None:
            stale_days = self.stale_days()
        rows = self._run("SELECT * FROM projects ORDER BY archived, id")
        now = time.time()
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
            # 79 里程碑完成度
            ms = self._run("SELECT pct, done FROM milestones WHERE project_id=? ORDER BY sort, id",
                           (pid,))
            p["n_ms"] = len(ms)
            p["ms_done"] = sum(1 for m in ms if m.get("done"))
            p["ms_pct"] = round(sum((100 if m.get("done") else (m.get("pct") or 0))
                                    for m in ms) / len(ms)) if ms else 0
            # 80 停滞预警
            last = self._last_active(pid)
            p["last_active"] = last
            days = int((now - last) // 86400) if last else 0
            p["idle_days"] = days
            p["stale"] = 1 if (days >= stale_days and p.get("status") != "已完成"
                               and not p.get("archived")) else 0
        return rows

    def stale_days(self) -> int:
        rows = self._run("SELECT v FROM kv WHERE k='projectStaleDays'")
        try:
            return max(1, int((rows[0]["v"] if rows else "") or 7))
        except (ValueError, TypeError):
            return 7

    # ---- 79 里程碑 ----

    def milestone_list(self, project_id: int = 0) -> list[dict]:
        if project_id:
            return self._run("SELECT * FROM milestones WHERE project_id=? ORDER BY sort, id",
                             (project_id,))
        return self._run("SELECT * FROM milestones ORDER BY project_id, sort, id")

    def milestone_save(self, id_: int | None, project_id: int, title: str, day: str = "",
                       pct: int = 0, sort: int = -1, quiet: bool = False) -> dict:
        if not (title or "").strip():
            return {"ok": False, "error": "里程碑要有名字"}
        try:
            pct = max(0, min(100, int(pct or 0)))
        except (ValueError, TypeError):
            pct = 0
        if id_:
            self._run("UPDATE milestones SET title=?, day=?, pct=? WHERE id=?",
                      (title.strip(), day or "", pct, int(id_)), False)
            return {"ok": True, "id": id_}
        if sort < 0:
            sort = self.conn.execute(
                "SELECT COALESCE(MAX(sort),-1)+1 FROM milestones WHERE project_id=?",
                (int(project_id or 0),)).fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO milestones (project_id, title, day, pct, done, sort, created) "
            "VALUES (?,?,?,?,0,?,?)",
            (int(project_id or 0), title.strip(), day or "", pct, sort, time.time()),
        )
        self.conn.commit()
        if not quiet:
            self.plog_add(int(project_id or 0), "加了里程碑「%s」" % title.strip(), "auto")
        return {"ok": True, "id": cur.lastrowid}

    def milestone_done(self, id_: int, done: int = 1, pct: int = -1) -> dict:
        rows = self._run("SELECT * FROM milestones WHERE id=?", (int(id_),))
        if not rows:
            return {"ok": False, "error": "没这个里程碑"}
        d = 1 if done else 0
        newpct = 100 if d else (0 if pct < 0 else max(0, min(100, int(pct))))
        self._run("UPDATE milestones SET done=?, pct=? WHERE id=?", (d, newpct, int(id_)), False)
        if d:
            self.plog_add(int(rows[0].get("project_id") or 0),
                          "完成了里程碑「%s」" % (rows[0].get("title") or ""), "auto")
        return {"ok": True, "done": d, "pct": newpct}

    def milestone_del(self, id_: int) -> dict:
        self._run("DELETE FROM milestones WHERE id=?", (int(id_),), False)
        return {"ok": True}

    # ---- 83 跨项目任务 ----

    def tasks_all(self, state: str = "", project_id: int = 0) -> list[dict]:
        """所有项目的任务一屏看，带项目名。"""
        sql = ("SELECT t.*, COALESCE(p.name,'(没挂项目)') AS project, "
               "COALESCE(p.color,'') AS pcolor, COALESCE(p.archived,0) AS p_archived "
               "FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE 1=1")
        args = []
        if state:
            sql += " AND t.state=?"
            args.append(state)
        if project_id:
            sql += " AND t.project_id=?"
            args.append(int(project_id))
        sql += " ORDER BY CASE t.state WHEN '在做' THEN 0 WHEN '待办' THEN 1 ELSE 2 END, " \
               "t.due='' , t.due, t.project_id, t.sort, t.id"
        return self._run(sql, tuple(args))

    # ---- 85 时间线（甘特简版）----

    def projects_timeline(self, project_id: int = 0) -> dict:
        """项目跨度 + 任务截止 + 里程碑日期，拼成几条能画成横条的区间。"""
        projs = ([p for p in self._run("SELECT * FROM projects WHERE id=?", (project_id,))]
                 if project_id else self._run("SELECT * FROM projects ORDER BY id"))
        out = []
        for p in projs:
            pid = p["id"]
            ts = [t for t in self._run("SELECT * FROM tasks WHERE project_id=?", (pid,))
                  if t.get("due")]
            ms = [m for m in self._run("SELECT * FROM milestones WHERE project_id=?", (pid,))
                  if m.get("day")]
            pts = [x for x in [p.get("created"), p.get("updated")] if x]
            starts = [x for x in ([t["due"] for t in ts] + [m["day"] for m in ms]
                                  + ([p["deadline"]] if p.get("deadline") else [])) if x]
            # 起点：项目创建日；终点：最晚的截止/里程碑/最后活动
            import datetime as _dt
            c = p.get("created")
            s = _dt.date.fromtimestamp(c).isoformat() if c else (
                min(starts) if starts else "")
            e = max(starts) if starts else (
                _dt.date.fromtimestamp(max(pts)).isoformat() if pts else s)
            if not s:
                continue
            out.append({
                "id": pid, "name": p.get("name") or "", "color": p.get("color") or "",
                "status": p.get("status") or "", "archived": p.get("archived") or 0,
                "start": s, "end": e,
                "tasks": sorted([{"title": t.get("title"), "due": t.get("due"),
                                  "state": t.get("state")} for t in ts],
                                key=lambda x: x["due"] or ""),
                "milestones": sorted([{"title": m.get("title"), "day": m.get("day"),
                                       "done": m.get("done")} for m in ms],
                                     key=lambda x: x["day"] or ""),
            })
        return {"ok": True, "rows": out}

    # ---- 86 动态日志 ----

    def plog_auto(self, project_id: int, text: str) -> dict:
        return self.plog_add(int(project_id or 0), text, "auto")

    # ---- 任务看板 ----

    def tasks_list(self, project_id: int = 0) -> list[dict]:
        if project_id:
            return self._run(
                "SELECT * FROM tasks WHERE project_id=? ORDER BY sort, id", (project_id,))
        return self._run("SELECT * FROM tasks ORDER BY project_id, sort, id")

    def task_save(self, id_: int | None, project_id: int, title: str, state: str,
                  due: str = "", quiet: bool = False) -> dict:
        if not title:
            return {"ok": False, "error": "任务名不能为空"}
        if id_:
            self._run("UPDATE tasks SET project_id=?, title=?, state=?, due=? WHERE id=?",
                      (int(project_id or 0), title, state or "待办", due or "", id_), False)
            if not quiet:
                self.plog_auto(project_id, "改了任务「%s」" % title)
            return {"ok": True, "id": id_}
        cur = self.conn.execute(
            "INSERT INTO tasks (project_id, title, state, due, sort, created) "
            "VALUES (?,?,?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE project_id=?),?)",
            (int(project_id or 0), title, state or "待办", due or "",
             int(project_id or 0), time.time()),
        )
        self.conn.commit()
        if not quiet:
            self.plog_auto(project_id, "加了任务「%s」" % title)
        return {"ok": True, "id": cur.lastrowid}

    def task_state(self, id_: int, state: str) -> dict:
        now = time.time() if state == "已完成" else None
        rows = self._run("SELECT project_id, title FROM tasks WHERE id=?", (id_,))
        self._run("UPDATE tasks SET state=?, done_at=COALESCE(?, done_at) WHERE id=?",
                  (state, now, id_), False)
        if rows:
            self.plog_auto(rows[0].get("project_id") or 0,
                           "任务「%s」→ %s" % (rows[0].get("title") or "", state))
        return {"ok": True}

    def task_due(self, id_: int, due: str) -> dict:
        rows = self._run("SELECT project_id, title FROM tasks WHERE id=?", (id_,))
        self._run("UPDATE tasks SET due=? WHERE id=?", (due or "", id_), False)
        if rows:
            self.plog_auto(rows[0].get("project_id") or 0,
                           "任务「%s」截止改为 %s" % (rows[0].get("title") or "", due or "不限"))
        return {"ok": True}

    def tasks_due(self, a: str, b: str) -> list[dict]:
        """某段日期内到期的未完成任务（日历要把它们画上去）。"""
        return self._run(
            "SELECT t.*, COALESCE(p.name,'') AS project FROM tasks t "
            "LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.due<>'' AND t.due IS NOT NULL AND t.due>=? AND t.due<=? "
            "AND t.state<>'已完成' ORDER BY t.due, t.id", (a, b))

    def task_del(self, id_: int) -> dict:
        rows = self._run("SELECT project_id, title FROM tasks WHERE id=?", (int(id_),))
        self._run("DELETE FROM tasks WHERE id=?", (int(id_),), False)
        if rows:
            self.plog_auto(rows[0].get("project_id") or 0,
                           "删了任务「%s」" % (rows[0].get("title") or ""))
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

    # ================= K 域：生活（95-104） =================

    LIFE_CATS = ("餐饮", "交通", "购物", "学习", "娱乐", "房租水电", "医疗", "人情", "其它")
    CHARGE_STATES = ("", "充电中", "已满", "待充", "不用充")
    WISH_STATES = ("想要", "比价中", "已购", "不买了")

    # ---- 95 记账 ----

    def ledger_add(self, day: str, kind: str, amount, category: str = "",
                   note: str = "") -> dict:
        if kind not in ("支出", "收入"):
            return {"ok": False, "error": "类型只能是 支出 / 收入"}
        day = (day or "").strip() or _today()
        try:
            amt = round(float(amount or 0), 2)
        except (TypeError, ValueError):
            return {"ok": False, "error": "金额填得不对"}
        if amt <= 0:
            return {"ok": False, "error": "金额要大于 0"}
        cur = self.conn.execute(
            "INSERT INTO ledger (day,kind,amount,category,note,created) VALUES (?,?,?,?,?,?)",
            (day, kind, amt, (category or "").strip() or "其它", (note or "").strip(),
             time.time()))
        self.conn.commit()
        r = {"ok": True, "id": cur.lastrowid}
        if kind == "支出":                       # 96 记完顺手看一眼这个月有没有超
            r["over"] = self.budget_check(day[:7]).get("over", [])
        return r

    def ledger_del(self, id_: int) -> dict:
        self._run("DELETE FROM ledger WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def ledger_list(self, month: str = "", kind: str = "", limit: int = 800) -> list[dict]:
        sql, args = "SELECT * FROM ledger WHERE 1=1", []
        if month:
            sql += " AND substr(day,1,7)=?"
            args.append(month)
        if kind in ("支出", "收入"):
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY day DESC, id DESC LIMIT ?"
        args.append(int(limit))
        return self._run(sql, tuple(args))

    def ledger_summary(self, month: str = "") -> dict:
        """某个月的收支总览 + 分类汇总。month 空就用本月。"""
        m = month or _today()[:7]
        rows = self._run("SELECT kind, amount, category FROM ledger WHERE substr(day,1,7)=?",
                         (m,))
        inc = sum(r["amount"] or 0 for r in rows if r["kind"] == "收入")
        exp = sum(r["amount"] or 0 for r in rows if r["kind"] == "支出")
        by_out, by_in = {}, {}
        for r in rows:
            c = (r["category"] or "其它").strip() or "其它"
            (by_in if r["kind"] == "收入" else by_out)[c] = \
                (by_in if r["kind"] == "收入" else by_out).get(c, 0) + (r["amount"] or 0)
        cat = [{"cat": k, "used": round(v, 2)} for k, v in by_out.items()]
        cat.sort(key=lambda x: -x["used"])
        src = [{"cat": k, "used": round(v, 2)} for k, v in by_in.items()]
        src.sort(key=lambda x: -x["used"])
        return {"ok": True, "month": m, "income": round(inc, 2), "expense": round(exp, 2),
                "net": round(inc - exp, 2), "n": len(rows), "by_cat": cat, "by_src": src,
                "cats": list(self.LIFE_CATS)}

    def ledger_months(self, limit: int = 12) -> dict:
        """102 收入看板：按月对比（含支出，好算净结余）。"""
        rows = self._run(
            "SELECT substr(day,1,7) m, kind, SUM(amount) s, COUNT(*) n FROM ledger "
            "GROUP BY m, kind ORDER BY m DESC")
        agg: dict[str, dict] = {}
        for r in rows:
            m = r["m"] or "未知"
            a = agg.setdefault(m, {"month": m, "income": 0.0, "expense": 0.0, "n": 0})
            if r["kind"] == "收入":
                a["income"] += r["s"] or 0
            else:
                a["expense"] += r["s"] or 0
            a["n"] += r["n"] or 0
        out = list(agg.values())[:int(limit)]
        for a in out:
            a["income"] = round(a["income"], 2)
            a["expense"] = round(a["expense"], 2)
            a["net"] = round(a["income"] - a["expense"], 2)
        return {"ok": True, "months": out}

    # ---- 96 超支预警 ----

    def budget_limits(self) -> dict:
        raw = self.kv_get("budgetLimits", "") or ""
        try:
            d = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            d = {}
        return {str(k): float(v) for k, v in d.items() if isinstance(v, (int, float))}

    def budget_limits_save(self, limits: dict) -> dict:
        clean = {}
        for k, v in (limits or {}).items():
            try:
                f = round(float(v), 2)
            except (TypeError, ValueError):
                continue
            if f > 0:
                clean[str(k).strip() or "其它"] = f
        self.kv_set("budgetLimits", json.dumps(clean, ensure_ascii=False))
        return {"ok": True, "limits": clean}

    def budget_check(self, month: str = "") -> dict:
        """按分类比对本月支出与阈值。over 里就是超支的。"""
        m = month or _today()[:7]
        lim = self.budget_limits()
        rows = self.ledger_summary(m)["by_cat"]
        used = {r["cat"]: r["used"] for r in rows}
        out, over = [], []
        for c in dict.fromkeys(list(self.LIFE_CATS) + list(used) + list(lim)):
            u, l = round(used.get(c, 0.0), 2), round(lim.get(c, 0.0), 2)
            if not u and not l:
                continue
            item = {"cat": c, "used": u, "limit": l,
                    "pct": round(u / l * 100, 1) if l else 0.0,
                    "over": bool(l and u > l), "left": round(l - u, 2) if l else 0.0}
            out.append(item)
            if item["over"]:
                over.append(item)
        out.sort(key=lambda x: -x["pct"])
        return {"ok": True, "month": m, "rows": out, "over": over,
                "limit_n": len(lim)}

    # ---- 97 设备台账 / 99 充电区 ----

    def devices_list(self) -> list[dict]:
        rows = self._run("SELECT * FROM devices ORDER BY id DESC")
        now = datetime.date.today()
        for r in rows:
            r["warranty_left"] = self._warranty_days(r.get("bought"), r.get("warranty"), now)
            r["warranty_end"] = self._warranty_end(r.get("bought"), r.get("warranty"))
        return rows

    @staticmethod
    def _warranty_end(bought: str, months) -> str:
        if not bought or not months:
            return ""
        try:
            d = datetime.date.fromisoformat(str(bought)[:10])
        except ValueError:
            return ""
        y, m = divmod(d.month - 1 + int(months), 12)
        try:
            return d.replace(year=d.year + y, month=m + 1).isoformat()
        except ValueError:                        # 2/29 之类
            return ""

    @staticmethod
    def _warranty_days(bought: str, months, today) -> int | None:
        end = Store._warranty_end(bought, months)
        if not end:
            return None
        try:
            return (datetime.date.fromisoformat(end) - today).days
        except ValueError:
            return None

    def device_save(self, id_: int | None, name: str, kind: str = "", zone: str = "",
                    bought: str = "", warranty=0, price=0, charge: str = "",
                    note: str = "") -> dict:
        if not (name or "").strip():
            return {"ok": False, "error": "设备名不能空"}
        ch = charge if charge in self.CHARGE_STATES else ""
        try:
            w, p = int(warranty or 0), float(price or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "保修月数/价格填得不对"}
        args = ((name or "").strip(), (kind or "").strip(), (zone or "").strip(),
                (bought or "").strip()[:10], w, p, ch, (note or "").strip())
        if id_:
            self._run("UPDATE devices SET name=?,kind=?,zone=?,bought=?,warranty=?,price=?,"
                      "charge=?,note=? WHERE id=?", args + (int(id_),), False)
            return {"ok": True, "id": int(id_)}
        cur = self.conn.execute(
            "INSERT INTO devices (name,kind,zone,bought,warranty,price,charge,note,created) "
            "VALUES (?,?,?,?,?,?,?,?,?)", args + (time.time(),))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def device_charge(self, id_: int, state: str) -> dict:
        if state not in self.CHARGE_STATES:
            return {"ok": False, "error": "充电状态不认识"}
        self._run("UPDATE devices SET charge=? WHERE id=?", (state, int(id_)), False)
        return {"ok": True, "charge": state}

    def device_del(self, id_: int) -> dict:
        self._run("DELETE FROM devices WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def charge_board(self) -> dict:
        """99 充电区：按位置分组看谁在充、谁满了。"""
        rows = self._run("SELECT * FROM devices WHERE COALESCE(charge,'')<>'' OR "
                         "COALESCE(zone,'')<>'' ORDER BY zone, id")
        zones: dict[str, list] = {}
        for r in rows:
            zones.setdefault((r.get("zone") or "未分区").strip() or "未分区", []).append(r)
        return {"ok": True, "zones": [{"zone": k, "items": v} for k, v in zones.items()],
                "n_charging": sum(1 for r in rows if r.get("charge") == "充电中"),
                "n_pending": sum(1 for r in rows if r.get("charge") == "待充")}

    # ---- 100 网络拓扑 ----

    def net_list(self) -> list[dict]:
        rows = self._run("SELECT * FROM net_nodes ORDER BY parent, id")
        by_parent: dict[int, list] = {}
        for r in rows:
            by_parent.setdefault(int(r.get("parent") or 0), []).append(r)
        out = []

        def walk(pid: int, depth: int):
            for r in by_parent.get(pid, []):
                r["depth"] = depth
                out.append(r)
                walk(int(r["id"]), depth + 1)
        walk(0, 0)
        for r in rows:                            # parent 指向不存在的节点时也得露面
            if r not in out:
                r["depth"] = 0
                out.append(r)
        return out

    def net_save(self, id_: int | None, name: str, kind: str = "", parent=0,
                 port: str = "", ip: str = "", note: str = "") -> dict:
        if not (name or "").strip():
            return {"ok": False, "error": "名字不能空"}
        try:
            p = int(parent or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "上游填得不对"}
        if id_ and p == int(id_):
            return {"ok": False, "error": "不能把自己当上游"}
        args = ((name or "").strip(), (kind or "").strip(), p, (port or "").strip(),
                (ip or "").strip(), (note or "").strip())
        if id_:
            self._run("UPDATE net_nodes SET name=?,kind=?,parent=?,port=?,ip=?,note=? WHERE id=?",
                      args + (int(id_),), False)
            return {"ok": True, "id": int(id_)}
        cur = self.conn.execute(
            "INSERT INTO net_nodes (name,kind,parent,port,ip,note,created) "
            "VALUES (?,?,?,?,?,?,?)", args + (time.time(),))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def net_del(self, id_: int) -> dict:
        """删节点时把挂在它下面的也跟着挪到根，别留孤儿。"""
        self._run("UPDATE net_nodes SET parent=0 WHERE parent=?", (int(id_),), False)
        self._run("DELETE FROM net_nodes WHERE id=?", (int(id_),), False)
        return {"ok": True}

    # ---- 101 采购清单 ----

    def wishes_list(self) -> dict:
        rows = self._run("SELECT * FROM wishes ORDER BY CASE status WHEN '想要' THEN 0 "
                         "WHEN '比价中' THEN 1 WHEN '已购' THEN 2 ELSE 3 END, priority, id DESC")
        want = round(sum(r["price"] or 0 for r in rows if r["status"] in ("想要", "比价中")), 2)
        bought = round(sum(r["price"] or 0 for r in rows if r["status"] == "已购"), 2)
        return {"ok": True, "rows": rows, "want_total": want, "bought_total": bought,
                "states": list(self.WISH_STATES)}

    def wish_save(self, id_: int | None, name: str, price=0, shop: str = "", url: str = "",
                  priority=2, status: str = "想要", note: str = "") -> dict:
        if not (name or "").strip():
            return {"ok": False, "error": "名字不能空"}
        st = status if status in self.WISH_STATES else "想要"
        try:
            pr, pi = float(price or 0), int(priority or 2)
        except (TypeError, ValueError):
            return {"ok": False, "error": "价格/优先级填得不对"}
        pi = pi if pi in (1, 2, 3) else 2
        bought_at = _today() if st == "已购" else ""
        args = ((name or "").strip(), pr, (shop or "").strip(), (url or "").strip(),
                pi, st, bought_at, (note or "").strip())
        if id_:
            old = self._run("SELECT status, bought_at FROM wishes WHERE id=?", (int(id_),))
            if old and old[0].get("status") == "已购" and st == "已购":
                args = args[:6] + (old[0].get("bought_at") or bought_at,) + args[7:]
            self._run("UPDATE wishes SET name=?,price=?,shop=?,url=?,priority=?,status=?,"
                      "bought_at=?,note=? WHERE id=?", args + (int(id_),), False)
            return {"ok": True, "id": int(id_)}
        cur = self.conn.execute(
            "INSERT INTO wishes (name,price,shop,url,priority,status,bought_at,note,created) "
            "VALUES (?,?,?,?,?,?,?,?,?)", args + (time.time(),))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def wish_buy(self, id_: int, day: str = "") -> dict:
        """一键标记已购（比价完了直接落账，顺手记一笔支出）。"""
        day = (day or "").strip() or _today()
        rows = self._run("SELECT * FROM wishes WHERE id=?", (int(id_),))
        if not rows:
            return {"ok": False, "error": "这条不在清单里"}
        w = rows[0]
        self._run("UPDATE wishes SET status='已购', bought_at=? WHERE id=?", (day, int(id_)), False)
        r = self.ledger_add(day, "支出", w.get("price") or 0, "购物",
                            (w.get("name") or "") + "（采购）")
        return {"ok": True, "ledger": r, "over": r.get("over", [])}

    def wish_del(self, id_: int) -> dict:
        self._run("DELETE FROM wishes WHERE id=?", (int(id_),), False)
        return {"ok": True}

    # ---- 104 体重简记 ----

    def weight_list(self, limit: int = 180) -> list[dict]:
        return self._run("SELECT * FROM weights ORDER BY day DESC LIMIT ?", (int(limit),))

    def weight_add(self, day: str, kg, note: str = "") -> dict:
        day = (day or "").strip() or _today()
        try:
            v = round(float(kg or 0), 2)
        except (TypeError, ValueError):
            return {"ok": False, "error": "体重填得不对"}
        if not 20 <= v <= 300:
            return {"ok": False, "error": "这个数不像体重"}
        old = self._run("SELECT id FROM weights WHERE day=?", (day,))
        if old:                                   # 同一天再记就覆盖，别留两条
            self._run("UPDATE weights SET kg=?, note=?, created=? WHERE id=?",
                      (v, (note or "").strip(), time.time(), int(old[0]["id"])), False)
            return {"ok": True, "id": int(old[0]["id"]), "replaced": True}
        cur = self.conn.execute(
            "INSERT INTO weights (day,kg,note,created) VALUES (?,?,?,?)",
            (day, v, (note or "").strip(), time.time()))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid, "replaced": False}

    def weight_del(self, id_: int) -> dict:
        self._run("DELETE FROM weights WHERE id=?", (int(id_),), False)
        return {"ok": True}

    def weight_stats(self) -> dict:
        rows = self._run("SELECT day, kg FROM weights ORDER BY day")   # 升序，给曲线
        if not rows:
            return {"ok": True, "n": 0, "series": []}
        first, last = rows[0], rows[-1]
        mn = min(r["kg"] for r in rows)
        mx = max(r["kg"] for r in rows)
        avg7 = sum(r["kg"] for r in rows[-7:]) / len(rows[-7:])
        return {"ok": True, "n": len(rows), "series": rows,
                "first": first, "last": last, "delta": round(last["kg"] - first["kg"], 2),
                "min": mn, "max": mx, "avg7": round(avg7, 2)}

    # ---- 老数据搬家：lists 表的 devices/budget/income 迁到新表 ----

    def life_migrate(self) -> dict:
        if self.kv_get("lifeMigrated", "") == "1":
            return {"ok": True, "skipped": True, "n": 0}
        n = 0
        rows = self._run("SELECT * FROM lists")
        for r in rows:
            try:
                f = json.loads(r.get("fields") or "{}")
            except (ValueError, TypeError):
                f = {}
            k = r.get("key")
            if k == "devices" and f.get("name"):
                self.device_save(None, f.get("name", ""), "", f.get("loc", ""),
                                 "", 0, 0, "", (f.get("power", "") + " " + f.get("note", "")).strip())
            elif k == "budget" and f.get("item"):
                self.wish_save(None, f.get("item", ""), f.get("plan") or 0, "", "", 2,
                               "已购" if f.get("actual") else "想要", f.get("note", ""))
            elif k == "income" and f.get("src"):
                self.ledger_add(f.get("date") or _today(), "收入", f.get("amt") or 0,
                                f.get("src", ""), f.get("note", ""))
            else:
                continue
            n += 1
        self.kv_set("lifeMigrated", "1")
        return {"ok": True, "skipped": False, "n": n}

    # ---------------- L 域：系统工具（105-114）----------------

    # 106 剪贴板：置顶 + 搜索

    def clip_pin(self, cid: int, on=1) -> dict:
        self._run("UPDATE clip SET pinned=? WHERE id=?", (1 if on else 0, cid), False)
        return {"ok": True}

    def clip_list_q(self, q: str = "", limit: int = 200) -> list[dict]:
        """置顶优先，再按时间倒序；q 非空时按内容模糊筛。"""
        q = (q or "").strip()
        if q:
            like = f"%{q}%"
            return self._run(
                "SELECT id, text, created, pinned FROM clip WHERE text LIKE ? "
                "ORDER BY pinned DESC, id DESC LIMIT ?", (like, limit))
        return self._run(
            "SELECT id, text, created, pinned FROM clip ORDER BY pinned DESC, id DESC LIMIT ?",
            (limit,))

    # 108 定时任务（cron 简版）

    def cron_list(self) -> list[dict]:
        return self._run("SELECT * FROM crons ORDER BY enabled DESC, id DESC")

    def cron_get(self, cid: int) -> dict | None:
        rows = self._run("SELECT * FROM crons WHERE id=?", (cid,))
        return rows[0] if rows else None

    def cron_save(self, cid, name: str, kind: str, payload: str, sched: str,
                  enabled=1, notify=0) -> dict:
        name = (name or "").strip() or "未命名任务"
        payload = (payload or "").strip()
        sched = (sched or "").strip() or "every:60"
        if not payload:
            return {"ok": False, "error": "任务内容不能为空"}
        if not _cron_valid(sched):
            return {"ok": False, "error": "时间写法看不懂：用 HH:MM / every:30 / every:2h / 5 段 cron"}
        kind = "claw" if (kind or "").lower() == "claw" else "cmd"
        if cid:
            self._run("UPDATE crons SET name=?, kind=?, payload=?, sched=?, enabled=?, notify=? WHERE id=?",
                      (name, kind, payload, sched, 1 if enabled else 0,
                       1 if notify else 0, int(cid)), False)
            return {"ok": True, "id": int(cid)}
        cur = self.conn.execute(
            "INSERT INTO crons (name, kind, payload, sched, enabled, notify, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, kind, payload, sched, 1 if enabled else 0, 1 if notify else 0, time.time()))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def cron_toggle(self, cid: int, on=1) -> dict:
        self._run("UPDATE crons SET enabled=? WHERE id=?", (1 if on else 0, cid), False)
        return {"ok": True}

    def cron_del(self, cid: int) -> dict:
        self._run("DELETE FROM crons WHERE id=?", (cid,), False)
        return {"ok": True}

    def cron_mark(self, cid: int, ok: bool, out: str = "") -> dict:
        self._run(
            "UPDATE crons SET last_run=?, last_ok=?, last_out=?, "
            "runs=COALESCE(runs,0)+1, oks=COALESCE(oks,0)+? WHERE id=?",
            (time.time(), 1 if ok else 0, (out or "")[:2000], 1 if ok else 0, cid), False)
        return {"ok": True}

    def cron_due(self, now: float | None = None) -> list[dict]:
        """到点该跑的（前端轮询这个再逐条触发执行）。"""
        now = now or time.time()
        dt = datetime.datetime.fromtimestamp(now)
        out = []
        for c in self.cron_list():
            if not c.get("enabled"):
                continue
            last = c.get("last_run") or c.get("created") or 0
            if _cron_match(c.get("sched") or "", dt, last, now):
                out.append(c)
        return out

    # 114 日志查看器

    def log_add(self, level: str, msg: str, src: str = "") -> dict:
        msg = (msg or "").strip()
        if not msg:
            return {"ok": False}
        self._run("INSERT INTO wlog (level, src, msg, created) VALUES (?,?,?,?)",
                  ((level or "info")[:8], (src or "")[:24], msg[:4000], time.time()), False)
        # 只留最近 3000 条，别把库撑爆
        self._run("DELETE FROM wlog WHERE id NOT IN "
                  "(SELECT id FROM wlog ORDER BY id DESC LIMIT 3000)", (), False)
        return {"ok": True}

    def log_list(self, limit: int = 300, level: str = "") -> list[dict]:
        level = (level or "").strip()
        if level:
            return self._run("SELECT * FROM wlog WHERE level=? ORDER BY id DESC LIMIT ?",
                             (level, limit))
        return self._run("SELECT * FROM wlog ORDER BY id DESC LIMIT ?", (limit,))

    def log_stats(self) -> dict:
        rows = self._run("SELECT level, COUNT(*) AS n FROM wlog GROUP BY level")
        d = {r["level"]: r["n"] for r in rows}
        tot = self._run("SELECT COUNT(*) AS n FROM wlog")
        return {"total": (tot[0]["n"] if tot else 0),
                "err": d.get("err", 0), "warn": d.get("warn", 0),
                "ok": d.get("ok", 0), "info": d.get("info", 0)}

    def log_clear(self) -> dict:
        self._run("DELETE FROM wlog", (), False)
        return {"ok": True}

    # ---------------- M 域：技能库（115-120）----------------

    # 115 收藏钉顶

    def skill_fav_list(self) -> list[str]:
        return [r["key"] for r in self._run("SELECT key FROM skill_fav ORDER BY created DESC")]

    def skill_fav_toggle(self, key: str, on=None) -> dict:
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "没指定技能"}
        cur = self._run("SELECT key FROM skill_fav WHERE key=?", (key,))
        is_on = bool(cur)
        if on is None:
            on = not is_on
        on = bool(on)
        if on and not is_on:
            self._run("INSERT OR REPLACE INTO skill_fav (key, created) VALUES (?,?)",
                      (key, time.time()), False)
        elif (not on) and is_on:
            self._run("DELETE FROM skill_fav WHERE key=?", (key,), False)
        return {"ok": True, "key": key, "fav": on}

    # 118 运行统计

    def skill_runs_map(self) -> dict:
        return {r["key"]: r for r in self._run("SELECT * FROM skill_runs")}

    def skill_use(self, key: str, name: str = "", src: str = "", ok=1) -> dict:
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "没指定技能"}
        now = time.time()
        cur = self._run("SELECT key FROM skill_runs WHERE key=?", (key,))
        if cur:
            self._run(
                "UPDATE skill_runs SET runs=COALESCE(runs,0)+1, last_run=?, last_ok=?, "
                "name=COALESCE(NULLIF(?,''), name), src=COALESCE(NULLIF(?,''), src) WHERE key=?",
                (now, 1 if ok else 0, name or "", src or "", key), False)
        else:
            self._run(
                "INSERT INTO skill_runs (key, name, src, runs, last_run, last_ok, created) "
                "VALUES (?,?,?,?,?,?,?)",
                (key, name or "", src or "", 1, now, 1 if ok else 0, now), False)
        rows = self._run("SELECT * FROM skill_runs WHERE key=?", (key,))
        return {"ok": True, "row": rows[0] if rows else None}

    def skill_stats(self, limit: int = 20) -> dict:
        rows = self._run(
            "SELECT * FROM skill_runs ORDER BY runs DESC, last_run DESC LIMIT ?", (limit,))
        tot = self._run("SELECT COUNT(*) AS n, COALESCE(SUM(runs),0) AS s FROM skill_runs")
        return {"rows": rows,
                "skills": (tot[0]["n"] if tot else 0),
                "total": (tot[0]["s"] if tot else 0)}

    # 117 自定义技能目录（本地注册）

    def skill_dirs_list(self) -> list[dict]:
        return self._run("SELECT * FROM skill_dirs ORDER BY id DESC")

    def skill_dir_add(self, path: str, label: str = "") -> dict:
        path = (path or "").strip().strip('"').strip("'")
        if not path:
            return {"ok": False, "error": "没填目录"}
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            return {"ok": False, "error": "目录不存在：%s" % path}
        dup = self._run("SELECT id FROM skill_dirs WHERE path=?", (path,))
        if dup:
            return {"ok": True, "id": dup[0]["id"], "dup": True}
        base = os.path.basename(path.rstrip("/\\")) or "自定义"
        cur = self.conn.execute(
            "INSERT INTO skill_dirs (path, label, created) VALUES (?,?,?)",
            (path, (label or "").strip() or base, time.time()))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    def skill_dir_del(self, did: int) -> dict:
        self._run("DELETE FROM skill_dirs WHERE id=?", (did,), False)
        return {"ok": True}

