"""慢慢的工作台 — 本地服务端。

零第三方依赖，全部用 Python 标准库。服务只监听 127.0.0.1，不对外暴露。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indexer  # noqa: E402
import store  # noqa: E402
import mail as mailmod  # noqa: E402
import docswrite  # noqa: E402
import integrations  # noqa: E402
import sysinfo  # noqa: E402
import docsio  # noqa: E402
import conpty  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DATA = os.path.join(BASE, "data")
EXPORTS = os.path.join(BASE, "exports")
CONFIG_PATH = os.path.join(BASE, "config.json")
DB_PATH = os.path.join(DATA, "index.db")

for d in (DATA, EXPORTS):
    os.makedirs(d, exist_ok=True)

START_TIME = time.time()


def sysinfo_snapshot():
    """给前端顶栏状态条喂实时系统数据（复用 sysinfo.py）。"""
    snap = {"uptime": int(time.time() - START_TIME)}
    try:
        m = sysinfo.mem()
        snap["mem"] = {"total": m["total"], "used": m["used"], "pct": m["load"]}
    except Exception:
        snap["mem"] = {"total": 0, "used": 0, "pct": 0}
    try:
        snap["cpu"] = sysinfo.cpu(0.2)
    except Exception:
        snap["cpu"] = 0
    try:
        snap["disks"] = sysinfo.disks(["C:\\"])
    except Exception:
        snap["disks"] = []
    return snap

CONFIG_V = 2          # 配置结构版本，改字段语义时 +1 并加迁移分支

DEFAULT_CONFIG = {
    "_v": CONFIG_V,
    "ai": {
        "label": "Ollama 云端",
        "base_url": "https://ollama.com/v1",
        "api_key": "",
        "model": "gpt-oss:120b",
    },
    # OCR 走视觉模型。base_url / api_key 留空 = 复用上面 ai 的接口
    # （实测过：Ollama 云端只有 gemma4:31b 能看图，所以默认指它）
    "ocr": {
        "base_url": "",
        "api_key": "",
        "model": "gemma4:31b",
    },
    "graph": {
        "client_id": "",
        "tenant": "common",
        "access_token": "",
    },
    "mail": {
        "user": "",
        "password": "",
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "smtp_host": "smtp.163.com",
        "smtp_port": 465,
    },
    "scan_roots": ["C:\\", "D:\\", "E:\\"],
}

GRAPH_SCOPES = "User.Read Mail.Read Calendars.Read Tasks.Read offline_access"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, json.JSONDecodeError):
            saved = {}
        cfg.update(saved)
        # 2026-09-26 迁移：ocr 字段语义变了（留空 = 复用 AI 接口，不再是「没配」）。
        # 用版本标记而不是猜字段值——否则用户以后真在本机配了本地视觉模型，
        # 重启就会被这条规则误伤覆盖掉。只在「整段等于旧默认值」时才动。
        if int(saved.get("_v") or 1) < CONFIG_V:
            old = {"base_url": "http://127.0.0.1:11434/v1", "api_key": "ollama", "model": ""}
            o = cfg.get("ocr") or {}
            if all(o.get(k) == v for k, v in old.items()):
                cfg["ocr"] = json.loads(json.dumps(DEFAULT_CONFIG["ocr"]))
            cfg["_v"] = CONFIG_V
            try:
                save_config(cfg)
            except OSError:
                pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CFG = load_config()
IDX = indexer.Indexer(DB_PATH)
STORE = store.Store()

DAY = lambda: time.strftime("%Y-%m-%d")  # noqa: E731

# 视觉/OCR 模型的名字特征。Ollama 里能读图的都带这类关键词，
# 纯文本模型不会（gpt-oss / kimi / glm / deepseek / minimax 都不带）
VISION_HINT = ("llava", "vision", "vl", "minicpm", "internvl", "qwen2.5vl",
               "qwen-vl", "cogvlm", "moondream", "bakllava", "llama3.2-vision",
               "gemma3", "gemma4")

# 实测过的结论（2026-09-26 用一张写着 OK 42 的图逐个打过）：
#   Ollama 云端 17 个模型里只有 gemma4:31b 能看图，
#   其余要么 HTTP 400 "does not support image input"，要么 402 不在免费额度内。
# 名字猜不准，所以真正确定能不能看图要靠 _probe_vision() 实测，结果进缓存。
KNOWN_VISION = {"gemma4:31b"}
KNOWN_NO_VISION = {"gpt-oss:120b", "gpt-oss:20b", "nemotron-3-nano:30b",
                   "nemotron-3-super", "nemotron-3-ultra"}

_VISION_CACHE: dict[str, tuple[bool, float, str]] = {}
_VISION_TTL = 3600.0


def _looks_vision(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in VISION_HINT)


def _ocr_cfg() -> dict:
    """OCR 的三项配置，留空的字段回落到 AI 接口。"""
    o = CFG.get("ocr") or {}
    a = CFG.get("ai") or {}
    return {
        "base_url": (o.get("base_url") or a.get("base_url") or "").rstrip("/"),
        "api_key": o.get("api_key") or a.get("api_key") or "",
        "model": o.get("model") or "",
    }


def _probe_png() -> bytes:
    """手写一张写着 "OK 42" 的小 PNG，用来实测模型能不能看图。零依赖。"""
    import struct
    import zlib
    F = {
        'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
        'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
        '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
        '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
        ' ': ["00000"] * 7,
    }
    glyphs = [F.get(c, F[' ']) for c in "OK 42"]
    rows = []
    for y in range(7):
        line = []
        for g in glyphs:
            line.extend(g[y] + "0")
        rows.append([255 if c == '1' else 0 for c in line])
    rows += [[0] * len(rows[0]) for _ in range(3)]
    pad = 8
    W, H = len(rows[0]) + pad * 2, len(rows) + pad * 2
    raw = b""
    for _ in range(pad):
        raw += b"\x00" + b"\x00" * W
    for r in rows:
        raw += b"\x00" + bytes([0] * pad + r + [0] * pad)
    for _ in range(pad):
        raw += b"\x00" + b"\x00" * W

    def ck(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n"
            + ck(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 0, 0, 0, 0))
            + ck(b"IDAT", zlib.compress(raw, 9)) + ck(b"IEND", b""))


def _vision_call(base: str, key: str, model: str, prompt: str,
                 img_b64: str, timeout: int = 180) -> tuple[bool, str]:
    """带图调一次模型。返回 (是否成功, 文本或错误)。"""
    body = {"model": model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt}]}],
            "max_tokens": 2000}
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    msg = d["choices"][0]["message"]
    t = msg.get("content") or ""
    if isinstance(t, list):
        t = "".join(x.get("text", "") for x in t if isinstance(x, dict))
    return True, str(t).strip()


def _probe_vision(base: str, key: str, model: str, force: bool = False) -> dict:
    """实测这个模型能不能看图。结果缓存 1 小时，避免每次拉列表都打一遍。"""
    ck = f"{base}|{model}"
    now = time.time()
    if not force and ck in _VISION_CACHE:
        ok, ts, note = _VISION_CACHE[ck]
        if now - ts < _VISION_TTL:
            return {"ok": True, "vision": ok, "cached": True, "note": note}
    if not force and model in KNOWN_VISION:
        return {"ok": True, "vision": True, "cached": True, "note": "已知能看图"}
    try:
        b64 = base64.b64encode(_probe_png()).decode()
        _, txt = _vision_call(base, key, model, "图上写的是什么？只回答看到的字符。", b64, 60)
        ok = ("42" in txt) or ("OK" in txt.upper() and "4" in txt)
        note = f"实测回复「{txt[:40]}」"
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        ok = False
        note = f"HTTP{e.code}: " + ("不支持图片" if "image" in b.lower()
                                    else json.loads(b).get("error", {}).get("message", "")[:60]
                                    if b.strip().startswith("{") else b[:60])
    except Exception as e:  # noqa: BLE001
        ok, note = False, f"{type(e).__name__}: {str(e)[:60]}"
    _VISION_CACHE[ck] = (ok, now, note)
    return {"ok": True, "vision": ok, "cached": False, "note": note}

# ---------- Graph 登录状态 ----------

GRAPH_STATE = {
    "flow": None,
    "user_code": "",
    "verification_uri": "",
    "status": "idle",
    "error": "",
    "account": "",
}


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def graph_start() -> None:
    cid = CFG["graph"]["client_id"].strip()
    if not cid:
        GRAPH_STATE.update(status="need_client_id", error="还没填 Azure 应用的 client_id")
        return
    tenant = CFG["graph"]["tenant"].strip() or "common"
    try:
        flow = _post_form(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
            {"client_id": cid, "scope": GRAPH_SCOPES},
        )
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        GRAPH_STATE.update(status="error", error=f"{e.code} {detail}")
        return
    except Exception as e:  # noqa: BLE001
        GRAPH_STATE.update(status="error", error=str(e))
        return

    GRAPH_STATE.update(
        flow=flow,
        user_code=flow.get("user_code", ""),
        verification_uri=flow.get("verification_uri", ""),
        status="waiting",
        error="",
    )

    def poll():
        interval = int(flow.get("interval", 5))
        deadline = time.time() + int(flow.get("expires_in", 900))
        while time.time() < deadline and GRAPH_STATE["status"] == "waiting":
            time.sleep(interval)
            try:
                tok = _post_form(
                    f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": cid,
                        "device_code": flow["device_code"],
                    },
                )
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", "ignore")
                if '"authorization_pending"' not in err:
                    GRAPH_STATE.update(status="error", error=err[:300])
                    return
                continue
            except Exception as e:  # noqa: BLE001
                GRAPH_STATE.update(status="error", error=str(e))
                return
            if "access_token" in tok:
                CFG["graph"]["access_token"] = tok["access_token"]
                save_config(CFG)
                GRAPH_STATE.update(status="ok", error="", account="已登录")
                return
        if GRAPH_STATE["status"] == "waiting":
            GRAPH_STATE.update(status="error", error="授权超时")

    threading.Thread(target=poll, daemon=True).start()


def graph_get(path: str) -> dict:
    tok = CFG["graph"].get("access_token", "")
    if not tok:
        return {"error": "未登录"}
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0{path}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code} {e.read().decode('utf-8','ignore')[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def graph_today() -> dict:
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0).isoformat()
    end = now.replace(hour=23, minute=59, second=59).isoformat()
    q = urllib.parse.quote(start), urllib.parse.quote(end)
    cal = graph_get(
        f"/me/calendar/calendarView?startDateTime={q[0]}&endDateTime={q[1]}"
        f"&$select=subject,start,end,organizer&$orderby=start/dateTime"
    )
    mail = graph_get("/me/messages?$top=8&$select=subject,from,receivedDateTime")
    out = {"events": [], "mails": [], "error": ""}
    if "error" in cal:
        out["error"] = str(cal["error"])
    else:
        for e in cal.get("value", []):
            out["events"].append({
                "subject": e.get("subject", ""),
                "start": e.get("start", {}).get("dateTime", ""),
                "end": e.get("end", {}).get("dateTime", ""),
            })
    if "error" not in mail:
        for m in mail.get("value", []):
            fr = m.get("from", {}).get("emailAddress", {})
            out["mails"].append({
                "subject": m.get("subject", ""),
                "from": fr.get("name", "") or fr.get("address", ""),
                "at": m.get("receivedDateTime", ""),
            })
    return out


# ---------- xlsx（内置极简写入器，不依赖 openpyxl） ----------

def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path: str, header: list[str], rows: list[list]) -> None:
    sheet_rows = []
    cells = []
    for i, h in enumerate(header):
        cells.append(
            f'<c r="{_col(i+1)}1" t="inlineStr" s="1"><is><t>{_esc(str(h))}</t></is></c>'
        )
    sheet_rows.append(f'<row r="1">{"".join(cells)}</row>')

    for ri, row in enumerate(rows, start=2):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{_col(ci+1)}{ri}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{_esc(str(v))}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(sheet_rows) + "</sheetData></worksheet>"
    )

    ct = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    wb = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf xfId="0"/><xf fontId="1" applyFont="1" xfId="0"/></cellXfs>'
        "</styleSheet>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


# ---------- HTTP ----------

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # helpers

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _static(self, rel: str):
        path = os.path.normpath(os.path.join(STATIC, rel))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            self.send_error(404)
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _term_run(self, cmd: str) -> dict:
        """在本地机器执行一条命令，返回输出。仅本机服务可用，前端已注明风险。"""
        cmd = (cmd or "").strip()
        if not cmd:
            return {"ok": False, "error": "空命令"}
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True, text=True, timeout=30,
            )
            return {
                "ok": True, "code": r.returncode,
                "out": (r.stdout or "")[-8000:], "err": (r.stderr or "")[-4000:],
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "超时（30 秒）"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def _openclaw_context(self) -> str:
        """拼一份工作台真实状态快照，注入给 OpenClaw 当背景上下文。"""
        day = DAY()
        lines = []
        pend = STORE.today_pending(day)
        if pend:
            lines.append("今日待办（%s）：" % day)
            for t in pend[:12]:
                lines.append("  - " + (t.get("text") or ""))
        try:
            projs = STORE.projects_list() or []
        except Exception:
            projs = []
        if projs:
            active = [p for p in projs if (p.get("status") or "").lower()
                      not in ("完成", "done", "归档", "archived", "关闭")]
            if active:
                lines.append("进行中的项目：")
                for p in active[:8]:
                    line = "  - " + (p.get("name") or "")
                    if p.get("status"):
                        line += " [" + p["status"] + "]"
                    if p.get("next_step"):
                        line += " 下一步：" + p["next_step"]
                    lines.append(line)
        try:
            kbs = STORE.kb_list() or []
        except Exception:
            kbs = []
        if kbs:
            lines.append("资料库近期条目：")
            for k in kbs[:6]:
                lines.append("  - " + (k.get("title") or "(无标题)"))
        try:
            dl = STORE.daylog_get(day)
        except Exception:
            dl = ""
        if dl and dl.strip():
            lines.append("今日日志摘要：" + dl.strip()[:600])
        return "\n".join(lines) if lines else "(工作台暂无内容)"

    def _bridge_execute(self, action: str, payload: dict) -> dict:
        """把待审的神经桥操作真正落到工作台各模块。仅动作白名单内的才执行。"""
        try:
            if action == "today/add":
                return STORE.today_add(payload.get("day", DAY()),
                                        payload.get("text", ""),
                                        int(payload.get("project_id", 0) or 0))
            if action == "today/toggle":
                return STORE.today_toggle(int(payload.get("id", 0) or 0),
                                         int(payload.get("done", 1)))
            if action == "today/del":
                return STORE.today_del(int(payload.get("id", 0) or 0))
            if action == "kb/save":
                return STORE.kb_save(None, payload.get("title", ""),
                                     payload.get("body", ""), payload.get("tags", ""))
            if action == "kb/del":
                return STORE.kb_del(int(payload.get("id", 0) or 0))
            if action == "projects/save":
                return STORE.project_save(None, payload.get("name", ""),
                                          payload.get("status", "进行中"),
                                          payload.get("next_step", ""))
            if action == "projects/del":
                return STORE.project_del(int(payload.get("id", 0) or 0))
            if action == "cal/add":
                return STORE.event_save(None, payload.get("day", ""),
                                        payload.get("start", ""), payload.get("end", ""),
                                        payload.get("title", ""), payload.get("note", ""))
            if action == "cal/del":
                return STORE.event_del(int(payload.get("id", 0) or 0))
            if action == "meeting/add":
                return STORE.meeting_save(
                    None,
                    payload.get("day", ""),
                    payload.get("start", ""),
                    payload.get("end", ""),
                    payload.get("title", ""),
                    payload.get("location", ""),
                    payload.get("link", ""),
                    payload.get("attendees", ""),
                    payload.get("note", ""),
                    payload.get("remind_before", 10),
                    "openclaw",
                )
            if action == "meeting/del":
                return STORE.meeting_del(int(payload.get("id", 0) or 0))
            if action == "reminders/add":
                return STORE.rem_add(float(payload.get("at", time.time() + 60)),
                                     payload.get("text", ""))
            if action == "reminders/done":
                return STORE.rem_done(int(payload.get("id", 0) or 0),
                                     int(payload.get("done", 1)))
            if action == "reminders/del":
                return STORE.rem_del(int(payload.get("id", 0) or 0))
            if action == "inbox/add":
                return STORE.inbox_add(payload.get("text", ""))
            return {"ok": False, "error": "未知桥动作：" + action}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def _term_out(self):
        """SSE 流：持续把 PTY 累积输出推给前端（base64）。会话关闭时发 closed 事件。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                if not conpty.is_active():
                    # 首帧就发现没活着的会话，或中途退出
                    try:
                        self.wfile.write(b"event: closed\ndata: 1\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    break
                chunk = conpty.read_available()
                if chunk:
                    b64 = base64.b64encode(chunk).decode("ascii")
                    try:
                        self.wfile.write(f"data: {b64}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, OSError):
                        break
                time.sleep(0.04)
        except (BrokenPipeError, OSError, ConnectionResetError):
            pass

    def _to_trash(self, path: str):
        """送进 Windows 回收站（可恢复），不用 os.remove 直接删。
        走 PowerShell 的 VB FileSystem.DeleteFile（SendToRecycleBin）。
        成功判据以「文件是否已离开原位置」为准——PowerShell 退出码在本环境不稳。"""
        path = os.path.normpath(path)
        try:
            safe = path.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                f"'{safe}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
            r = subprocess.run(
                f'powershell.exe -NoProfile -Command "{ps}"',
                shell=True, capture_output=True, text=True, timeout=30,
            )
            # 文件已不在原处 = 已送回收站（VB 的 SendToRecycleBin 会移走文件）
            if not os.path.exists(path):
                return True, ""
            err = (r.stderr or "").strip()[:200] or "文件还在原地，回收站调用未生效"
            return False, err
        except subprocess.TimeoutExpired:
            return False, "回收站超时"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def _bulk(self, action: str, paths: list, dest: str) -> dict:
        """批量复制 / 移动 / 送回收站。删除只进回收站，不真删。"""
        if not isinstance(paths, list) or not paths:
            return {"ok": False, "error": "没有选中文件"}
        results = []
        for path in paths:
            try:
                if action == "copy":
                    if not dest or not os.path.isdir(dest):
                        results.append({"path": path, "ok": False, "error": "目标文件夹不存在"})
                    else:
                        shutil.copy2(path, dest)
                        results.append({"path": path, "ok": True})
                elif action == "move":
                    if not dest or not os.path.isdir(dest):
                        results.append({"path": path, "ok": False, "error": "目标文件夹不存在"})
                    else:
                        shutil.move(path, os.path.join(dest, os.path.basename(path)))
                        results.append({"path": path, "ok": True})
                elif action == "trash":
                    ok, msg = self._to_trash(path)
                    results.append({"path": path, "ok": ok, "error": msg})
                else:
                    results.append({"path": path, "ok": False, "error": "未知操作"})
            except Exception as e:  # noqa: BLE001
                results.append({"path": path, "ok": False, "error": str(e)})
        return {"ok": True, "action": action, "results": results}

    # routes

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path

        if p in ("/", "/index.html"):
            self._static("index.html")
            return
        if p.startswith("/static/"):
            self._static(p[len("/static/"):])
            return

        if p == "/api/status":
            self._json({
                "count": IDX.count(),
                "last_scan_at": IDX.last_scan_at(),
                "progress": IDX.progress,
                "counts": STORE.counts(),
                "config": {
                    "ai": {**CFG["ai"], "api_key_set": bool(CFG["ai"]["api_key"])},
                    "ocr": CFG.get("ocr") or {},
                    "mail": {
                        "user": CFG["mail"]["user"],
                        "configured": bool(CFG["mail"]["user"] and CFG["mail"]["password"]),
                        "imap_host": CFG["mail"]["imap_host"],
                        "smtp_host": CFG["mail"]["smtp_host"],
                    },
                    "wps": bool(integrations.find_wps("et")),
                    "graph": {
                        "client_id": CFG["graph"]["client_id"],
                        "client_id_set": bool(CFG["graph"]["client_id"]),
                        "tenant": CFG["graph"]["tenant"],
                        "logged_in": bool(CFG["graph"]["access_token"]),
                    },
                    "scan_roots": CFG["scan_roots"],
                },
                "graph_state": {
                    k: GRAPH_STATE[k] for k in ("status", "user_code", "verification_uri", "error", "account")
                },
            })
            return

        if p == "/api/sysinfo":
            self._json(sysinfo_snapshot())
            return

        if p == "/api/search":
            q = parse_qs(u.query)
            rows, total = IDX.search(
                q.get("q", [""])[0],
                q.get("ext", [""])[0],
                int(q.get("min_size", ["0"])[0]) or None,
                min(int(q.get("limit", ["200"])[0]), 1000),
                int(q.get("offset", ["0"])[0]),
            )
            self._json({"rows": rows, "total": total})
            return

        if p == "/api/stats":
            self._json({"count": IDX.count(), "exts": IDX.top_exts()})
            return

        if p == "/api/ai/models":
            self._ai_models()
            return

        if p == "/api/ocr/models":
            self._ocr_models()
            return

        if p == "/api/launch/list":
            self._json(integrations.launch_list())
            return

        if p == "/api/files/nl":
            self._nl_search(parse_qs(u.query).get("q", [""])[0])
            return

        if p == "/api/skills":
            self._json({
                "wb": integrations.workbuddy_skills(),
                "claw": integrations.openclaw_skills(),
            })
            return

        if p == "/api/claw/agents":
            self._json(integrations.openclaw_agents())
            return

        if p == "/api/claw/skills":
            self._json(integrations.openclaw_skills())
            return

        if p == "/api/claw/health":
            self._json(integrations.openclaw_health())
            return

        if p == "/api/claw/automations":
            self._json(integrations.openclaw_automations())
            return

        if p == "/api/claw/info":
            mjs = integrations._openclaw_mjs()
            self._json({
                "exists": os.path.isfile(mjs),
                "path": mjs,
                "node": os.path.isfile(integrations.NODE),
            })
            return

        if p == "/api/inbox":
            self._json({"rows": STORE.inbox_list()})
            return

        if p == "/api/today":
            day = parse_qs(u.query).get("day", [""])[0] or DAY()
            self._json({"rows": STORE.today_list(day)})
            return

        if p == "/api/kv":
            k = parse_qs(u.query).get("k", [""])[0]
            self._json({"v": STORE.kv_get(k)})
            return

        if p == "/api/events":
            q = parse_qs(u.query)
            month = q.get("month", [""])[0]
            if month:
                a, b = month + "-01", month + "-31"
                self._json({
                    "rows": STORE.events_list(month),
                    "tasks": STORE.tasks_due(a, b),
                })
                return
            a = q.get("from", [""])[0]
            b = q.get("to", [""])[0]
            self._json({"rows": STORE.events_range(a, b), "tasks": STORE.tasks_due(a, b)})
            return

        if p == "/api/today/pending":
            self._json({"rows": STORE.today_pending(parse_qs(u.query).get("day", [""])[0] or DAY())})
            return

        if p == "/api/daylog":
            day = parse_qs(u.query).get("day", [""])[0] or DAY()
            self._json({"day": day, "text": STORE.daylog_get(day)})
            return

        if p == "/api/lists":
            key = parse_qs(u.query).get("key", [""])[0]
            rows = STORE.list_items(key)
            for r in rows:
                try:
                    r["fields"] = json.loads(r["fields"]) if r.get("fields") else {}
                except (ValueError, TypeError):
                    r["fields"] = {}
            self._json({"rows": rows})
            return

        if p == "/api/room/list":
            self._json(STORE.room_list())
            return

        if p == "/api/clip":
            self._json({"rows": STORE.clip_list()})
            return

        if p == "/api/reminders":
            self._json({"rows": STORE.rem_list()})
            return

        if p == "/api/meetings":
            month = parse_qs(u.query).get("month", [""])[0]
            self._json({"rows": STORE.meeting_list(month) if month else STORE._run(
                "SELECT * FROM meetings ORDER BY day, start LIMIT 200")})
            return

        if p == "/api/file-tags":
            self._json({"rows": STORE.tags_all()})
            return

        if p == "/api/tags":
            self._json({"rows": STORE.tags_distinct()})
            return

        if p == "/api/files/top-large":
            q = parse_qs(u.query)
            self._json({
                "rows": IDX.top_large(
                    int(q.get("limit", ["60"])[0]), q.get("ext", [""])[0]
                )
            })
            return

        if p == "/api/files/usage":
            q = parse_qs(u.query)
            self._json({"rows": IDX.dir_usage(q.get("root", ["C:\\"])[0])})
            return

        if p == "/api/files/dup":
            q = parse_qs(u.query)
            self._json({
                "rows": IDX.dup_groups(
                    int(q.get("min_size", ["1048576"])[0]),
                    int(q.get("limit", ["40"])[0]),
                )
            })
            return

        if p == "/api/files/recent":
            self._json({"rows": IDX.recent(int(parse_qs(u.query).get("limit", ["500"])[0]))})
            return

        if p == "/api/grep":
            q = parse_qs(u.query)
            self._grep(q.get("q", [""])[0], int(q.get("limit", ["40"])[0]))
            return

        if p == "/api/projects":
            self._json({"rows": STORE.projects_board()})
            return

        if p == "/api/tasks":
            self._json({
                "rows": STORE.tasks_list(int(parse_qs(u.query).get("project_id", ["0"])[0])),
                "running": STORE.pomodoro_running(),
                "today": STORE.pomodoro_today(),
            })
            return

        if p == "/api/pomodoro":
            self._json({
                "running": STORE.pomodoro_running(),
                "today": STORE.pomodoro_today(),
                "rows": STORE.pomodoro_list(30),
            })
            return

        if p == "/api/plog":
            self._json({"rows": STORE.plog_list(int(parse_qs(u.query).get("project_id", ["0"])[0]))})
            return

        if p == "/api/notes":
            self._json({"rows": STORE.notes_list()})
            return

        if p == "/api/links":
            self._json({"rows": STORE.links_list()})
            return

        if p == "/api/kb":
            self._json({"rows": STORE.kb_list()})
            return

        if p == "/api/openclaw/history":
            self._json({"rows": STORE.openclaw_recent(
                int(parse_qs(u.query).get("limit", ["30"])[0] or 30))})
            return

        if p == "/api/bridge/pending":
            self._json({"rows": STORE.bridge_pending_list()})
            return

        # 交互终端输出流（SSE）：把 PTY 累积的输出以 base64 推给前端
        if p == "/api/term/out":
            self._term_out()
            return

        if p == "/api/chats":
            self._json({"rows": STORE.chat_list()})
            return

        if p == "/api/prompts":
            self._json({"rows": STORE.prompts_list()})
            return

        if p == "/api/connectors":
            self._json({"rows": CFG.get("connectors") or []})
            return

        if p == "/api/habits":
            self._json({"rows": STORE.habits_list()})
            return

        if p == "/api/backup":
            self._backup()
            return

        if p == "/api/chats/get":
            self._json(STORE.chat_get(int(parse_qs(u.query).get("id", ["0"])[0])))
            return

        if p == "/api/system":
            self._json({
                "cpu": sysinfo.cpu(),
                "mem": sysinfo.mem(),
                "disks": sysinfo.disks(["C:\\", "D:\\", "E:\\"]),
                "procs": sysinfo.procs(40),
                "cores": os.cpu_count(),
            })
            return

        if p == "/api/files/preview":
            self._preview(parse_qs(u.query).get("path", [""])[0])
            return

        if p == "/api/files/raw":
            self._raw(parse_qs(u.query).get("path", [""])[0])
            return

        if p == "/api/docs/read":
            self._json(docsio.read_any(parse_qs(u.query).get("path", [""])[0]))
            return

        if p == "/api/docs/wps":
            self._json({
                "wps": integrations.find_wps("wps"),
                "et": integrations.find_wps("et"),
            })
            return

        if p == "/api/mail/list":
            q = parse_qs(u.query)
            self._json(
                mailmod.MailClient(CFG["mail"]).list(
                    int(q.get("limit", ["30"])[0]),
                    q.get("unseen", ["0"])[0] == "1",
                    q.get("q", [""])[0],
                )
            )
            return

        if p == "/api/mail/diag":
            self._json(mailmod.MailClient(CFG["mail"]).diagnose())
            return

        if p == "/api/mail/read":
            q = parse_qs(u.query)
            self._json(
                mailmod.MailClient(CFG["mail"]).read(
                    q.get("uid", [""])[0], q.get("mark", ["1"])[0] != "0"
                )
            )
            return

        if p == "/api/graph/today":
            self._json(graph_today())
            return

        if p.startswith("/api/download/"):
            # 浏览器会把中文文件名百分号编码后发过来，必须先解回原样再拼路径，
            # 否则「总结_xxx.docx」这类名字永远 404。
            name = os.path.basename(unquote(p[len("/api/download/"):]))
            fp = os.path.join(EXPORTS, name)
            if not os.path.isfile(fp):
                self.send_error(404)
                return
            with open(fp, "rb") as f:
                data = f.read()
            ext = os.path.splitext(name)[1].lower()
            ctype = {
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # HTTP 头只能走 latin-1，直接塞中文会把连接搞断。
            # 所以：filename= 用 ASCII 兜底名，真正的中文名放 filename*=（RFC 5987）。
            ascii_name = "".join(
                c if (c.isascii() and c.isalnum() or c in "._-") else "_" for c in name
            ).strip("_.")
            if not ascii_name or ascii_name == ext.lstrip("."):
                ascii_name = "download" + ext
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}',
            )
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)

    def _backup(self):
        """把所有业务数据打成 JSON 下载。"""
        import datetime as _dt
        body = json.dumps(STORE.export_all(), ensure_ascii=False).encode("utf-8")
        name = "workbench-backup-" + _dt.date.today().isoformat() + ".json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        body = self._body()

        if p == "/api/scan":
            roots = body.get("roots") or CFG["scan_roots"]
            roots = [r for r in roots if os.path.exists(r)]
            if not roots:
                self._json({"ok": False, "error": "没有可用的盘符"})
                return
            CFG["scan_roots"] = roots
            save_config(CFG)
            started = IDX.start_scan(roots)
            self._json({"ok": started, "roots": roots})
            return

        if p == "/api/scan/stop":
            IDX.stop_scan()
            self._json({"ok": True})
            return

        if p == "/api/export":
            rows = body.get("rows") or []
            header = body.get("header") or ["名称", "大小(字节)", "类型", "修改时间", "路径"]
            name = f"export_{int(time.time())}.xlsx"
            fp = os.path.join(EXPORTS, name)
            write_xlsx(fp, header, rows)
            self._json({"ok": True, "file": name, "url": f"/api/download/{name}"})
            return

        if p == "/api/inbox/add":
            self._json(STORE.inbox_add(body.get("text", "").strip()))
            return

        if p == "/api/inbox/done":
            self._json(STORE.inbox_done(int(body.get("id", 0)), int(body.get("done", 1))))
            return

        if p == "/api/inbox/del":
            self._json(STORE.inbox_del(int(body.get("id", 0))))
            return

        if p == "/api/today/add":
            self._json(STORE.today_add(
                body.get("day") or DAY(), body.get("text", "").strip(),
                int(body.get("project_id", 0) or 0),
            ))
            return

        if p == "/api/today/toggle":
            self._json(STORE.today_toggle(int(body.get("id", 0)), int(body.get("done", 1))))
            return

        if p == "/api/today/del":
            self._json(STORE.today_del(int(body.get("id", 0))))
            return

        if p == "/api/today/roll":
            self._json(STORE.today_roll(body.get("from", ""), body.get("to", "") or DAY()))
            return

        if p == "/api/daylog/save":
            self._json(STORE.daylog_save(
                body.get("day") or DAY(), (body.get("text", "") or ""),
            ))
            return

        if p == "/api/lists/add":
            self._json(STORE.list_add(
                (body.get("key") or "").strip(), body.get("fields") or {},
            ))
            return

        if p == "/api/lists/del":
            self._json(STORE.list_del(int(body.get("id", 0))))
            return

        if p == "/api/room/get":
            self._json(STORE.room_get(int(body.get("id", 0) or body.get("rid", 0))))
            return

        if p == "/api/room/save":
            self._json(STORE.room_save(
                (body.get("name") or "未命名方案").strip(),
                body.get("data") or {}, int(body.get("id", 0) or 0),
            ))
            return

        if p == "/api/room/del":
            self._json(STORE.room_del(int(body.get("id", 0))))
            return

        # ---- 剪贴板历史 ----
        if p == "/api/clip/add":
            self._json(STORE.clip_add(body.get("text", "")))
            return
        if p == "/api/clip/del":
            self._json(STORE.clip_del(int(body.get("id", 0))))
            return
        if p == "/api/clip/clear":
            self._json(STORE.clip_clear())
            return

        # ---- 定时提醒 ----
        if p == "/api/reminders/add":
            at = body.get("at")
            try:
                at = float(at)
            except (TypeError, ValueError):
                at = time.time() + 60
            self._json(STORE.rem_add(at, body.get("text", "")))
            return
        if p == "/api/reminders/done":
            self._json(STORE.rem_done(int(body.get("id", 0)), int(body.get("done", 1))))
            return
        if p == "/api/reminders/del":
            self._json(STORE.rem_del(int(body.get("id", 0))))
            return

        # ---- 内置终端（在本地机器执行命令，仅本机服务可用）----
        if p == "/api/term/run":
            self._json(self._term_run(body.get("cmd", "")))
            return

        # ---- 交互终端（ConPTY 真终端，仅 Windows 10 1809+ 可用）----
        if p == "/api/term/start":
            ok, msg = conpty.start_session(
                cols=int(body.get("cols") or 120), rows=int(body.get("rows") or 30))
            self._json({"ok": ok, "error": msg})
            return

        if p == "/api/term/in":
            ok, msg = conpty.write_input(body.get("data", ""))
            self._json({"ok": ok, "error": msg})
            return

        if p == "/api/term/resize":
            conpty.resize(int(body.get("cols") or 0), int(body.get("rows") or 0))
            self._json({"ok": True})
            return

        # ---- 文件标签 / 批量 ----
        if p == "/api/file-tags":
            op = body.get("op", "add")
            if op == "del":
                self._json(STORE.tag_del(body.get("path", ""), body.get("tag", "")))
            else:
                self._json(STORE.tag_add(body.get("path", ""), body.get("tag", "")))
            return
        if p == "/api/files/bulk":
            self._json(self._bulk(
                body.get("action", ""), body.get("paths") or [], body.get("dest", ""),
            ))
            return

        if p == "/api/events/save":
            self._json(STORE.event_save(
                body.get("id") or None, body.get("day", ""), body.get("start", ""),
                body.get("end", ""), body.get("title", "").strip(), body.get("note", ""),
                body.get("source", "manual"),
            ))
            return

        if p == "/api/events/del":
            self._json(STORE.event_del(int(body.get("id", 0))))
            return

        if p == "/api/events/done":
            self._json(STORE.event_done(int(body.get("id", 0)), int(body.get("done", 1))))
            return

        if p == "/api/meetings/save":
            self._json(STORE.meeting_save(
                body.get("id") or None,
                body.get("day", ""),
                body.get("start", ""),
                body.get("end", ""),
                body.get("title", "").strip(),
                body.get("location", ""),
                body.get("link", ""),
                body.get("attendees", ""),
                body.get("note", ""),
                body.get("remind_before", 10),
                body.get("source", "manual"),
            ))
            return

        if p == "/api/meetings/del":
            self._json(STORE.meeting_del(int(body.get("id", 0))))
            return

        if p == "/api/kv/set":
            self._json(STORE.kv_set(body.get("k", ""), body.get("v", "")))
            return

        if p == "/api/mail/send":
            self._json(
                mailmod.MailClient(CFG["mail"]).send(
                    body.get("to", ""), body.get("subject", ""), body.get("body", "")
                )
            )
            return

        if p == "/api/mail/test":
            self._json(mailmod.MailClient(CFG["mail"]).diagnose())
            return

        if p == "/api/docs/ai-table":
            self._ai_table(body)
            return

        if p == "/api/docs/make":
            self._doc_make(body)
            return

        if p == "/api/docs/ai-doc":
            self._ai_doc(body)
            return

        if p == "/api/docs/summarize":
            self._doc_summarize(body)
            return

        if p == "/api/ocr/read":
            self._ocr_read(body)
            return

        if p == "/api/ocr/probe":
            self._ocr_probe(body)
            return

        if p == "/api/docs/ocr-pdf":
            self._ocr_pdf(body)
            return

        if p == "/api/docs/open":
            name = os.path.basename(body.get("file", ""))
            fp = os.path.join(EXPORTS, name) if name else ""
            self._json(integrations.open_with_wps(fp, body.get("app", "et")))
            return

        if p == "/api/openclaw":
            task = (body.get("task") or "").strip()
            if not task:
                self._json({"ok": False, "error": "空任务"})
                return
            ctx = ""
            if body.get("ctx", True):
                try:
                    ctx = self._openclaw_context()
                except Exception:
                    ctx = ""
            r = integrations.openclaw_run(task, ctx, int(body.get("timeout", 240)))
            # 运行记录写回工作台（统一活动），不依赖 OpenClaw 是否成功
            try:
                STORE.openclaw_log(
                    task, (r.get("reply") or r.get("error") or "")[:4000],
                    bool(r.get("ok")), "run",
                )
            except Exception:
                pass
            self._json(r)
            return

        # ---- OpenClaw 神经桥：写操作先入待审队列，用户确认后才执行 ----
        if p == "/api/skills/install":
            name = (body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "没指定技能名"})
                return
            self._json(integrations.openclaw_skill_install(name))
            return

        if p.startswith("/api/bridge/"):
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._json({"ok": False, "error": "仅本机可调用神经桥"}, 403)
                return
            if p == "/api/bridge/submit":
                action = (body.get("action") or "").strip()
                payload = body.get("payload")
                if not action or not isinstance(payload, dict):
                    self._json({"ok": False, "error": "action/payload 缺失"})
                    return
                pid = STORE.bridge_enqueue(action, payload)
                self._json({"ok": True, "pending": True, "id": pid,
                            "hint": "已提交，请在工作台「OpenClaw → 待确认」里确认后才会执行"})
                return
            if p == "/api/bridge/confirm":
                rid = int(body.get("id", 0) or 0)
                row = STORE.bridge_get(rid)
                if not row or row.get("status") != "pending":
                    self._json({"ok": False, "error": "找不到待确认项"})
                    return
                try:
                    pl = json.loads(row.get("payload") or "{}")
                except Exception:
                    pl = {}
                res = self._bridge_execute(row["action"], pl)
                STORE.bridge_resolve(rid, "done" if res.get("ok") else "failed",
                                     str(res.get("error") or "ok"))
                self._json({"ok": True, "result": res})
                return
            if p == "/api/bridge/reject":
                rid = int(body.get("id", 0) or 0)
                STORE.bridge_resolve(rid, "rejected", "用户拒绝")
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": "未知桥端点"}, 404)
            return

        if p == "/api/projects/save":
            self._json(STORE.project_save(
                body.get("id") or None, body.get("name", ""),
                body.get("status", ""), body.get("next_step", ""),
            ))
            return

        if p == "/api/projects/del":
            self._json(STORE.project_del(int(body.get("id", 0))))
            return

        if p == "/api/tasks/save":
            self._json(STORE.task_save(
                body.get("id") or None, int(body.get("project_id", 0) or 0),
                body.get("title", ""), body.get("state", "待办"),
                body.get("due", ""),
            ))
            return

        if p == "/api/tasks/state":
            self._json(STORE.task_state(int(body.get("id", 0)), body.get("state", "待办")))
            return

        if p == "/api/tasks/del":
            self._json(STORE.task_del(int(body.get("id", 0))))
            return

        if p == "/api/tasks/due":
            self._json(STORE.task_due(int(body.get("id", 0)), body.get("due", "")))
            return

        if p == "/api/pomodoro/start":
            self._json(STORE.pomodoro_start(
                int(body.get("project_id", 0) or 0),
                int(body.get("task_id", 0) or 0),
                body.get("title", ""),
            ))
            return

        if p == "/api/pomodoro/stop":
            self._json(STORE.pomodoro_stop(int(body.get("id", 0))))
            return

        if p == "/api/plog/add":
            self._json(STORE.plog_add(
                int(body.get("project_id", 0) or 0),
                body.get("text", ""), body.get("kind", "log"),
            ))
            return

        if p == "/api/plog/del":
            self._json(STORE.plog_del(int(body.get("id", 0))))
            return

        if p == "/api/notes/save":
            self._json(STORE.note_save(
                body.get("id") or None, body.get("title", ""),
                body.get("body", ""), body.get("tags", ""),
            ))
            return

        if p == "/api/notes/del":
            self._json(STORE.note_del(int(body.get("id", 0))))
            return

        if p == "/api/links/add":
            self._json(STORE.link_add(
                body.get("title", ""), body.get("url", ""), body.get("tags", "")
            ))
            return

        if p == "/api/links/del":
            self._json(STORE.link_del(int(body.get("id", 0))))
            return

        if p == "/api/kb/save":
            self._json(STORE.kb_save(
                body.get("id") or None,
                (body.get("title") or "").strip(),
                body.get("body", ""),
                (body.get("tags") or "").strip(),
                (body.get("source") or "manual").strip(),
                (body.get("source_path") or "").strip(),
            ))
            return

        if p == "/api/kb/del":
            self._json(STORE.kb_del(int(body.get("id", 0))))
            return

        if p == "/api/kb/import":
            self._kb_import(body)
            return

        if p == "/api/kb/ask":
            self._kb_ask(body)
            return

        if p == "/api/chats/save":
            self._json(STORE.chat_save(
                body.get("title", ""), body.get("model", ""), body.get("messages", []),
                body.get("id") or None,
            ))
            return

        if p == "/api/prompts/save":
            self._json(STORE.prompt_save(
                body.get("id") or None, body.get("title", ""),
                body.get("body", ""), body.get("tags", ""),
            ))
            return

        if p == "/api/prompts/del":
            self._json(STORE.prompt_del(int(body.get("id", 0))))
            return

        if p == "/api/backup/import":
            self._json(STORE.import_all(body.get("data") or {}, body.get("mode", "merge")))
            return

        if p == "/api/habits/save":
            self._json(STORE.habit_save(
                body.get("id") or None, body.get("name", ""), body.get("note", "")))
            return

        if p == "/api/habits/del":
            self._json(STORE.habit_del(int(body.get("id", 0))))
            return

        if p == "/api/habits/toggle":
            self._json(STORE.habit_toggle(
                int(body.get("id", 0)), body.get("day") or DAY()))
            return

        if p == "/api/system/kill":
            pid = int(body.get("pid", 0))
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], timeout=10, capture_output=True)
                self._json({"ok": True})
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)})
            return

        if p == "/api/config":
            for k, v in body.items():
                if k in ("ai", "graph", "ocr"):
                    CFG[k].update(v)
                else:
                    CFG[k] = v
            save_config(CFG)
            self._json({"ok": True})
            return

        if p == "/api/connectors/push":
            cid = body.get("id")
            cons = CFG.get("connectors") or []
            c = next((x for x in cons if x.get("id") == cid), None)
            if not c:
                self._json({"ok": False, "error": "找不到这个连接器（去设置里添加一个）"})
                return
            self._json(integrations.connector_push(c, body.get("title", "工作台"), body.get("content", "")))
            return

        if p == "/api/ai/chat":
            self._ai_stream(body)
            return

        if p == "/api/ai/models":
            self._ai_models()
            return

        if p == "/api/graph/login":
            if body.get("client_id"):
                CFG["graph"]["client_id"] = body["client_id"].strip()
                CFG["graph"]["tenant"] = (body.get("tenant") or "common").strip()
                save_config(CFG)
            graph_start()
            self._json({
                "status": GRAPH_STATE["status"],
                "user_code": GRAPH_STATE["user_code"],
                "verification_uri": GRAPH_STATE["verification_uri"],
                "error": GRAPH_STATE["error"],
            })
            return

        if p == "/api/open":
            target = body.get("path", "")
            if not target or not os.path.exists(target):
                self._json({"ok": False, "error": "路径不存在"})
                return
            try:
                if os.path.isdir(target):
                    subprocess.Popen(["explorer", target])
                else:
                    os.startfile(target)  # noqa: S606
                self._json({"ok": True})
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)})
            return

        self.send_error(404)

    # AI

    def _ai_stream(self, body: dict):
        ai = CFG["ai"]
        base = ai["base_url"].rstrip("/")
        if not base:
            self._json({"error": "还没配置 AI 接口地址"})
            return
        payload = {
            "model": body.get("model") or ai["model"],
            "messages": body.get("messages", []),
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        if ai["api_key"]:
            headers["Authorization"] = f"Bearer {ai['api_key']}"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(obj):
            raw = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(raw)
                self.wfile.flush()
            except (BrokenPipeError, OSError):
                return False
            return True

        try:
            req = urllib.request.Request(
                f"{base}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                for line in r:
                    s = line.decode("utf-8", "ignore").strip()
                    if not s.startswith("data:"):
                        continue
                    s = s[5:].strip()
                    if s == "[DONE]":
                        break
                    try:
                        obj = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    delta = ""
                    ch = obj.get("choices") or []
                    if ch:
                        d = ch[0].get("delta") or {}
                        # 只转发正文 content；推理模型的思考过程（reasoning）直接丢弃，不显示
                        delta = d.get("content") or ""
                        # 个别模型会把 <think>…</think> 直接塞进 content，剥离掉
                        if delta:
                            delta = re.sub(r"<think>[\s\S]*?</think>", "", delta, flags=re.IGNORECASE)
                    if delta:
                        if not emit({"delta": delta}):
                            break
            emit({"done": True})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            emit({"error": f"{e.code} {detail}"})
        except Exception as e:  # noqa: BLE001
            emit({"error": str(e)})
        try:
            self.close_connection = True
        except Exception:  # noqa: BLE001
            pass

    def _ai_models(self):
        ai = CFG["ai"]
        base = ai["base_url"].rstrip("/")
        headers = {}
        if ai["api_key"]:
            headers["Authorization"] = f"Bearer {ai['api_key']}"
        try:
            req = urllib.request.Request(f"{base}/models", headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            names = [m.get("id") or m.get("name") for m in data.get("data", [])]
            self._json({"ok": True, "models": [n for n in names if n]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": str(e)})


    def _nl_search(self, q: str):
        """自然语言找文件：先让模型翻成检索条件，再走索引。"""
        if not q.strip():
            self._json({"ok": False, "error": "说点什么"})
            return
        cond = integrations.nl_to_query(q, CFG["ai"])
        kw = cond.get("kw") or ""
        rows, total = IDX.search(
            kw, cond.get("ext") or "",
            (cond.get("min_size_mb") or 0) * 1024 * 1024 or None,
            60, 0,
        )
        # 路径片段和时间窗在 SQL 层没做，这里过滤
        p = (cond.get("path") or "").lower()
        if p:
            rows = [r for r in rows if p in (r.get("path") or "").lower()]
        days = cond.get("days") or 0
        if days:
            cut = time.time() - days * 86400
            rows = [r for r in rows if (r.get("mtime") or 0) >= cut]
        self._json({
            "ok": True, "cond": cond, "rows": rows[:40], "total": len(rows),
            "note": cond.get("note") or "",
        })

    def _ocr_models(self):
        """列出能用来做 OCR 的模型：云端一份 + 本机 Ollama 一份。

        「能不能看图」不靠名字猜 —— 先套已知结论，没有的再实测（有缓存）。
        """
        o = _ocr_cfg()
        out = {"ok": True, "cur": o["model"], "base": o["base_url"],
               "cloud": [], "local": [], "vision": [], "errors": []}

        def fetch(base, key, tag):
            try:
                req = urllib.request.Request(
                    base + "/models",
                    headers={"Authorization": f"Bearer {key}"} if key else {})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return [m.get("id") or m.get("name") for m in data.get("data", []) if
                        (m.get("id") or m.get("name"))]
            except Exception as e:  # noqa: BLE001
                out["errors"].append(f"{tag}拉不到：{str(e)[:80]}")
                return []

        models = []
        if o["base_url"]:
            models += [(n, o["base_url"], o["api_key"], "cloud") for n in fetch(o["base_url"], o["api_key"], "云端")]
        # 本机 11434 也列一份，方便以后 pull 了本地视觉模型直接选
        local = fetch("http://127.0.0.1:11434/v1", "ollama", "本机")
        models += [(n, "http://127.0.0.1:11434/v1", "ollama", "local") for n in local]

        for name, base, key, src in models:
            guess = name in KNOWN_VISION or (name not in KNOWN_NO_VISION and _looks_vision(name))
            item = {"name": name, "src": src, "base": base, "guess": guess,
                    "vision": None, "note": ""}
            out[src].append(item)
        out["cloud_names"] = [x["name"] for x in out["cloud"]]
        out["local_names"] = [x["name"] for x in out["local"]]
        self._json(out)

    def _ocr_probe(self, body: dict):
        """实测某个模型能不能看图。force=1 忽略缓存。"""
        name = (body.get("model") or "").strip()
        if not name:
            self._json({"ok": False, "error": "没指定模型"})
            return
        o = _ocr_cfg()
        base = (body.get("base_url") or o["base_url"]).rstrip("/")
        key = body.get("api_key") or o["api_key"]
        r = _probe_vision(base, key, name, bool(body.get("force")))
        r["model"] = name
        self._json(r)

    def _ocr_read(self, body: dict):
        """拿视觉模型读一张图：把图 base64 发给模型，让它把字吐出来。"""
        import mimetypes
        path = (body.get("path") or "").strip()
        prompt = (body.get("prompt") or "").strip() or \
            "把图上的文字原样读出来，保留段落和表格结构。读不出来就说读不出来，不要编。"
        o = _ocr_cfg()
        if not o["model"]:
            self._json({"ok": False, "error": "还没选 OCR 模型，去设置页选一个（gemma4:31b 能用）"})
            return
        if not path or not os.path.isfile(path):
            self._json({"ok": False, "error": "文件不存在"})
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            self._json({"ok": False, "error": f"{ext} 不是图片，OCR 只吃图片"})
            return
        try:
            raw = open(path, "rb").read()
        except OSError as e:
            self._json({"ok": False, "error": f"读不了：{e}"})
            return
        if len(raw) > 12 << 20:
            self._json({"ok": False, "error": "图太大了（超过 12MB），先压缩一下"})
            return
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext) or \
            (mimetypes.types_map.get(ext) or "image/png")
        b64 = base64.b64encode(raw).decode()
        try:
            # 接口只认 png 的 data URL 前缀判断，统一按真实 mime 传
            body_req = {"model": o["model"],
                        "messages": [{"role": "user", "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:{mime};base64,{b64}"}},
                            {"type": "text", "text": prompt}]}],
                        "max_tokens": 4000}
            req = urllib.request.Request(
                o["base_url"] + "/chat/completions",
                data=json.dumps(body_req).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         **({"Authorization": f"Bearer {o['api_key']}"} if o["api_key"] else {})})
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.loads(r.read().decode("utf-8"))
            msg = d["choices"][0]["message"]
            t = msg.get("content") or ""
            if isinstance(t, list):
                t = "".join(x.get("text", "") for x in t if isinstance(x, dict))
            self._json({"ok": True, "text": str(t).strip(), "model": o["model"],
                        "name": os.path.basename(path), "bytes": len(raw)})
        except urllib.error.HTTPError as e:
            b = e.read().decode("utf-8", "replace")
            self._json({"ok": False, "error": f"接口报 {e.code}：{b[:200]}"})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"})

    def _ocr_pdf(self, body: dict):
        """扫描版 PDF：整份一次性 OCR。

        渲染整份（默认，不限制页数）→ 逐页发给视觉模型 → 用 SSE 边读边推进度。
        `max_pages` 可选兜底，传了就只渲染前 N 页；不传 = 读完整份。
        一组 SSE 事件：start(总页数) → 每页 progress → done(全文) / error。
        """
        path = (body.get("path") or "").strip()
        mp = body.get("max_pages") or 0
        max_pages = int(mp) if mp else 0     # 0 = 全部页
        o = _ocr_cfg()

        # 整条都走 SSE：先发头，后面要么发 error 事件，要么发 start/progress/done
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(obj):
            raw = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(raw)
                self.wfile.flush()
                return True
            except (BrokenPipeError, OSError):
                return False

        def fail(msg):
            emit({"type": "error", "error": msg})
            self.close_connection = True

        if not path or not os.path.isfile(path):
            fail("文件不存在")
            return
        if not path.lower().endswith(".pdf"):
            fail("不是 PDF")
            return
        if not o["model"]:
            fail("还没选 OCR 模型（设置页里选 gemma4:31b）")
            return

        r = docsio.pdf_render(path, max_pages=max_pages or None)
        if not r.get("ok"):
            fail(r.get("error", "PDF 渲染失败"))
            return

        pages = r["pages"]
        total = r["total"]
        name = os.path.basename(path)
        prompt = (body.get("prompt") or "").strip() or \
            "把这一页上的文字原样读出来，保留段落结构。读不出来就说读不出来，不要编。"
        emit({"type": "start", "total": total, "model": o["model"], "name": name})

        out, failed = [], []
        for i, raw in enumerate(pages, 1):
            emit({"type": "progress", "page": i, "total": total})
            b64 = base64.b64encode(raw).decode()
            try:
                _, t = _vision_call(o["base_url"], o["api_key"], o["model"], prompt, b64, 240)
                out.append(f"<!-- 第 {i} 页 -->\n{t}")
            except urllib.error.HTTPError as e:
                failed.append(f"第 {i} 页：HTTP{e.code}")
                out.append(f"<!-- 第 {i} 页：识别失败 HTTP{e.code} -->")
            except Exception as e:  # noqa: BLE001
                failed.append(f"第 {i} 页：{type(e).__name__}")
                out.append(f"<!-- 第 {i} 页：识别失败 -->")

        emit({"type": "done", "text": "\n\n".join(out), "model": o["model"],
              "name": name, "total": total, "done": len(pages),
              "failed": failed, "rendered": r["rendered"]})
        self.close_connection = True

    def _grep(self, q: str, limit: int):
        """全文检索：只在文本类文件里找，限制扫描量避免卡死。"""
        if not q.strip():
            self._json({"ok": False, "error": "空的关键词"})
            return
        low = q.lower()
        hits = []
        scanned = 0
        for path, name in IDX.text_candidates(4000):
            scanned += 1
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read(2 << 20)
            except OSError:
                continue
            i = txt.lower().find(low)
            if i < 0:
                continue
            hits.append({
                "path": path,
                "name": name,
                "snippet": txt[max(0, i - 60): i + 160].replace("\n", " ").replace("\r", ""),
            })
            if len(hits) >= limit:
                break
        self._json({"ok": True, "hits": hits, "scanned": scanned})

    # ---------- 文件预览 ----------

    TEXT_EXT = {
        "txt", "md", "json", "js", "ts", "py", "csv", "log", "ini", "xml",
        "yml", "yaml", "html", "css", "java", "c", "cpp", "h", "go", "rs",
        "sh", "bat", "toml", "sql", "rb", "php",
    }

    IMG_EXT = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
        "svg": "image/svg+xml",
    }

    def _preview(self, path: str):
        if not path or not os.path.isfile(path):
            self._json({"kind": "none", "hint": "文件不存在"})
            return
        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower().lstrip(".")

        if ext in self.IMG_EXT:
            self._json({
                "kind": "image",
                "name": name,
                "url": "/api/files/raw?path=" + urllib.parse.quote(path),
            })
            return

        if ext in self.TEXT_EXT:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(60000)
                self._json({
                    "kind": "text",
                    "name": name,
                    "text": text,
                    "truncated": len(text) >= 60000,
                })
            except OSError as e:
                self._json({"kind": "none", "hint": str(e)})
            return

        self._json({
            "kind": "none",
            "name": name,
            "hint": f".{ext or '未知'} 没法直接预览，点右边的「打开」用本机程序看",
        })

    def _raw(self, path: str):
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        ext = os.path.splitext(path)[1].lower()
        mime = self.IMG_EXT.get(ext.lstrip("."), "application/octet-stream")
        try:
            with open(path, "rb") as f:
                data = f.read(24 << 20)
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ai_table(self, body: dict):
        prompt = body.get("prompt", "").strip()
        if not prompt:
            self._json({"ok": False, "error": "还没描述要什么表"})
            return

        ask = (
            "按下面的要求生成一张表格。严格要求：只输出一个 JSON 二维数组，"
            "第一行为表头，不要解释、不要额外文字。\n要求：" + prompt
        )
        r = integrations.ai_complete(ask, CFG["ai"])
        if not r.get("ok"):
            self._json({"ok": False, "error": r.get("error")})
            return

        arr = integrations.extract_json_array(r.get("text", ""))
        if not arr or not isinstance(arr[0], list):
            self._json({"ok": False, "error": "模型没返回规范的表格", "raw": r.get("text", "")[:400]})
            return

        header = [str(x) for x in arr[0]]
        rows = [[str(c) for c in row] for row in arr[1:]]
        name = f"ai_table_{int(time.time())}.xlsx"
        fp = os.path.join(EXPORTS, name)
        write_xlsx(fp, header, rows)
        self._json({
            "ok": True,
            "file": name,
            "url": f"/api/download/{name}",
            "header": header,
            "rows": rows,
        })

    # ---------- 文档：生成（WPS 全套） ----------

    def _doc_make(self, body: dict):
        kind = (body.get("kind") or "word").strip()
        md = body.get("md", "")
        title = (body.get("title") or "").strip() or docswrite.md_title(md, "文档")
        if not md.strip():
            self._json({"ok": False, "error": "没有内容可写"})
            return

        if kind in ("excel", "xlsx", "表格"):
            blocks = docswrite.md_to_blocks(md)
            tbl = next((b for b in blocks if b["type"] == "table"), None)
            if not tbl or len(tbl["rows"]) < 2:
                self._json({"ok": False,
                            "error": "内容里没找到表格。Excel 需要用 Markdown 表格（| 列 | 列 |）"})
                return
            rows = tbl["rows"]
            name = docswrite.safe_name(title, "excel")
            write_xlsx(os.path.join(EXPORTS, name), rows[0], rows[1:])
            self._json({"ok": True, "file": name, "url": f"/api/download/{name}",
                        "title": title, "note": f"{len(rows) - 1} 行 × {len(rows[0])} 列"})
            return

        name = docswrite.safe_name(title, kind)
        r = docswrite.write_any(os.path.join(EXPORTS, name), kind, md, title)
        if not r.get("ok"):
            self._json(r)
            return
        self._json({"ok": True, "file": name, "url": f"/api/download/{name}",
                    "title": title, "note": r.get("note", ""), "kind": r.get("kind")})

    def _ai_doc(self, body: dict):
        """用模型写出 Markdown，再落成 docx / pptx / xlsx。"""
        kind = (body.get("kind") or "word").strip()
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            self._json({"ok": False, "error": "还没说要写什么"})
            return

        spec = {
            "word": "一份 Word 文档（.docx）",
            "ppt": "一份演示文稿（.pptx）",
            "excel": "一张表格（.xlsx）",
        }.get(kind, "一份文档")

        rule = {
            "word": ("用 Markdown 输出。第一行必须是 # 标题，正文用 ## 分小节，"
                     "列举用 - ，需要表格时用 Markdown 表格语法。不要写代码块围栏。"),
            "ppt": ("用 Markdown 输出。第一行 # 是整副演示的标题，之后每个 ## 开始一页，"
                    "每页下面用 - 列要点，每页要点不超过 6 条。不要写代码块围栏。"),
            "excel": ("只输出一个 Markdown 表格，第一行为表头，"
                      "不要任何解释文字，不要代码块围栏。"),
        }.get(kind, "用 Markdown 输出。")

        r = integrations.ai_complete(
            f"请按要求写{spec}。内容主题：{prompt}\n\n输出规则：{rule}\n\n"
            "严格要求：只输出正文内容本身，不要开头寒暄、不要结尾总结、"
            "不要说「好的」「以下是」之类的话、不要用 ``` 包裹。",
            CFG["ai"],
        )
        if not r.get("ok"):
            self._json({"ok": False, "error": r.get("error")})
            return

        md = _strip_fence(r.get("text", ""))
        if len(md.strip()) < 10:
            self._json({"ok": False, "error": "模型没写出内容", "raw": r.get("text", "")[:300]})
            return
        self._doc_make({"kind": kind, "md": md})

    def _doc_summarize(self, body: dict):
        """导入一个文件，抽文字喂给模型：总结 / 出报告 / 挑毛病。"""
        path = body.get("path", "")
        mode = (body.get("mode") or "summary").strip()
        extra = (body.get("extra") or "").strip()

        rd = docsio.read_any(path)
        if not rd.get("ok"):
            self._json({"ok": False, "error": rd.get("error")})
            return

        payload = _payload(rd)
        if len(payload.strip()) < 20:
            self._json({"ok": False, "error": "这个文件里几乎没抽出文字，总结不了"})
            return

        ask = {
            "summary": "通读下面这份材料，给出一份总结。要求："
                       "先用 3~5 条要点说清核心内容，再补一段 200 字以内的概述。"
                       "只基于材料本身，不要添加材料里没有的信息。",
            "report": "下面是一张表格的数据。请写一份汇总报告："
                      "先说这份表在记什么、一共多少条，再给出关键发现和量化结论，"
                      "最后给 2~3 条可执行建议。数字必须来自表内，不许编。",
            "fix": "下面是一张表格的数据。请逐条挑出数据问题："
                   "空值、格式不一致、重复行、明显异常值、单位混乱。"
                   "每条给出「位置 + 问题 + 怎么改」。没问题就直说没问题。",
        }.get(mode, "总结下面这份材料。")

        if extra:
            ask += f"\n补充要求：{extra}"

        chunks = _chunk(payload, 10_000)
        if len(chunks) > 4:
            chunks = chunks[:4]
            truncated = True
        else:
            truncated = False

        if len(chunks) == 1:
            r = integrations.ai_complete(f"{ask}\n\n材料：\n{chunks[0]}", CFG["ai"])
            if not r.get("ok"):
                self._json({"ok": False, "error": r.get("error")})
                return
            out, model = r.get("text", ""), r.get("model", "")
        else:
            # 长材料：先分块摘要，再合并成一份
            parts = []
            model = ""
            for i, c in enumerate(chunks, 1):
                r = integrations.ai_complete(
                    f"这是材料的第 {i}/{len(chunks)} 部分。提炼这部分的关键信息，"
                    f"保留数字和专有名词，300 字以内。\n\n{c}", CFG["ai"])
                if not r.get("ok"):
                    self._json({"ok": False, "error": f"第 {i} 段失败：{r.get('error')}"})
                    return
                parts.append(r.get("text", ""))
                model = r.get("model", "")
            r = integrations.ai_complete(
                f"{ask}\n\n下面是分部分提炼过的内容：\n\n" + "\n\n".join(parts),
                CFG["ai"])
            if not r.get("ok"):
                self._json({"ok": False, "error": r.get("error")})
                return
            out = r.get("text", "")

        self._json({
            "ok": True,
            "text": _strip_fence(out).strip(),
            "model": model,
            "mode": mode,
            "name": rd.get("name", os.path.basename(path)),
            "kind": rd.get("kind", ""),
            "src_chars": len(payload),
            "note": rd.get("note", ""),
            "truncated": truncated,
            "chunks": len(chunks),
        })

    # ---------- 本地知识库 ----------

    def _kb_import(self, body: dict):
        """把一个本地文件抽成文本，落成一条知识（source=file）。"""
        path = (body.get("path") or "").strip()
        if not path or not os.path.exists(path):
            self._json({"ok": False, "error": "路径不存在或没填"})
            return
        rd = docsio.read_any(path)
        if not rd.get("ok"):
            self._json({"ok": False, "error": rd.get("error")})
            return
        payload = _payload(rd)
        if len(payload.strip()) < 20:
            self._json({"ok": False, "error": "这个文件里几乎没抽出文字，存不进知识库"})
            return
        title = body.get("title") or os.path.splitext(os.path.basename(path))[0]
        r = STORE.kb_save(
            None, title.strip(),
            payload[:200_000],
            (body.get("tags") or "").strip(),
            source="file", source_path=path,
        )
        if not r.get("ok"):
            self._json(r)
            return
        self._json({
            "ok": True, "id": r.get("id"),
            "title": title, "chars": len(payload),
            "name": rd.get("name", os.path.basename(path)),
            "kind": rd.get("kind", ""),
        })

    def _kb_ask(self, body: dict):
        """一次性问答：从本地知识库召回相关条目当上下文，交给模型答。"""
        q = (body.get("q") or "").strip()
        if not q:
            self._json({"ok": False, "error": "还没写问题"})
            return
        rows = STORE.kb_list()
        if not rows:
            self._json({"ok": False, "error": "知识库还是空的，先去「知识」页加几条或导入文件"})
            return
        ctx = _kb_retrieve(q, rows)
        ctx_text = "\n\n".join(
            f"【知识 {i+1}】{(c.get('title') or '(无标题)')}\n{c.get('body','')}"
            for i, c in enumerate(ctx)
        )
        prompt = (
            "下面是本地知识库里与问题最相关的若干条资料，请只依据这些资料回答问题；"
            "资料里没有的内容如实说「资料里没提到」，不要编造。\n\n"
            f"资料：\n{ctx_text}\n\n问题：{q}\n\n回答："
        )
        r = integrations.ai_complete(prompt, CFG["ai"])
        if not r.get("ok"):
            self._json({"ok": False, "error": r.get("error")})
            return
        self._json({
            "ok": True,
            "text": _strip_fence(r.get("text", "")).strip(),
            "model": r.get("model", ""),
            "used": [c.get("id") for c in ctx],
            "used_titles": [c.get("title") or "(无标题)" for c in ctx],
        })


def _strip_fence(s: str) -> str:
    """模型经常自作主张包一层 ```markdown，去掉。"""
    s = s.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", s, re.S)
    if m:
        return m.group(1)
    if s.startswith("```"):
        return re.sub(r"^```[a-zA-Z]*\n", "", s)
    return s


def _payload(rd: dict) -> str:
    """把解析结果拼成给模型看的文本。表格优先用表格形态，别拿 TSV 糊弄。"""
    tables = rd.get("tables") or []
    parts = []
    if tables:
        for t in tables[:6]:
            rows = t if isinstance(t, list) else t.get("rows", [])
            if not rows:
                continue
            head = " | ".join(str(x) for x in rows[0])
            sep = " | ".join("---" for _ in rows[0])
            body = "\n".join(" | ".join(str(x) for x in r) for r in rows[1:])
            parts.append(f"| {head} |\n| {sep} |\n{body}")
    txt = rd.get("text", "")
    if txt and not tables:
        parts.append(txt)
    elif txt and tables:
        parts.append("\n\n其他文字内容：\n" + txt)
    return "\n\n".join(parts)[:60_000]


def _chunk(t: str, n: int) -> list[str]:
    """按段落切块，尽量不在句子中间断开。"""
    out, cur = [], ""
    for p in t.split("\n"):
        if len(cur) + len(p) + 1 > n and cur:
            out.append(cur)
            cur = ""
        cur += p + "\n"
    if cur.strip():
        out.append(cur)
    return out or [t]


def _kb_tokens(text: str) -> set[str]:
    """把一段文本拆成可匹配的 token 集合：中文取二元组，英文数字取词。

    不依赖分词库，够本地知识库做关键词召回用。"""
    text = (text or "").lower()
    toks: set[str] = set()
    for w in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(w) >= 2:
            for i in range(len(w) - 1):
                toks.add(w[i:i + 2])
        elif w:
            toks.add(w)
    for w in re.findall(r"[a-z0-9]+", text):
        if len(w) >= 2:
            toks.add(w)
    return toks


def _kb_retrieve(q: str, rows: list[dict], top: int = 5, cap: int = 12_000) -> list[dict]:
    """按关键词重叠给知识条目打分，返回要塞进上下文的若干条。

    没有任何重叠时退化为按更新时间取 top 条，保证至少有点材料可问。"""
    qt = _kb_tokens(q)
    scored = []
    for r in rows:
        blob = f"{r.get('title','')} {r.get('tags','')} {r.get('body','')}"
        s = len(qt & _kb_tokens(blob))
        scored.append((s, r))
    scored.sort(key=lambda x: (x[0], x[1].get("updated", 0)), reverse=True)
    hit = [r for s, r in scored if s > 0][:top]
    if not hit:
        hit = [r for _, r in scored[:top]]
    # 控制上下文总量
    out, used = [], 0
    for r in hit:
        body = r.get("body", "") or ""
        if used + len(body) > cap:
            out.append({**r, "body": body[:max(0, cap - used)]})
            break
        out.append(r)
        used += len(body)
    return out


def main():
    port = 8777
    host = (CFG.get("remote") or {}).get("bind") or "127.0.0.1"
    argv = sys.argv[1:]
    if argv and argv[0].isdigit():
        port = int(argv[0])
    if "--host" in argv:
        host = argv[argv.index("--host") + 1]
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"工作台已启动： http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
