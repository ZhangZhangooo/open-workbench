"""设备间互传文件（电脑 ↔ 手机 / 平板）。

设计要点（都是踩过坑才这么定的）：

1. **不手写 multipart 解析**。手机浏览器直接 `fetch(url, {method:'POST', body: file})`
   把原始字节流丢过来，文件名走 query 参数 `?name=<urlencode(UTF-8)>`。
   multipart 的 boundary / 换行 / 编码坑太多，而且大文件还得边解边存。
2. **落盘分块进行**，绝不 `read()` 整个文件进内存 —— 传个 4G 的镜像不能把内存干爆，
   也能顺便边收边校验、超限立刻掐断。
3. **文件名不进 HTTP 头**。HTTP 头只能安全承载 latin-1，中文文件名塞进去必炸。
   所以一律走 query 参数（前端 encodeURIComponent，服务端 unquote）。
4. 这些接口**绝对不能**放进 server.py 的 `LOCAL_ONLY_PREFIX`，
   否则手机端根本传不了文件 —— 那是给终端/桥接/口令接口准备的保护名单。
5. 落盘文件名用 `<随机 id>__<净化后的原名>`：既能肉眼在文件夹里认出来，
   又不会因为名字里带 Windows 的非法字符（反斜杠、斜杠、冒号、星号、问号、
   双引号、尖括号、竖线）或者超长而写不进去。
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import time

BASE = os.path.dirname(os.path.abspath(__file__))
TRANSFER_DIR = os.path.join(BASE, "data", "transfer")
FILES_DIR = os.path.join(TRANSFER_DIR, "files")
for _d in (TRANSFER_DIR, FILES_DIR):
    os.makedirs(_d, exist_ok=True)

CHUNK = 1 << 16          # 64KB

DEFAULT_CFG = {
    "enabled": True,
    "quota_mb": 4096,    # 收件箱总容量上限（MB）；**0 = 不限**
    "max_mb": 2048,      # 单个文件上限（MB）；**0 = 不限**
    "keep_hours": 72,    # 上传时定死的保留时长；**0 = 永不过期**
}

CFG_KEY = "transferCfg"


# ---------------- 配置 ----------------

def cfg(st) -> dict:
    """读配置，缺的字段用默认值补齐（旧库升级后也能跑）。"""
    d = dict(DEFAULT_CFG)
    raw = ""
    try:
        raw = st.kv_get(CFG_KEY) or ""
    except Exception:  # noqa: BLE001
        raw = ""
    if raw:
        try:
            import json
            got = json.loads(raw)
            if isinstance(got, dict):
                d.update({k: got[k] for k in DEFAULT_CFG if k in got})
        except (ValueError, TypeError):
            pass
    for k in ("quota_mb", "max_mb", "keep_hours"):
        try:
            d[k] = max(0, int(d[k]))
        except (TypeError, ValueError):
            d[k] = DEFAULT_CFG[k]
    d["enabled"] = bool(d["enabled"])
    return d


def save_cfg(st, patch: dict) -> dict:
    """只覆盖传进来的字段，其余保持不动。返回合并后的完整配置。"""
    import json
    d = cfg(st)
    for k in DEFAULT_CFG:
        if k in patch and patch[k] is not None and patch[k] != "":
            d[k] = patch[k]
    for k in ("quota_mb", "max_mb", "keep_hours"):
        try:
            d[k] = max(0, int(d[k]))
        except (TypeError, ValueError):
            d[k] = DEFAULT_CFG[k]
    d["enabled"] = bool(d["enabled"])
    st.kv_set(CFG_KEY, json.dumps(d, ensure_ascii=False))
    return d


# ---------------- 杂活 ----------------

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name: str) -> str:
    """把用户给的名字洗成 Windows 上一定能落盘的样子。空名兜底成「未命名」。"""
    name = (name or "").strip().replace("\r", " ").replace("\n", " ")
    name = os.path.basename(name)              # 去掉任何路径成分
    name = _BAD.sub("_", name)
    name = name.strip(" .")                    # Windows 不允许结尾是点/空格
    if len(name) > 80:                         # 留出 id 前缀 + 扩展名的余量
        stem, ext = os.path.splitext(name)
        name = stem[: 80 - len(ext)] + ext
    return name or "未命名"


def human(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (n, u)
        n /= 1024.0
    return "%.1f TB" % n


def disk_free(path: str = FILES_DIR) -> int:
    """所在盘还剩多少字节。拿不到就返回 0（调用方当作"不知道"处理）。"""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


# ---------------- 收 / 存 ----------------

def sweep(st) -> int:
    """清掉已经到期的文件。

    过期时间在**上传那一刻**就按 keep_hours 定死了（写进 expire_at），
    所以这里不看 keep_hours —— 改了配置只影响之后传的，不会把老文件提前清掉。
    expire_at = 0 表示永不过期。返回清掉几个。
    """
    rows = st.transfer_expired(time.time())
    n = 0
    for r in rows:
        _unlink(r.get("path") or "")
        n += 1
    if n:
        st.transfer_del_ids([r["id"] for r in rows])
    return n


def _unlink(path_name: str) -> None:
    if not path_name:
        return
    p = os.path.join(FILES_DIR, os.path.basename(path_name))
    try:
        os.remove(p)
    except OSError:
        pass


def _drain(rfile, length, cap=32 << 20) -> None:
    """拒绝上传之前，先把对面还在发的数据读掉。

    不读会怎样：我们写完 400 就关连接，可客户端还在发文件 → Windows 直接
    ConnectionAborted，浏览器只会显示「网络错误」，看不到我们精心写的那句提示。
    cap 是防止有人拿一个超大的 Content-Length 吊着我们一直读盘；
    真正的第一道防线在前端（上传前就用 file.size 比过配置了）。
    """
    left = min(max(0, int(length or 0)), cap)
    while left > 0:
        chunk = rfile.read(min(CHUNK, left))
        if not chunk:
            break
        left -= len(chunk)


def add_file(st, name: str, rfile, length: int, ctype: str = "",
             src: str = "LAN", hours: int = 0) -> dict:
    """把 rfile 里的 length 个字节分块写进收件箱。

    返回 {"ok": True, "item": {...}} 或 {"ok": False, "error": "..."}。
    任何一步失败都会把半截文件删掉，不留垃圾。
    """
    try:
        length = max(0, int(length or 0))
    except (TypeError, ValueError):
        length = 0

    def _no(msg):
        _drain(rfile, length)
        return {"ok": False, "error": msg}

    c = cfg(st)
    if not c["enabled"]:
        return _no("主机把互传关掉了")

    name = safe_name(name)

    max_bytes = c["max_mb"] * 1024 * 1024
    if max_bytes and length > max_bytes:
        return _no("单个文件超过上限 %d MB" % c["max_mb"])

    used = total_bytes(st)
    quota = c["quota_mb"] * 1024 * 1024
    if quota and used + length > quota:
        return _no("收件箱放不下了（已用 %s / 上限 %s）"
                   % (human(used), human(quota)))

    free = disk_free()
    if free and length and free < length + 64 * 1024 * 1024:
        return _no("硬盘剩余空间不足（只剩 %s）" % human(free))

    tid = secrets.token_hex(8)
    disk = "%s__%s" % (tid, name)
    full = os.path.join(FILES_DIR, disk)

    got = 0
    try:
        with open(full, "wb") as f:
            while got < length:
                chunk = rfile.read(min(CHUNK, length - got))
                if not chunk:
                    break                      # 客户端断了
                f.write(chunk)
                got += len(chunk)
    except Exception as e:  # noqa: BLE001
        _unlink(disk)
        return {"ok": False, "error": "写入失败：%s" % e}

    if got != length:
        _unlink(disk)
        return {"ok": False, "error": "只收到 %s / %s，连接中断了"
                % (human(got), human(length))}

    keep = hours if hours and int(hours) > 0 else c["keep_hours"]
    now = time.time()
    expire_at = now + keep * 3600.0 if keep else 0.0
    st.transfer_add(tid, name, got, ctype or "", src or "", disk, now, expire_at)
    return {"ok": True, "item": _item(st, tid)}


def _item(st, tid: str):
    r = st.transfer_get(tid)
    if not r:
        return None
    return _shape(r)


def _shape(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "size": r["size"],
        "size_h": human(r["size"]),
        "type": r["ctype"] or "",
        "src": r["src"] or "",
        "created": r["created"],
        "expire_at": r.get("expire_at") or 0,
        "hits": r.get("hits") or 0,
        "last_hit": r.get("last_hit") or 0,
        "alive": os.path.isfile(os.path.join(FILES_DIR, r["path"] or "")),
    }


def list_items(st) -> dict:
    sweep(st)
    rows = st.transfer_list(400)
    items = [_shape(r) for r in rows]
    c = cfg(st)
    used = sum(i["size"] for i in items)
    return {
        "ok": True,
        "items": items,
        "cfg": c,
        "stats": {
            "count": len(items),
            "bytes": used,
            "bytes_h": human(used),
            "quota_mb": c["quota_mb"],
            "used_pct": (100.0 * used / (c["quota_mb"] * 1024 * 1024))
            if c["quota_mb"] else 0,
            "free_h": human(disk_free()),
        },
    }


def total_bytes(st) -> int:
    try:
        return int(st.transfer_total() or 0)
    except Exception:  # noqa: BLE001
        return 0


def path_of(st, tid: str):
    """拿到可下载的真实路径。找不到、或文件已经不在盘上，返回 None。"""
    r = st.transfer_get(tid)
    if not r:
        return None
    p = os.path.join(FILES_DIR, os.path.basename(r["path"] or ""))
    if not os.path.isfile(p):
        st.transfer_del_ids([tid])
        return None
    return p, r


def bump_hit(st, tid: str) -> None:
    try:
        st.transfer_hit(tid, time.time())
    except Exception:  # noqa: BLE001
        pass


def remove(st, ids) -> dict:
    """按 id 删。ids 为空就什么都不干（不能误删整箱，清空走 clear()）。"""
    ids = [str(i) for i in (ids or []) if i]
    if not ids:
        return {"ok": False, "error": "没指定要删哪个"}
    n = 0
    for tid in ids:
        r = st.transfer_get(tid)
        if not r:
            continue
        _unlink(r.get("path") or "")
        st.transfer_del_ids([tid])
        n += 1
    return {"ok": True, "removed": n}


def clear(st) -> dict:
    rows = st.transfer_list(100000)
    for r in rows:
        _unlink(r.get("path") or "")
    n = len(rows)
    st.transfer_wipe()
    return {"ok": True, "removed": n}
