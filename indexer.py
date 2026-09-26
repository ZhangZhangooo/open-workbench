"""全盘文件索引：后台线程扫描 C/D/E，结果落 SQLite。

只读不写：这个模块绝不创建、修改、删除用户的任何文件。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Callable

EXCLUDE_DIR_NAMES = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery", "perflogs",
    "windowsapps", "wudownloadcache", "softwaredistribution",
    "node_modules", ".git", "__pycache__", "site-packages",
    ".venv", "venv", "env", ".idea", ".vscode-server",
}

EXCLUDE_SUBSTR = (
    "appdata\\local\\temp",
    "appdata\\local\\cache",
    "appdata\\local\\inet",
    "appdata\\locallow",
    "appdata\\local\\microsoft\\windows\\inetcache",
    "appdata\\local\\crashdumps",
    "appdata\\local\\packages",
    "\\temp\\",
    "\\cache\\",
)

BATCH = 4000

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,
    name   TEXT,
    lname  TEXT,
    ext    TEXT,
    size   INTEGER,
    mtime  REAL,
    parent TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_lname ON files(lname);
CREATE INDEX IF NOT EXISTS idx_files_ext   ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_files_size  ON files(size);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _norm_ext(name: str) -> str:
    i = name.rfind(".")
    if i <= 0 or i == len(name) - 1:
        return ""
    return name[i + 1:].lower()


class Indexer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=8000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.progress = {
            "running": False,
            "scanned": 0,
            "current": "",
            "started": 0.0,
            "finished": 0.0,
            "error": "",
        }

    # ---------- 扫描 ----------

    @staticmethod
    def _skip_dir(low: str, name_l: str) -> bool:
        if name_l in EXCLUDE_DIR_NAMES:
            return True
        for s in EXCLUDE_SUBSTR:
            if s in low:
                return True
        return False

    def _write_batch(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)", rows
            )
            self._conn.commit()

    def _scan(self, roots: list[str], on_done: Callable[[], None] | None) -> None:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('last_scan_start', ?)",
                (str(time.time()),),
            )
            self._conn.commit()

            rows: list[tuple] = []
            scanned = 0
            t0 = time.time()

            for root in roots:
                if self._stop.is_set():
                    break
                stack = [root]
                while stack:
                    if self._stop.is_set():
                        break
                    d = stack.pop()
                    self.progress["current"] = d
                    try:
                        with os.scandir(d) as it:
                            for e in it:
                                if self._stop.is_set():
                                    break
                                try:
                                    if e.is_dir(follow_symlinks=False):
                                        low = e.path.lower()
                                        if not self._skip_dir(low, e.name.lower()):
                                            stack.append(e.path)
                                        continue
                                    st = e.stat(follow_symlinks=False)
                                except OSError:
                                    continue
                                rows.append((
                                    e.path,
                                    e.name,
                                    e.name.lower(),
                                    _norm_ext(e.name),
                                    st.st_size,
                                    st.st_mtime,
                                    d,
                                ))
                                scanned += 1
                                if len(rows) >= BATCH:
                                    with self._lock:
                                        conn.executemany(
                                            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                                            rows,
                                        )
                                        conn.commit()
                                    rows.clear()
                                    self.progress["scanned"] = scanned
                    except (OSError, PermissionError):
                        continue

            if rows:
                with self._lock:
                    conn.executemany(
                        "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)", rows
                    )
                    conn.commit()

            self.progress["scanned"] = scanned
            self.progress["finished"] = time.time() - t0
            self.build_dirs()
            self._conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('last_scan_at', ?)",
                (str(time.time()),),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            self.progress["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()
            self.progress["running"] = False
            self.progress["current"] = ""
            if on_done:
                on_done()

    def start_scan(self, roots: list[str], on_done: Callable[[], None] | None = None) -> bool:
        if self.progress["running"]:
            return False
        self._stop.clear()
        self.progress.update(
            running=True, scanned=0, current="", started=time.time(),
            finished=0.0, error="",
        )
        self._thread = threading.Thread(
            target=self._scan, args=(roots, on_done), daemon=True
        )
        self._thread.start()
        return True

    def stop_scan(self) -> None:
        self._stop.set()

    # ---------- 查询 ----------

    def search(
        self,
        q: str = "",
        ext: str = "",
        min_size: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        sql = "SELECT path, name, ext, size, mtime FROM files WHERE 1=1"
        args: list = []
        if q:
            sql += " AND lname LIKE ?"
            args.append(f"%{q.lower()}%")
        if ext:
            sql += " AND ext = ?"
            args.append(ext.lower().lstrip("."))
        if min_size:
            sql += " AND size >= ?"
            args.append(min_size)

        count_sql = "SELECT COUNT(*) FROM (" + sql + ")"
        total = self._conn.execute(count_sql, args).fetchone()[0]

        sql += " ORDER BY mtime DESC LIMIT ? OFFSET ?"
        args += [limit, offset]

        rows = self._conn.execute(sql, args).fetchall()
        return [
            {
                "path": r[0],
                "name": r[1],
                "ext": r[2],
                "size": r[3],
                "mtime": r[4],
            }
            for r in rows
        ], total

    def count(self) -> int:
        try:
            return self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        except sqlite3.Error:
            return 0

    def last_scan_at(self) -> float:
        try:
            r = self._conn.execute(
                "SELECT v FROM meta WHERE k='last_scan_at'"
            ).fetchone()
            return float(r[0]) if r else 0.0
        except (sqlite3.Error, ValueError):
            return 0.0

    def top_large(self, limit: int = 60, ext: str = "") -> list[dict]:
        sql = "SELECT path, name, ext, size, mtime FROM files"
        args: list = []
        if ext:
            sql += " WHERE ext = ?"
            args.append(ext.lower().lstrip("."))
        sql += " ORDER BY size DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [
            {"path": r[0], "name": r[1], "ext": r[2], "size": r[3], "mtime": r[4]}
            for r in rows
        ]

    def build_dirs(self) -> int:
        """把目录占用聚合进 dirs 表，供空间分析下钻用。"""
        with self._lock:
            self._conn.execute("DROP TABLE IF EXISTS dirs")
            self._conn.execute(
                "CREATE TABLE dirs (path TEXT PRIMARY KEY, size INTEGER, count INTEGER)"
            )
            self._conn.execute(
                "INSERT INTO dirs SELECT parent, SUM(size), COUNT(*) FROM files GROUP BY parent"
            )
            self._conn.commit()
            return self._conn.execute("SELECT COUNT(*) FROM dirs").fetchone()[0]

    def dir_usage(self, root: str) -> list[dict]:
        """root 的下一级各占多少空间。"""
        try:
            rows = self._conn.execute("SELECT path, size, count FROM dirs").fetchall()
        except sqlite3.Error:
            self.build_dirs()
            rows = self._conn.execute("SELECT path, size, count FROM dirs").fetchall()

        r = root.rstrip("\\")
        prefix = r + "\\"
        low = prefix.lower()
        agg: dict[str, list] = {}
        for path, size, cnt in rows:
            if not path.lower().startswith(low):
                continue
            rest = path[len(prefix):]
            if not rest:
                continue
            key = prefix + rest.split("\\")[0]
            a = agg.setdefault(key, [0, 0])
            a[0] += size or 0
            a[1] += cnt or 0
        out = [{"path": k, "size": v[0], "count": v[1]} for k, v in agg.items()]
        out.sort(key=lambda x: x["size"], reverse=True)
        return out[:80]

    def dup_groups(self, min_size: int = 1048576, limit: int = 40) -> list[dict]:
        """先按大小分组，同大小的再算哈希，找出真重复。"""
        import hashlib

        # 先用 SQL 找出「大小完全相同」的候选组（快），再对少量文件读头做哈希确认
        cand = self._conn.execute(
            "SELECT size, COUNT(*) c FROM files WHERE size >= ? "
            "GROUP BY size HAVING c > 1 ORDER BY size DESC LIMIT 80",
            (min_size,),
        ).fetchall()

        groups: list[dict] = []
        hashed = 0
        for size, _cnt in cand:
            if len(groups) >= limit or hashed >= 60:
                break
            paths = [
                r[0]
                for r in self._conn.execute(
                    "SELECT path FROM files WHERE size = ? LIMIT 12", (size,)
                ).fetchall()
            ]
            hh: dict[str, list[str]] = {}
            for p in paths:
                if hashed >= 60:
                    break
                try:
                    with open(p, "rb") as f:
                        head = f.read(1 << 17)
                    hashed += 1
                except OSError:
                    continue
                hh.setdefault(hashlib.md5(head).hexdigest(), []).append(p)
            for h, ps in hh.items():
                if len(ps) > 1:
                    groups.append({"size": size, "hash": h, "paths": ps})

        groups.sort(key=lambda g: g["size"], reverse=True)
        return groups[:limit]

    def top_exts(self, n: int = 12) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ext, COUNT(*) c, SUM(size) s FROM files "
            "WHERE ext <> '' GROUP BY ext ORDER BY c DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [{"ext": r[0], "count": r[1], "size": r[2] or 0} for r in rows]

    TEXT_EXT_SET = {
        "txt", "md", "json", "js", "ts", "py", "csv", "log", "ini", "xml",
        "yml", "yaml", "html", "css", "java", "c", "cpp", "h", "go", "rs",
        "sh", "bat", "toml", "sql", "rb", "php",
    }

    def text_candidates(self, limit: int = 4000) -> list[tuple]:
        """给全文检索用的候选文件：文本类、小于 5MB、按时间倒序。"""
        exts = sorted(self.TEXT_EXT_SET)
        ph = ",".join("?" * len(exts))
        sql = (
            f"SELECT path, name FROM files WHERE ext IN ({ph}) "
            "AND size < 5242880 ORDER BY mtime DESC LIMIT ?"
        )
        return self._conn.execute(sql, exts + [limit]).fetchall()

    def recent(self, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT path, name, ext, size, mtime FROM files ORDER BY mtime DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"path": r[0], "name": r[1], "ext": r[2], "size": r[3], "mtime": r[4]}
            for r in rows
        ]
