"""打印机：彩打 / 3D 打印的统一接入层。

两类设备、两套协议，别混着做：

* **普通打印机（彩打 / 黑白）** —— 内容先变成 PDF，再从两条通道送出去：
  1. `ipp`（默认）：**IPPS 直连**打印机，不经过 Windows 驱动，不弹任何窗口。
     ⚠️ 关键事实：Epson 的 IPP Everywhere 实现**只接受 TLS**——明文打 `http://ip:631/ipp/print`
     会回 `HTTP 426 Upgrade Required`。所以 `tls=True` 是默认，证书自签所以关校验。
  2. `spool`：丢进 **Windows 打印队列**（WSD/IPP/本地都行，系统自己处理）。
     实测：作业能进队列（Get-PrintJob 能看到），但 `winspool` 的 `WritePrinter`
     在这台 WSD 打印机上会驱动崩溃；所以 spool 通道优先用 Shell 的 PrintTo verb。
     ⚠️ Shell PrintTo **依赖文件类型注册了 handler**：PDF/图片有，HTML 没有。

* **3D 打印机** —— 三种主流协议，都走 HTTP + JSON：
  - `octoprint`：OctoPrint 1.x（API Key 走 `X-Api-Key` 头）
  - `klipper`：Klipper 固件 + Moonraker（无鉴权）
  - `prusalink`：PrusaLink（Bearer token）

设备存在 kv `printers`，任务队列存 kv `printJobs`（不上 sqlite：任务量小、
免去老库迁移风险，和 transferCfg 一个路子）。打印的产物/中间件落 `data/print/`。

零第三方依赖：Windows 侧走 PowerShell 子进程 + ctypes 调 winspool，
跨平台部分走 urllib/ssl/socket。
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "print")
STAGE = os.path.join(DATA, "stage")     # OpenClaw 把产物放这儿
OUT = os.path.join(DATA, "out")         # 转好的 PDF / G-code
LOGS = os.path.join(DATA, "logs")
for _d in (DATA, STAGE, OUT, LOGS):
    os.makedirs(_d, exist_ok=True)

DEV_KEY = "printers"
JOB_KEY = "printJobs"
MAX_JOBS = 200
IS_WIN = os.name == "nt"

# 常见浏览器（拿来做「内容 -> PDF」）。找不到就走 Pillow/纯文本兜底。
BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

PROTOCOLS = {
    "normal": ("ipp", "spool"),
    "3d": ("octoprint", "klipper", "prusalink"),
}

NORMAL_KIND = "普通打印机"
KIND_3D = "3D 打印机"


# ============================== 小工具 ==============================

def _kv_get(st, key, default=""):
    try:
        v = st.kv_get(key)
    except Exception:  # noqa: BLE001
        return default
    return v if v else default


def _json_load(raw, default):
    if not raw:
        return default
    try:
        v = json.loads(raw)
    except Exception:  # noqa: BLE001
        return default
    return v if isinstance(v, type(default)) else default


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024
    return "%.1f TB" % n


def safe_name(name):
    """去掉路径成分 + Windows 非法字符，跟 transfer 那边一个规矩。"""
    import ntpath
    base = ntpath.basename(str(name or "").replace("/", "\\")).strip()
    base = re.sub(r'[\\/:*?"<>|]', "_", base)
    base = base.rstrip(". ").strip()
    if not base:
        base = "未命名"
    if len(base) > 80:
        ext = os.path.splitext(base)[1][:12]
        base = base[:80 - len(ext)] + ext
    return base


def run_ps(script, timeout=15):
    """跑一段 PowerShell，把结果当 UTF-8 文本拿回来。

    ⚠️ 必须用 -EncodedCommand 传 Base64（UTF-16LE）：脚本里有中文，
    直接 -Command 会被 cmd 的编码坑到。返回 (ok, stdout, stderr)。
    """
    if not IS_WIN:
        return False, "", "非 Windows，没有 PowerShell"
    # ⚠️ PS 5.1 的 stdout 默认是 cp936，中文打印机名会乱码，必须先把输出编码拧成 UTF-8。
    # 另外用 -EncodedCommand（Base64 的 UTF-16LE）传脚本，避免 cmd 层的编码坑。
    prelude = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               "$OutputEncoding=[Text.Encoding]::UTF8;")
    enc = base64.b64encode((prelude + script).encode("utf-16-le")).decode("ascii")
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            capture_output=True, timeout=timeout,
        )
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode == 0, out.strip(), err.strip()
    except subprocess.TimeoutExpired:
        return False, "", "PowerShell 超时"
    except Exception as exc:  # noqa: BLE001
        return False, "", repr(exc)


def safe_json_loads(raw, default=None):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return default


# ============================== 设备存储 ==============================

def devices(st):
    """已配对设备 + 系统自动发现的普通打印机（合在一起给前端看）。"""
    saved = _json_load(_kv_get(st, DEV_KEY, ""), [])
    out = []
    seen = set()
    for d in saved:
        if not isinstance(d, dict):
            continue
        d.setdefault("id", secrets.token_hex(8))
        d.setdefault("kind", NORMAL_KIND)
        d.setdefault("proto", "ipp")
        d.setdefault("host", "")
        d.setdefault("port", 631)
        d.setdefault("api_key", "")
        d.setdefault("enabled", True)
        d.setdefault("builtin", False)
        out.append(d)
        seen.add(d["name"])
    for sys_p in list_windows_printers():
        if sys_p["name"] in seen:
            for d in out:
                if d["name"] == sys_p["name"]:
                    d["online"] = sys_p.get("online", True)
                    d.setdefault("jobs", sys_p.get("jobs", 0))
                    d["status"] = sys_p.get("status", "")
            continue
        out.append({
            "id": "sys-" + re.sub(r"[^A-Za-z0-9]+", "", sys_p["name"])[:24],
            "kind": NORMAL_KIND, "name": sys_p["name"],
            "proto": "spool", "host": "", "port": 0, "api_key": "",
            "enabled": True, "builtin": True, "caps": sys_p.get("caps", {}),
            "driver": sys_p.get("driver", ""), "port_name": sys_p.get("port", ""),
            "default": sys_p.get("default", False),
            "status": sys_p.get("status", ""), "jobs": sys_p.get("jobs", 0),
            "online": sys_p.get("online", True),
            "note": "系统里已装好的驱动，直接就能用",
        })
    return out


def save_devices(st, devs):
    keep = [d for d in devs if not d.get("builtin")]
    st.kv_set(DEV_KEY, json.dumps(keep, ensure_ascii=False))
    return len(keep)


def find_device(st, dev_id):
    for d in devices(st):
        if d.get("id") == dev_id:
            return d
    return None


def add_device(st, dev):
    devs = _json_load(_kv_get(st, DEV_KEY, ""), [])
    dev = dict(dev or {})
    dev["id"] = dev.get("id") or secrets.token_hex(8)
    dev.setdefault("kind", NORMAL_KIND)
    dev.setdefault("proto", "ipp")
    dev.setdefault("host", "")
    dev.setdefault("port", 631)
    dev.setdefault("api_key", "")
    dev.setdefault("enabled", True)
    dev.setdefault("name", "未命名设备")
    dev["added"] = time.time()
    devs.append(dev)
    save_devices(st, devs)
    return dev


def update_device(st, dev_id, patch):
    devs = _json_load(_kv_get(st, DEV_KEY, ""), [])
    hit = None
    for d in devs:
        if d.get("id") == dev_id:
            d.update(patch or {})
            hit = d
            break
    save_devices(st, devs)
    return hit


def del_device(st, dev_id):
    devs = _json_load(_kv_get(st, DEV_KEY, ""), [])
    keep = [d for d in devs if d.get("id") != dev_id]
    removed = len(keep) != len(devs)
    save_devices(st, keep)
    return removed


# ============================== Windows 打印机发现 ==============================

_PS_LIST = r"""
$ErrorActionPreference = 'SilentlyContinue'
$items = @()
foreach ($p in (Get-Printer | Where-Object { $_.Type -ne 'Logical' })) {
  $jobs = 0; $st = ''
  try { $jobs = @($p | Get-PrintJob -ErrorAction SilentlyContinue).Count } catch {}
  try { $st = [string]$p.PrinterStatus } catch {}
  $cap = ''
  try {
    if ($p.PrinterStatus -ne 'Normal') { $cap = [string]$p.PrinterStatus }
  } catch {}
  $items += [pscustomobject]@{
    name = $p.Name; driver = [string]$p.DriverName; port = [string]$p.PortName
    shared = [bool]$p.Shared; default = $false
    jobs = $jobs; status = $cap
  }
}
# 默认打印机单独查
try {
  $d = (Get-CimInstance Win32_Printer | Where-Object { $_.Default -eq $true } | Select-Object -First 1)
  if ($d) { $items | Where-Object { $_.name -eq $d.Name } | ForEach-Object { $_.default = $true } }
} catch {}
$items | ConvertTo-Json -Depth 4 -Compress
"""


def list_windows_printers():
    ok, out, err = run_ps(_PS_LIST, timeout=20)
    if not ok or not out:
        return []
    data = safe_json_loads(out, None)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    res = []
    for d in data:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        res.append({
            "name": str(d.get("name") or ""),
            "driver": str(d.get("driver") or ""),
            "port": str(d.get("port") or ""),
            "shared": bool(d.get("shared")),
            "default": bool(d.get("default")),
            "jobs": int(d.get("jobs") or 0),
            "status": str(d.get("status") or ""),
            "online": str(d.get("status") or "") in ("", "Normal"),
        })
    return res


_PS_JOBS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$p = '%s'
$items = @()
foreach ($j in (Get-PrintJob -PrinterName $p -ErrorAction SilentlyContinue)) {
  $items += [pscustomobject]@{
    id = [int]$j.ID; doc = [string]$j.DocumentName; size = [int64]$j.Size
    status = [string]$j.JobStatus; user = [string]$j.JobUserName
    submitted = ''
  }
}
if ($items.Count -eq 0) { '[]' } else { $items | ConvertTo-Json -Depth 3 -Compress }
"""


def spool_jobs(printer_name):
    ok, out, _ = run_ps(_PS_JOBS % printer_name.replace("'", "''"), timeout=15)
    if not ok or not out:
        return []
    data = safe_json_loads(out, [])
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict)]


def spool_cancel(printer_name, job_id):
    ok, out, err = run_ps(
        "Remove-PrintJob -PrinterName '%s' -ID %d" % (printer_name.replace("'", "''"), int(job_id)),
        timeout=15)
    return ok, (out or err)


def cancel_jobs(printer_name):
    ids = [j.get("id") for j in spool_jobs(printer_name) if j.get("id") is not None]
    n = 0
    for i in ids:
        ok, _ = spool_cancel(printer_name, i)
        n += 1 if ok else 0
    return n


# ============================== 局域网发现 3D 打印机 ==============================

_PROBES = (
    ("/api/version", "octoprint"),
    ("/printer/info", "klipper"),
    ("/api/v1/status", "prusalink"),
)


def discover_lan(subnet=None, timeout=1.2, workers=64):
    """扫同网段找 3D 打印机。只认**特征路径的 JSON**，别把路由器也认成打印机。

    ⚠️ 别用 127.x.x.x 冒充"局域网来客"——Windows socket 层会把它归一成 127.0.0.1，
    造出来的"来客"其实是本机，会导致断言集体假绿。
    """
    nets = [subnet] if subnet else _local_subnets()
    found = []
    seen = set()

    def one(ip):
        res = {"ip": ip, "ports": [], "kind": "", "name": "", "detail": ""}
        for port in (7125, 8080, 80):
            try:
                with socket.create_connection((ip, port), timeout) as s:
                    res["ports"].append(port)
            except Exception:  # noqa: BLE001
                continue
        if not res["ports"]:
            return None
        for port in res["ports"]:
            for path, kind in _PROBES:
                r = _http_get(ip, port, path, timeout)
                if r is None:
                    continue
                ct = (r.get("content_type") or "").lower()
                if "json" not in ct:
                    continue
                d = safe_json_loads(r.get("text") or "", None)
                if not isinstance(d, dict):
                    continue
                # 认设备：OctoPrint 的 /api/version 必有 server 字段；Moonraker 必有 result
                if kind == "octoprint" and not (d.get("server") or d.get("text")):
                    continue
                if kind == "klipper" and d.get("result") != "ok":
                    continue
                if kind == "prusalink" and not isinstance(d.get("printer"), (dict, list)):
                    continue
                res["kind"] = kind
                res["name"] = _device_name(d, kind, ip)
                res["detail"] = _device_detail(d, kind)
                res["api_key_needed"] = kind == "octoprint"
                return res
        return res if res["ports"] else None

    for net in nets:
        ips = [net + str(i) for i in range(1, 255)]
        with _Pool(workers) as pool:
            for r in pool.map(one, ips):
                if not r or not r.get("ports"):
                    continue
                key = (r["ip"], tuple(r["ports"]))
                if key in seen:
                    continue
                seen.add(key)
                found.append(r)
    found.sort(key=lambda r: (not r.get("kind"), r["ip"]))
    return found


def _device_name(d, kind, ip):
    if kind == "octoprint":
        s = d.get("server") or {}
        return str(s) if isinstance(s, str) else (s.get("server") or ip)
    if kind == "klipper":
        # Moonraker: {"result":"ok","data":{...}} —— 名字在 data 里，不在 result 里
        k = d.get("data") if isinstance(d.get("data"), dict) else {}
        return str(k.get("hostname") or ("klipper@" + ip))
    return ip


def _device_detail(d, kind):
    if kind == "octoprint":
        s = d.get("server") or {}
        if isinstance(s, str):
            try:
                s = json.loads(s)
            except Exception:  # noqa: BLE001
                s = {}
        v = (s.get("software_version") if isinstance(s, dict) else "") or ""
        return str(v)
    if kind == "klipper":
        return "Moonraker"
    if kind == "prusalink":
        return "PrusaLink"
    return ""


def _local_subnets():
    """本机在用的局域网网段（取网卡 IP 的前三段）。拿不到就退回常见的。"""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("192.168.0.1", 80))       # 不发包，只是让系统选路
        ip = s.getsockname()[0]
        s.close()
        parts = ip.split(".")
        if parts[0] == "192" and parts[1] == "168":
            out.append(".".join(parts[:3]) + ".")
        elif parts[0] == "10":
            out.append("10.%s.%s." % (parts[1], parts[2]))
        elif parts[0] == "172" and 16 <= int(parts[1]) <= 31:
            out.append("172.%s.%s." % (parts[1], parts[2]))
        else:
            out.append(".".join(parts[:3]) + ".")
    except Exception:  # noqa: BLE001
        pass
    if not out:
        out = ["192.168.0."]
    return out


class _Pool:
    """极简线程池（不想为这个引入 concurrent.futures 的显式 import 噪音）。"""

    def __init__(self, n):
        self.n = max(1, int(n))

    def __enter__(self):
        import concurrent.futures as cf
        self.ex = cf.ThreadPoolExecutor(max_workers=self.n)
        return self.ex

    def __exit__(self, *a):
        self.ex.shutdown(wait=True)

    def map(self, fn, items):
        return self.ex.map(fn, items)


def _http_get(ip, port, path, timeout=1.2):
    try:
        req = urllib.request.Request("http://%s:%d%s" % (ip, port, path))
        req.add_header("User-Agent", "wb-print-scan")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(4096)
            return {"text": raw.decode("utf-8", "replace"),
                    "content_type": r.headers.get("Content-Type", "")}
    except Exception:  # noqa: BLE001
        return None


# ============================== IPP / IPPS 客户端 ==============================

_T_TEXT, _T_NAME, _T_KEYWORD, _T_URI, _T_CHARSET, _T_LANG = 0x41, 0x42, 0x44, 0x47, 0x48, 0x49
_T_ENUM, _T_BOOL, _T_INT = 0x23, 0x22, 0x21
# ⚠️ operation-id 必须按 RFC 8011 对，别凭印象写。写错了打印机不会说原因，
# 只回一个 72 字节的空错误响应（bad-request 且没有任何 status-message），极难查：
#   0x0001 Print-Job / 0x0004 Validate-Job / 0x0008 Cancel-Job
#   0x0009 Get-Printer-Attributes / 0x000A Get-Printer-Supported-Attributes / 0x000B Get-Jobs
OP_PRINT_JOB, OP_VALIDATE_JOB, OP_CANCEL_JOB, OP_GET_ATTRS = 0x0001, 0x0004, 0x0008, 0x0009
STATUS_TEXT = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0406: "client-error-document-format-not-supported",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0506: "server-error-version-not-supported",
}


def _ipp_attr(tag, name, val, vtag=_T_TEXT):
    nb = name.encode("utf-8")
    vb = val.encode("utf-8") if isinstance(val, str) else val
    return (bytes([tag]) + struct.pack(">H", len(nb)) + nb
            + struct.pack(">H", len(vb)) + vb)


def _ipp_request(uri, op, pdf=None, job_name="wb-job", user="workbench"):
    r = b"\x02\x00" + struct.pack(">H", op) + struct.pack(">I", 1)
    r += bytes([0x01])
    r += _ipp_attr(0x47, "charset", "utf-8", _T_CHARSET)
    r += _ipp_attr(0x48, "naturalLanguage", "en", _T_LANG)
    r += _ipp_attr(0x45, "uri", uri, _T_URI)
    r += _ipp_attr(0x42, "requesting-user-name", user, _T_NAME)
    # Get-Printer-Attributes 只有 operation-attributes 组，多塞一个 job 组打印机就
    # 直接回 client-error-bad-request(0x0400)。别"顺手"加。
    if op != OP_GET_ATTRS:
        r += bytes([0x02])
        # ⚠️ 在 job-attributes 组里：0x42 是 job-uri，job-name 才是 0x49。放错打印机会回
        # client-error-bad-request(0x0400)。这条是实测踩出来的，别改回去。
        r += _ipp_attr(0x23, "document-format", "application/pdf", _T_KEYWORD)
        r += _ipp_attr(0x49, "job-name", safe_name(job_name), _T_NAME)
    r += bytes([0x03])
    if pdf is not None and op == OP_PRINT_JOB:
        r += pdf
    return r


def _ipp_parse(b):
    out = {"len": len(b)}
    if len(b) < 8:
        out["err"] = "响应太短"
        return out
    out["version"] = "%d.%d" % (b[0], b[1])
    out["status_code"] = struct.unpack(">H", b[2:4])[0]
    out["request_id"] = struct.unpack(">I", b[4:8])[0]
    out["status_text"] = STATUS_TEXT.get(out["status_code"], "status-0x%04x" % out["status_code"])
    out["ok"] = out["status_code"] < 0x0400
    # ⚠️ IPP 的分隔符 tag 有 0x00~0x05 全套（operation/job/end/printer-description/
    # unsupported-attributes），只认 0x03 的话从 printer-description 开始就全解析跑偏，
    # 看不到打印机真正报的属性。additional-value-length(0x53) 还要额外吃 4 字节长度。
    delim = {0x00: "reserved", 0x01: "operation-attributes", 0x02: "job-attributes",
             0x03: "end-of-attributes", 0x04: "printer-description",
             0x05: "unsupported-attributes"}
    names, i = [], 8
    while i < len(b):
        tag = b[i]
        if tag == 0x03:
            names.append("<" + delim[tag] + ">")
            break
        if tag in delim:
            names.append("<" + delim[tag] + ">")
            i += 1
            continue
        if i + 3 > len(b):
            names.append("<truncated at %d>" % i)
            break
        nl = struct.unpack(">H", b[i + 1:i + 3])[0]
        if nl > 4096 or i + 3 + nl > len(b):
            names.append("<truncated name at %d>" % i)
            break
        name = b[i + 3:i + 3 + nl].decode("utf-8", "replace")
        i += 3 + nl
        if tag == 0x53 and i + 4 <= len(b):          # additional-value-length
            vl = struct.unpack(">I", b[i:i + 4])[0]
            val = b[i + 4:i + 4 + vl]
            i += 4 + vl
        else:
            if i + 2 > len(b):
                break
            vl = struct.unpack(">H", b[i:i + 2])[0]
            val = b[i + 2:i + 2 + vl]
            i += 2 + vl
        if i > len(b):
            names.append("%s=<truncated>" % name)
            break
        show = val[:140].decode("utf-8", "replace") if val else ""
        names.append("%s=%r" % (name, show))
    out["attrs"] = names
    out["attr_map"] = {k.split("=", 1)[0]: k.split("=", 1)[1].strip("'")
                       for k in names if "=" in k and not k.startswith("<")}
    return out


def ipp_send(dev, pdf=None, op=OP_PRINT_JOB, timeout=25):
    """IPPS 直连打印/验证。返回 {ok, status_text, http, conn, attrs...}。"""
    host = (dev.get("host") or "").strip()
    if not host:
        return {"ok": False, "status_text": "没填打印机 IP"}
    port = int(dev.get("port") or 631)
    uri = dev.get("uri") or "ipp://%s:%d/ipp/print" % (host, port)
    path = dev.get("path") or "/ipp/print"
    use_tls = dev.get("tls", True)
    req = _ipp_request(uri, op, pdf, job_name=dev.get("job_name") or "wb-job",
                       user=dev.get("user") or "workbench")
    out = {"host": host, "port": port, "uri": uri, "tls": bool(use_tls),
           "req_bytes": len(req), "pdf_bytes": len(pdf) if pdf else 0}
    try:
        s = socket.create_connection((host, port), 8)
        s.settimeout(timeout)
        if use_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE       # 打印机自签证书
            s = ctx.wrap_socket(s, server_hostname=host)
            out["cipher"] = s.cipher()[0] if s.cipher() else ""
        s.sendall(("POST %s HTTP/1.1\r\nHost: %s:%d\r\nContent-Type: application/ipp\r\n"
                   "Accept: application/ipp\r\nUser-Agent: wb-workbench\r\n"
                   "Content-Length: %d\r\nConnection: close\r\n\r\n"
                   % (path, host, port, len(req))).encode())
        s.sendall(req)
        buf = b""
        while len(buf) < 262144:
            try:
                c = s.recv(8192)
            except socket.timeout:
                break
            if not c:
                break
            buf += c
        s.close()
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["status_text"] = "连不上：" + (str(exc) or repr(exc))
        return out
    head, _, body = buf.partition(b"\r\n\r\n")
    first = head.split(b"\r\n")[0].decode("latin-1", "replace") if head else ""
    out["http"] = first
    if "426" in first:
        out["ok"] = False
        out["status_text"] = "这台打印机只收 IPPS（TLS），得把 tls 打开"
        return out
    parsed = _ipp_parse(body)
    out["resp_len"] = parsed.get("len")
    out.update({k: v for k, v in parsed.items() if k != "len"})
    if first and "200" not in first:
        out["ok"] = False
    return out


# ============================== Windows 队列送印（spool） ==============================

class _DocInfo1(ctypes.Structure):
    _fields_ = [("pDocName", ctypes.c_wchar_p),
                ("pOutputFile", ctypes.c_wchar_p),
                ("pDatatype", ctypes.c_wchar_p)]


def winspool_write(printer_name, data, job_name="wb-job", datatype="RAW"):
    """直接把字节送进 Windows 打印队列（零依赖、不依赖桌面会话）。

    ⚠️ 每一步的异常都要就地吃掉：finally 里如果再抛异常，会把真正的错误顶掉
    （踩过：ClosePrinter 里多包了一层 c_void_p(h)，TypeError 把 WritePrinter 的
    access violation 盖掉了，排查绕了半天）。所以这里逐段 try、逐段返回。
    """
    if not IS_WIN:
        return False, "非 Windows"
    try:
        ws = ctypes.WinDLL("winspool.drv", use_last_error=True)
    except Exception as exc:  # noqa: BLE001
        return False, "加载 winspool.drv 失败：" + repr(exc)
    try:
        ws.OpenPrinterW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        ws.OpenPrinterW.restype = ctypes.c_int
        ws.StartDocPrinterW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        ws.StartDocPrinterW.restype = ctypes.c_void_p
        ws.WritePrinter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        ws.WritePrinter.restype = ctypes.c_int
        ws.EndDocPrinter.argtypes = [ctypes.c_void_p]
        ws.EndDocPrinter.restype = ctypes.c_int
        ws.ClosePrinter.argtypes = [ctypes.c_void_p]
        ws.ClosePrinter.restype = ctypes.c_int
    except Exception as exc:  # noqa: BLE001
        return False, "签名绑定失败：" + repr(exc)

    h = ctypes.c_void_p()
    if not ws.OpenPrinterW(printer_name, ctypes.byref(h), None):
        return False, "OpenPrinter 失败 err=%d" % ctypes.get_last_error()
    try:
        di = _DocInfo1(safe_name(job_name), None, datatype)
        try:
            job = ws.StartDocPrinterW(h, 1, ctypes.byref(di))
        except Exception as exc:  # noqa: BLE001
            return False, "StartDocPrinter 异常：" + repr(exc)
        if not job:
            return False, "StartDocPrinter 失败 err=%d" % ctypes.get_last_error()
        buf = ctypes.create_string_buffer(data, len(data))   # ctypes 的 c_void_p 不吃 bytes
        try:
            n = ws.WritePrinter(h, buf, len(data))
        except Exception as exc:  # noqa: BLE001
            return False, "WritePrinter 崩溃（这台打印机/这个 datatype=%s 不吃直写）：%s" % (
                datatype, getattr(exc, "__doc__", None) or repr(exc))
        try:
            ws.EndDocPrinter(h)
        except Exception:  # noqa: BLE001
            pass
        return (n > 0), ("写入 %d/%d 字节" % (n, len(data)))
    finally:
        try:
            ws.ClosePrinter(h)          # ⚠️ 不要再套 c_void_p()，会 TypeError 掩盖上面的错
        except Exception:  # noqa: BLE001
            pass


def spool_verb(printer_name, path):
    """走 Shell 的 PrintTo verb（系统自己处理文件类型）。

    ⚠️ 依赖该扩展名注册了 handler：PDF/PNG/JPG 有，**HTML 没有**。
    """
    ok, out, err = run_ps(
        "Start-Process -FilePath '%s' -Verb PrintTo -ArgumentList ('\"%s\"') -ErrorAction Stop"
        % (path.replace("'", "''"), printer_name.replace("'", "''")), timeout=20)
    return ok, (out or err or "已交给系统打印")


# ---- 系统打印对话框（"导入文件打印"走这条，稳） ----

_PS_DEFGET = r"""
$ErrorActionPreference='SilentlyContinue'
$d = Get-CimInstance Win32_Printer | Where-Object { $_.Default -eq $true } | Select-Object -First 1
if ($d) { $d.Name } else { '' }
"""

_PS_DEFSET = r"""
$ErrorActionPreference='Stop'
$p = Get-CimInstance Win32_Printer -Filter "Name='%s'"
if (-not $p) { throw '找不到这台打印机' }
Invoke-CimMethod -InputObject $p -MethodName SetDefaultPrinter | Out-Null
'done'
"""


def default_printer():
    ok, out, _ = run_ps(_PS_DEFGET, timeout=15)
    return out.strip() if ok else ""


def set_default_printer(name):
    """临时把某台打印机设成系统默认。打印对话框就是拿默认值预选的。"""
    ok, out, err = run_ps(_PS_DEFSET % name.replace("'", "''"), timeout=15)
    return ok, (out or err)


def open_print_dialog(path, printer_name=None, restore=True):
    """把文件交给系统打印对话框（Verb=print），打印机已预选好。

    这是最稳的一条：走 Windows 自己的打印 UI，厂商驱动完整参与渲染——
    驱动该转 PDF 的转 PDF、该套色的套色，不依赖我们直写打印数据。

    ⚠️ PrintTo（不弹框直接印）实测在这台机器上 PDF/TXT 都没有 handler，
    所以只能走 print 这个"会弹对话框"的动词。
    """
    if not os.path.isfile(path):
        return {"ok": False, "error": "文件不在：" + path}
    old = ""
    switched = False
    if printer_name:
        cur = default_printer()
        if cur and cur != printer_name:
            ok, msg = set_default_printer(printer_name)
            switched = ok
            if not ok:
                return {"ok": False, "error": "换默认打印机失败：" + str(msg)}
            old = cur
    ok, out, err = run_ps(
        "Start-Process -FilePath '%s' -Verb print -ErrorAction Stop" % path.replace("'", "''"),
        timeout=20)
    if not ok:
        return {"ok": False, "error": "唤起打印对话框失败：" + str(err or out),
                "default_switched": switched}
    return {"ok": True, "channel": "system-dialog", "printer": printer_name or old,
            "default_switched": switched, "old_default": old, "restore": restore}


def close_print_dialog(printer_name=None, restore=True):
    """用户打印完/取消之后调用：把默认打印机切回去。"""
    if not printer_name:
        return {"ok": False, "error": "没给要恢复的打印机名"}
    ok, msg = set_default_printer(printer_name)
    return {"ok": ok, "detail": msg}


def print_normal(st, dev, path, opts=None):
    """把一个文件（PDF/图片/文本/HTML）送到普通打印机。

    通道优先级（实测这台 Epson 的结论）：
      spool + dialog（默认）→ 系统打印对话框，稳，走厂商驱动完整渲染
      spool + silent         → PrintTo verb 直印（实测 PDF/TXT 无 handler，多半失败）
      spool + raw            → winspool 直写数据（这打印机驱动会崩）
      ipp                    → IPPS 直连（这打印机回 operation-not-supported）
    """
    opts = opts or {}
    proto = dev.get("proto") or "spool"
    name = dev.get("name") or "打印机"
    if not os.path.isfile(path):
        return {"ok": False, "error": "文件不在：" + path}

    if proto == "ipp":
        data = open(path, "rb").read()
        r = ipp_send(dev, data, OP_PRINT_JOB, timeout=int(opts.get("timeout") or 30))
        r["channel"] = "ipps" if r.get("tls") else "ipp"
        if not r.get("ok"):
            r["error"] = "IPP 拒绝：" + str(r.get("status_text") or r.get("http"))
        return r

    if proto != "spool":
        return {"ok": False, "error": "不认识的通道 " + str(proto)}

    mode = (opts.get("mode") or "dialog").lower()
    if mode == "dialog":
        return open_print_dialog(path, printer_name=name)
    if mode == "raw":
        ok, msg = winspool_write(name, open(path, "rb").read(), job_name=os.path.basename(path))
        return ({"ok": True, "channel": "winspool", "detail": msg} if ok
                else {"ok": False, "channel": "winspool", "error": msg})

    tried = []
    ok, msg = spool_verb(name, path)
    if ok:
        return {"ok": True, "channel": "spool-verb", "detail": msg}
    tried.append("PrintTo: " + str(msg))
    ok2, msg2 = winspool_write(name, open(path, "rb").read(), job_name=os.path.basename(path))
    if ok2:
        return {"ok": True, "channel": "winspool", "detail": msg2}
    tried.append("winspool: " + str(msg2))
    r = open_print_dialog(path, printer_name=name)
    if r.get("ok"):
        r["fallback_from"] = tried
        return r
    tried.append("对话框: " + str(r.get("error")))
    return {"ok": False, "channel": "spool", "error": "三条路都不通 —— " + " / ".join(tried)}


def send_to_printer(st, dev, path, opts=None):
    """不分普通/3D 的统一入口。"""
    opts = opts or {}
    if dev.get("kind") == KIND_3D:
        return print_3d(dev, path, opts)
    return print_normal(st, dev, path, opts)


# ============================== 3D 打印机协议 ==============================

def _3d_get(dev, path, timeout=12):
    url = "http://%s:%d%s" % (dev["host"], int(dev.get("port") or 80), path)
    req = urllib.request.Request(url)
    if dev.get("api_key"):
        if dev.get("proto") == "prusalink":
            req.add_header("Authorization", "Bearer " + dev["api_key"])
        else:
            req.add_header("X-Api-Key", dev["api_key"])
    req.add_header("User-Agent", "wb-workbench")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1 << 20)
            ct = r.headers.get("Content-Type", "")
            return safe_json_loads(raw.decode("utf-8", "replace"), {}) if "json" in ct else {"_raw": raw}
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_err": e.reason}
    except Exception as exc:  # noqa: BLE001
        return {"_err": repr(exc)}


def _3d_post_json(dev, path, payload=None, timeout=20):
    url = "http://%s:%d%s" % (dev["host"], int(dev.get("port") or 80), path)
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if dev.get("api_key"):
        if dev.get("proto") == "prusalink":
            req.add_header("Authorization", "Bearer " + dev["api_key"])
        else:
            req.add_header("X-Api-Key", dev["api_key"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1 << 20)
            return safe_json_loads(raw.decode("utf-8", "replace"), {"_raw": len(raw)})
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_err": e.reason}
    except Exception as exc:  # noqa: BLE001
        return {"_err": repr(exc)}


def _3d_multipart(dev, path, field, filename, data, extra=None, timeout=120):
    """手写 multipart（和 transfer 一样刻意不引第三方）。"""
    bnd = "----wbprint" + secrets.token_hex(8)
    parts = []
    for k, v in (extra or {}).items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode())
    head = ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n" % (bnd, field, safe_name(filename))).encode()
    body = b"".join(parts) + head + data + ("\r\n--%s--\r\n" % bnd).encode()
    url = "http://%s:%d%s" % (dev["host"], int(dev.get("port") or 80), path)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + bnd)
    if dev.get("api_key"):
        if dev.get("proto") == "prusalink":
            req.add_header("Authorization", "Bearer " + dev["api_key"])
        else:
            req.add_header("X-Api-Key", dev["api_key"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1 << 20)
            return safe_json_loads(raw.decode("utf-8", "replace"), {"_raw": len(raw)})
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_err": e.reason}
    except Exception as exc:  # noqa: BLE001
        return {"_err": repr(exc)}


def status_3d(dev):
    """统一成 {state, progress, temps, file, eta, raw}，前端不用管是哪家。"""
    proto = dev.get("proto")
    if proto == "octoprint":
        d = _3d_get(dev, "/api/printer")
        st = (d.get("state") or {}) if isinstance(d, dict) else {}
        pr = st.get("progress") or {}
        tp = st.get("temperature") or {}
        tool = (tp.get("tool0") or {})
        bed = (tp.get("bed") or {})
        flags = st.get("flags") or {}
        return {
            "state": st.get("text") or st.get("_err") or "未知",
            "printing": bool(flags.get("printing")),
            "progress": round(float(pr.get("completion") or 0), 1),
            "file": (st.get("job") or {}).get("file") or "",
            "eta_min": round((float(pr.get("print_time_left") or 0)) / 60.0, 1),
            "nozzle": [round(float(tool.get("actual") or 0), 1), round(float(tool.get("target") or 0), 1)],
            "bed": [round(float(bed.get("actual") or 0), 1), round(float(bed.get("target") or 0), 1)],
            "raw_err": d.get("_err") or d.get("_http") or "",
        }
    if proto == "klipper":
        # Moonraker 的响应是 {"result":"ok","status":{...},"eventtime":...} ——
        # status 在**顶层**，result 只是个 "ok" 字符串。按 result 取会 AttributeError。
        d = _3d_get(dev, "/printer/objects/progress")
        o = d.get("status") if isinstance(d.get("status"), dict) else {}
        prog = o.get("progress") or 0
        t = _3d_get(dev, "/printer/objects/gcode_start")
        st2 = t.get("status") if isinstance(t.get("status"), dict) else {}
        return {
            "state": st2.get("state") or ("printing" if prog else "ready"),
            "printing": bool(prog and prog < 1),
            "progress": round(float(prog or 0) * 100, 1),
            "file": st2.get("filename") or "",
            "nozzle": [], "bed": [], "raw_err": d.get("_err") or "",
        }
    if proto == "prusalink":
        d = _3d_get(dev, "/api/v1/status")
        p = d.get("printer") if isinstance(d, dict) else {}
        if isinstance(p, list):
            p = p[0] if p else {}
        p = p or {}
        temp = p.get("temp") or {}
        return {
            "state": str(p.get("state") or "未知"),
            "printing": "PRINTING" in str(p.get("state") or "").upper(),
            "progress": round(float(p.get("progress") or 0), 1),
            "file": "", "nozzle": [float(temp.get("extruder") or 0), float(temp.get("extruder_target") or 0)],
            "bed": [float(temp.get("bed") or 0), float(temp.get("bed_target") or 0)],
            "raw_err": d.get("_err") or "",
        }
    return {"state": "未知协议", "printing": False, "progress": 0, "file": "", "nozzle": [], "bed": []}


def print_3d(dev, path, opts=None):
    opts = opts or {}
    proto = dev.get("proto")
    name = os.path.basename(path)
    data = open(path, "rb").read()
    if proto == "octoprint":
        r = _3d_multipart(dev, "/api/files", "file", name, data,
                          extra={"select": "true", "print": "true" if opts.get("print_now", True) else "false"})
        if r.get("_err") or r.get("_http"):
            # 老版本没有 multipart 上传端点，退回"先传后选"
            r2 = _3d_multipart(dev, "/api/files/local", "file", name, data)
            if r2.get("_err") or r2.get("_http"):
                return {"ok": False, "error": str(r2)}
            if opts.get("print_now", True):
                _3d_post_json(dev, "/api/files/local/" + name, {"command": "select", "print": True})
            r = r2
        return {"ok": True, "channel": "octoprint", "file": name, "bytes": len(data)}
    if proto == "klipper":
        r = _3d_multipart(dev, "/printer/files/upload", "file", name, data,
                          extra={"root": opts.get("root", "gcodes")})
        if r.get("_err"):
            return {"ok": False, "error": str(r)}
        start = _3d_post_json(dev, "/printer/print/start?filename=" + urllib.parse.quote(name), None)
        if start.get("_err"):
            return {"ok": False, "error": "已上传但启动失败：" + str(start)}
        return {"ok": True, "channel": "klipper", "file": name, "bytes": len(data)}
    if proto == "prusalink":
        r = _3d_multipart(dev, "/api/v1/files", "file", name, data, extra={"path": opts.get("root", "/")})
        if r.get("_err") or r.get("_http"):
            return {"ok": False, "error": str(r)}
        if opts.get("print_now", True):
            _3d_post_json(dev, "/api/v1/job", {"paths": [name], "print": True})
        return {"ok": True, "channel": "prusalink", "file": name, "bytes": len(data)}
    return {"ok": False, "error": "不认识的 3D 协议 " + str(proto)}


def control_3d(dev, action):
    proto = dev.get("proto")
    cmd = {"pause": {"pause"}, "resume": {"resume"}, "cancel": {"cancel"},
           "stop": {"stop"}, "start": {"start"}}.get(action, set())
    if not cmd:
        return {"ok": False, "error": "不认识的动作 " + str(action)}
    if proto == "octoprint":
        r = _3d_post_json(dev, "/api/job", {"command": action})
        return {"ok": not (r.get("_err") or r.get("_http")), "raw": r}
    if proto == "klipper":
        m = {"pause": "pause", "resume": "resume", "cancel": "stop", "stop": "stop", "start": "start"}
        r = _3d_post_json(dev, "/printer/print/" + m[action], None)
        return {"ok": not r.get("_err"), "raw": r}
    if proto == "prusalink":
        m = {"pause": "pause", "resume": "resume", "cancel": "stop", "stop": "stop", "start": "print"}
        r = _3d_post_json(dev, "/api/v1/job", {"action": m[action]})
        return {"ok": not (r.get("_err") or r.get("_http")), "raw": r}
    return {"ok": False, "error": "不认识的 3D 协议"}


def test_3d(dev):
    d = _3d_get(dev, "/api/version" if dev.get("proto") == "octoprint" else "/printer/info")
    if d.get("_err"):
        return {"ok": False, "error": "连不上：" + str(d.get("_err"))}
    if dev.get("proto") == "octoprint" and not dev.get("api_key"):
        return {"ok": False, "error": "OctoPrint 需要 API Key（Settings → API）"}
    return {"ok": True, "info": d}


# ============================== 任务队列 ==============================

def jobs(st, limit=MAX_JOBS):
    arr = _json_load(_kv_get(st, JOB_KEY, ""), [])
    return arr[:limit]


def add_job(st, dev, path, title=None, extra=None):
    arr = _json_load(_kv_get(st, JOB_KEY, ""), [])
    j = {
        "id": secrets.token_hex(8),
        "printer": dev.get("name") if dev else "?",
        "printer_id": dev.get("id") if dev else "",
        "kind": dev.get("kind") if dev else NORMAL_KIND,
        "file": os.path.basename(path or ""),
        "path": path or "",
        "title": title or os.path.basename(path or ""),
        "status": "queued",
        "created": time.time(),
        "log": [],
        "meta": extra or {},
    }
    arr.insert(0, j)
    st.kv_set(JOB_KEY, json.dumps(arr[:MAX_JOBS], ensure_ascii=False))
    return j


def update_job(st, job_id, **patch):
    arr = _json_load(_kv_get(st, JOB_KEY, ""), [])
    hit = None
    for j in arr:
        if j.get("id") == job_id:
            if "log" in patch:
                j.setdefault("log", []).append(patch.pop("log"))
            j.update(patch)
            hit = j
            break
    st.kv_set(JOB_KEY, json.dumps(arr[:MAX_JOBS], ensure_ascii=False))
    return hit


def clear_jobs(st):
    st.kv_set(JOB_KEY, "[]")


# ============================== 内容 -> PDF ==============================

def find_browser():
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    return ""


def html_to_pdf(html_path, pdf_path, timeout=60):
    """用 Chrome/Edge 的 headless 打印成 PDF。这是零依赖路线里最靠谱的一步。"""
    exe = find_browser()
    if not exe:
        return False, "没找到 Chrome / Edge"
    profile = os.path.join(DATA, "_chrome_profile")
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
           "--virtual-time-budget=8000", "--user-data-dir=" + profile,
           "--print-to-pdf=" + pdf_path, url]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "浏览器打印超时"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 200:
        return False, "没生成 PDF"
    return True, human(os.path.getsize(pdf_path))


def to_pdf(src, pdf_path=None):
    """任意内容 -> PDF。PDF 原样复制；其它交给浏览器。"""
    ext = os.path.splitext(src)[1].lower()
    pdf_path = pdf_path or os.path.join(OUT, secrets.token_hex(6) + "__" + safe_name(src) + ".pdf")
    if ext == ".pdf":
        if os.path.abspath(src) != os.path.abspath(pdf_path):
            shutil.copy2(src, pdf_path)
        return pdf_path, "原样"
    if ext in (".html", ".htm"):
        ok, msg = html_to_pdf(src, pdf_path)
        return (pdf_path, msg) if ok else (None, msg)
    if ext in (".txt", ".md", ".log", ".csv", ".json"):
        with open(src, "r", encoding="utf-8", errors="replace") as f:
            body = f.read()
        html = ("<html><head><meta charset='utf-8'><style>"
                "body{font-family:'Microsoft YaHei',Segoe UI,sans-serif;padding:28px;line-height:1.6}"
                "pre{white-space:pre-wrap;font-family:Consolas,monospace}"
                "</style></head><body><pre>" + _esc(body) + "</pre></body></html>")
        tmp = os.path.join(STAGE, secrets.token_hex(6) + ".html")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        ok, msg = html_to_pdf(tmp, pdf_path)
        return (pdf_path, msg) if ok else (None, msg)
    ok, msg = html_to_pdf(src, pdf_path)
    return (pdf_path, msg) if ok else (None, msg)


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ============================== 派活辅助 ==============================

def stage_snapshot():
    return {f: os.path.getmtime(os.path.join(STAGE, f)) for f in os.listdir(STAGE)
            if os.path.isfile(os.path.join(STAGE, f))}


def stage_new(after):
    """列出 stage 里比 after 新的文件（OpenClaw 跑完扫这个就知道产出了什么）。"""
    cur = stage_snapshot()
    return [os.path.join(STAGE, f) for f, mt in cur.items() if after.get(f, 0) < mt]


def selftest():
    """纯逻辑自检：净化、IPP 编码、设备归一。不碰网络。"""
    fails = []

    def ck(name, cond):
        if not cond:
            fails.append(name)

    ck("safe_name 去路径", safe_name("..\\x\\evil.txt") == "evil.txt")
    ck("safe_name 去非法字符", not re.search(r'[\\/:*?"<>|]', safe_name('a*b?c|d.txt')))
    ck("safe_name 空名兜底", safe_name("  ") == "未命名")
    ck("safe_name 保扩展名", safe_name("x" * 200 + ".gcode").endswith(".gcode"))

    req = _ipp_request("ipp://1.2.3.4:631/ipp/print", OP_PRINT_JOB, b"%PDF-")
    ck("IPP 版本 2.0", req[:2] == b"\x02\x00")
    ck("IPP op=Print-Job", struct.unpack(">H", req[2:4])[0] == OP_PRINT_JOB)
    ck("IPP 带 document-data", req.endswith(b"%PDF-"))
    ck("IPP job-name 用 0x49", b"job-name" in req)
    ck("IPP 不误用 job-uri", b"job-uri" not in req)

    p = _ipp_parse(b"\x02\x00\x00\x00\x00\x00\x00\x01\x03")
    ck("IPP 解析 successful-ok", p.get("ok") is True and p.get("status_text") == "successful-ok")
    p2 = _ipp_parse(b"\x02\x00\x04\x00\x00\x00\x00\x01\x03")
    ck("IPP 解析 bad-request", p2.get("status_code") == 1024 and p2.get("ok") is False)

    ck("human B", human(0) == "0 B")
    ck("human KB", human(1536).startswith("1.5 KB"))
    return fails


if __name__ == "__main__":
    f = selftest()
    print("selftest OK" if not f else "FAIL: " + ", ".join(f))
    sys.exit(1 if f else 0)