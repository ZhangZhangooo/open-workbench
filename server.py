"""OpenWorkbench — 本地服务端。

零第三方依赖，全部用 Python 标准库。服务只监听 127.0.0.1，不对外暴露。
"""

from __future__ import annotations

import base64
import calendar
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
import wecom as wecommod  # noqa: E402

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
        "smtp_tls": "",          # 空=自动（465→ssl / 587→starttls）；也可 ssl/starttls/none
    },
    # 63 多账号：上面那份 mail 永远等于「当前启用的账号」，切账号就是把它换掉。
    # 这样所有老代码（MailClient(CFG["mail"])）一行都不用改。
    "mail_accounts": [],         # [{id,name,user,password,imap_host,imap_port,smtp_host,smtp_port,smtp_tls}]
    "mail_active": "",           # 当前启用账号的 id（空 = 用上面那份 mail）
    # 企业微信双向通道：自建应用 + 「微信插件」，在微信聊天框里指挥工作台。
    # 收消息只要 Token/EncodingAESKey；发消息额外要 CorpID/Secret/AgentID，
    # 且本机公网 IP 必须在后台的「企业可信IP」白名单里（否则 60020）。
    "wecom": {
        "enabled": False,
        "corpid": "",            # 我的企业 -> 企业ID
        "secret": "",            # 自建应用 -> Secret
        "agentid": "",           # 自建应用 -> AgentId
        "touser": "@all",        # 默认接收人（企业微信 UserID，@all 表示应用可见范围内所有人）
        "token": "",             # 接收消息 -> Token
        "aes_key": "",           # 接收消息 -> EncodingAESKey
        "msgtype": "text",       # 主动发消息用 text / markdown
        "tunnel": "",            # cloudflared 拿到的 https://xxx.trycloudflare.com
        "callback_url": "",      # 拼好的完整回调地址，方便直接粘到后台
        "egress_ip": "",         # 上次见到的公网出口 IP，变了就提醒去更新可信IP
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

MAIL_ATT = os.path.join(DATA, "mail_att")
MAIL_TLS_FIELDS = ("user", "password", "imap_host", "imap_port", "smtp_host",
                   "smtp_port", "smtp_tls")


def _mail_acct_id() -> str:
    return str(CFG.get("mail_active") or "")


def mail_client():
    """当前启用账号的 MailClient。多账号就是「先把 CFG['mail'] 换成那个账号」。"""
    return mailmod.MailClient(CFG["mail"])


def _mail_apply_active(aid: str) -> dict:
    """把启用账号的内容灌进 CFG['mail']，并落盘。返回被选中的账号（脱敏）。

    注意 password 也要「照搬」：另一个账号的授权码绝不能留在内存里，
    否则切到没存密码的账号时会拿上一个账号的授权码去登录。
    """
    accs = CFG.get("mail_accounts") or []
    a = next((x for x in accs if str(x.get("id")) == str(aid)), None)
    if a is None:
        return {"ok": False, "error": "没这个账号"}
    for k in MAIL_TLS_FIELDS:
        if k in a:
            CFG["mail"][k] = a[k]
    CFG["mail_active"] = str(a.get("id"))
    save_config(CFG)
    return {"ok": True, "id": CFG["mail_active"], "user": CFG["mail"].get("user", "")}


def _uid_dir(uid: str) -> str:
    """uid 当目录名用之前洗一遍（uid 通常纯数字，但别假设）。"""
    return "".join(ch for ch in str(uid) if ch.isalnum() or ch in "-_") or "unknown"


def _mail_accounts_public() -> list[dict]:
    """对外列账号：密码换成「有没有填」，别把授权码送去前端。"""
    out = []
    for a in CFG.get("mail_accounts") or []:
        out.append({
            "id": a.get("id"), "name": a.get("name") or a.get("user") or "账号",
            "user": a.get("user", ""), "imap_host": a.get("imap_host", ""),
            "imap_port": a.get("imap_port", 993), "smtp_host": a.get("smtp_host", ""),
            "smtp_port": a.get("smtp_port", 465), "smtp_tls": a.get("smtp_tls", ""),
            "password_set": bool(a.get("password")),
            "active": str(a.get("id")) == _mail_acct_id(),
        })
    return out


def _mail_rules_tags(subject: str, frm: str) -> str:
    """64 收件规则：命中就返回标签（多规则命中用 / 连起来）。"""
    try:
        rules = STORE.mail_rules_list()
    except Exception:  # noqa: BLE001
        return ""
    s = (subject or "").lower()
    f = (frm or "").lower()
    hits: list[str] = []
    for r in rules:
        c = (r.get("contains") or "").strip().lower()
        if not c:
            continue
        field = r.get("field") or "from"
        hit = ((field in ("from", "any") and c in f)
               or (field in ("subject", "any") and c in s))
        if hit:
            t = (r.get("tag") or r.get("name") or "").strip()
            if t and t not in hits:
                hits.append(t)
    return " / ".join(hits)


_MAIL_UNREAD = {"n": 0, "ts": 0.0, "error": ""}


def _mail_unread_cached(max_age: float = 300.0) -> dict:
    """70 未读角标：缓存一下，别让侧栏每 2 秒就去 IMAP 敲一次门。"""
    now = time.time()
    if _MAIL_UNREAD["ts"] and now - _MAIL_UNREAD["ts"] < max_age:
        return {**_MAIL_UNREAD, "cached": True}
    if not CFG["mail"].get("user") or not CFG["mail"].get("password"):
        _MAIL_UNREAD.update(n=0, ts=now, error="还没配邮箱")
        return {**_MAIL_UNREAD, "cached": False}
    try:
        r = mail_client().unread_count()
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "n": 0, "error": f"{type(e).__name__}: {e}"}
    _MAIL_UNREAD.update(n=int(r.get("n") or 0), ts=now, error=r.get("error") or "")
    return {**_MAIL_UNREAD, "cached": False, "ok": bool(r.get("ok"))}


def _mail_send_queued(body: dict) -> dict:
    """69 定时发送：入队，到点由后台代发。"""
    to = (body.get("to") or "").strip()
    subj = (body.get("subject") or "").strip()
    text = body.get("body") or ""
    if not to:
        return {"ok": False, "error": "还没填收件人"}
    at = float(body.get("at") or 0)
    if at <= 0:
        return {"ok": False, "error": "还没填发送时间"}
    r = STORE.mail_outbox_add(_mail_acct_id(), to, subj, text, at, "pending")
    r["at"] = at
    return r


def _mail_tick() -> int:
    """把到点的定时邮件发掉。返回这一轮处理了几封。"""
    try:
        due = STORE.mail_outbox_due(time.time())
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for row in due:
        n += 1
        try:
            msg = _mail_build(row.get("mto") or "", row.get("subject") or "",
                              row.get("body") or "")
            acct = next((a for a in (CFG.get("mail_accounts") or [])
                         if str(a.get("id")) == str(row.get("acct"))), None)
            cli = mailmod.MailClient(acct) if acct else mail_client()
            r = cli.send_message(msg)
            if r.get("ok"):
                STORE.mail_outbox_mark(row["id"], "sent")
            else:
                STORE.mail_outbox_mark(row["id"], "failed", r.get("error") or "发送失败")
        except Exception as e:  # noqa: BLE001
            STORE.mail_outbox_mark(row["id"], "failed", f"{type(e).__name__}: {e}")
    return n


def _mail_build(to: str, subject: str, text: str):
    from email.message import EmailMessage as _EM
    msg = _EM()
    msg["From"] = CFG["mail"].get("user") or ""
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    return msg


def _mail_loop():
    while True:
        time.sleep(20)
        try:
            _mail_tick()
        except Exception:  # noqa: BLE001
            pass


# ---------------- H 域：日历 / 会议（71-78）----------------

_ICS_FREQ = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY",
             "yearly": "YEARLY", "weekdays": "WEEKLY"}


def _ics_escape(s: str) -> str:
    """ICS 文本要转义反斜杠/分号/逗号，换行用 \\n。"""
    return ((s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_dt(day: str, hm: str) -> str:
    d = (day or "").replace("-", "")
    t = (hm or "").replace(":", "")
    if len(d) == 8 and len(t) == 4:
        return f"{d}T{t}00"
    return (d or "19700101") + "T000000"


def _ics_cal(a: str, b: str) -> str:
    """76 导出 ICS：日程 + 会议。重复日程只出原型并带 RRULE，交给日历软件自己展开。"""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenWorkbench//Calendar//CN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:OpenWorkbench 日程"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    def vevent(uid, day, start, end, title, desc, loc, rule, link):
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"SUMMARY:{_ics_escape(title)}")
        lines.append(f"DTSTART:{_ics_dt(day, start)}")
        if end:
            lines.append(f"DTEND:{_ics_dt(day, end)}")
        if desc:
            lines.append(f"DESCRIPTION:{_ics_escape(desc)}")
        if loc:
            lines.append(f"LOCATION:{_ics_escape(loc)}")
        if link:
            lines.append(f"URL:{_ics_escape(link)}")
        if rule:
            lines.append("RRULE:" + rule)
        lines.append("END:VEVENT")

    seen = set()
    for ev in STORE.events_range(a, b):
        eid = ev.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        rep = ev.get("repeat") or ""
        rule = ""
        if rep in _ICS_FREQ:
            rule = "FREQ=" + _ICS_FREQ[rep]
            if rep == "weekdays":
                rule += ";BYDAY=MO,TU,WE,TH,FR"
            until = (ev.get("repeat_until") or "").replace("-", "")
            if until:
                rule += f";UNTIL={until}T235959"
        base = ev.get("base_day") or ev.get("day")
        vevent(f"wb-ev-{eid}@openworkbench", base, ev.get("start"), ev.get("end"),
               ev.get("title"), ev.get("note"), "", rule, "")
    try:
        mts = STORE._run("SELECT * FROM meetings WHERE day>=? AND day<=? ORDER BY day",
                         (a, b))
    except Exception:  # noqa: BLE001
        mts = []
    for mt in mts:
        desc = "\n".join(x for x in [
            ("参会：" + mt["attendees"]) if mt.get("attendees") else "",
            mt.get("note") or "",
        ] if x)
        vevent(f"wb-mt-{mt.get('id')}@openworkbench", mt.get("day"), mt.get("start"),
               mt.get("end"), mt.get("title"), desc, mt.get("location") or "", "",
               mt.get("link") or "")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _cal_minutes_prompt(row: dict) -> str:
    """78 会议纪要：把会议信息拼成给 OpenClaw 的写作任务。"""
    span = (row.get("start") or "")
    if row.get("end"):
        span = (span + "–" + str(row["end"])) if span else str(row["end"])
    lines = ["把下面这场会议整理成一份会议纪要，用 Markdown 输出。", "",
             f"- 主题：{row.get('title') or ''}",
             f"- 日期：{row.get('day') or ''}",
             f"- 时间：{span}"]
    if row.get("location"):
        lines.append(f"- 地点：{row['location']}")
    if row.get("attendees"):
        lines.append(f"- 参会：{row['attendees']}")
    if row.get("link"):
        lines.append(f"- 入会链接：{row['link']}")
    note = (row.get("note") or "").strip()
    if note:
        lines += ["", "已有的记录 / 备注：", note]
    lines += ["", "结构要求：## 结论与决定 / ## 讨论要点 / ## 待办事项（Markdown 表格：事项 | 负责人 | 截止）"
              "/ ## 风险与遗留问题。信息不够的地方写「待补充」，不要编造人名或数字。"]
    return "\n".join(lines)


_REM_PUSH_LAST = {"ts": 0.0, "n": 0, "conn": 0}


def _enabled_connectors() -> list[dict]:
    """启用中的连接器。企业微信没有 token/url（它靠 secret），单独放行。"""
    out = []
    for c in (CFG.get("connectors") or []):
        if not c.get("enabled", True):
            continue
        ctype = (c.get("type") or "").lower()
        if c.get("token") or c.get("url"):
            out.append(c)
        elif ctype in ("wecom", "qywx", "企业微信") and c.get("secret"):
            out.append(c)
    return out


def _push_all(title: str, content: str) -> dict:
    """把一条内容推到所有启用的连接器，逐个记推送日志。"""
    conns = _enabled_connectors()
    sent = 0
    for c in conns:
        try:
            res = integrations.connector_push(c, title, content)
            good = bool(res.get("ok"))
            sent += 1 if good else 0
            STORE.connector_push_log((c.get("type") or ""),
                                     (c.get("name") or c.get("id") or ""),
                                     title, good, res.get("error") or res.get("msg") or "")
        except Exception as e:  # noqa: BLE001
            try:
                STORE.connector_push_log((c.get("type") or ""), (c.get("name") or ""),
                                         title, False, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
    return {"ok": True, "n": len(conns), "sent": sent}


# ================= 企业微信双向通道 =================
# 前面那些连接器（pushplus / serverchan / webhook / smtp）都是单向的：
# 工作台推给你，你没法回话。这里是第一个双向的 ——
# 你在（普通）微信的聊天框里发一句话，工作台收到、干活、把结果发回同一个框。
#
# 走的通道是「企业微信群机器人」不行（只能群内、单向），所以用的是
# 「企业微信自建应用 + 我的企业→微信插件」：个人微信扫一下插件二维码，
# 之后收发消息都在你自己的微信里，体验跟普通微信没区别，且官方合规、不封号。
#
# 两个硬性前提，代码里该提示的都提示了：
#   1. 收消息只要 Token + EncodingAESKey；
#   2. 发消息要 CorpID + Secret + AgentID，且本机公网 IP 必须在后台
#      「企业可信IP」白名单里 —— 家宽是动态 IP，所以这里存了上次的出口 IP 做对比提醒。

_WECOM_SEEN: dict[str, float] = {}      # MsgId -> 时间，企业微信收不到响应会重推，靠它去重
_WECOM_LOCK = threading.Lock()


def wecom_cfg() -> dict:
    c = CFG.get("wecom")
    if not isinstance(c, dict):
        c = json.loads(json.dumps(DEFAULT_CONFIG["wecom"]))
        CFG["wecom"] = c
    for k, v in DEFAULT_CONFIG["wecom"].items():
        c.setdefault(k, v)
    return c


def _wecom_callback_url() -> str:
    """拼给企业微信后台填的回调地址。"""
    c = wecom_cfg()
    manual = (c.get("callback_url") or "").strip()
    if manual:
        return manual
    base = (c.get("tunnel") or "").strip().rstrip("/")
    return f"{base}/wecom/callback" if base else ""


def _wecom_send_to(user: str, content: str, title: str = "") -> dict:
    """主动发一条给成员。user 为空就退回配置里的默认接收人。"""
    c = dict(wecom_cfg())
    if user:
        c["touser"] = user
    return integrations.wecom_send(c, title, content, c.get("msgtype") or "text")


def _wecom_dedup(msgid: str, window: float = 300.0) -> bool:
    """True = 这条是重推的，跳过。企业微信 5 秒收不到响应就会重试。"""
    if not msgid:
        return False
    now = time.time()
    with _WECOM_LOCK:
        for k, ts in list(_WECOM_SEEN.items()):
            if now - ts > window:
                _WECOM_SEEN.pop(k, None)
        if msgid in _WECOM_SEEN:
            return True
        _WECOM_SEEN[msgid] = now
        return False


_WECOM_HELP = """我在，说人话就行。

  帮助            看这份说明
  状态            工作台现在什么样
  今日            今天还有哪些事没做完
  记 买牛奶        攒进收件箱（零碎念头先存下）
  待办 交电费      直接进今天的事
  收件箱          看攒了什么
  账 32 吃饭       记一笔支出
  账 收入 500 稿费  记一笔收入
  搜 报销单        全盘找文件（46 万份里找）

其它任何话，原样交给本机 OpenClaw 去干，干完把结果发回这个聊天框。"""


_LEDGER_LEAD = ("账", "记账", "记帐", "流水", "记一笔")
_LEDGER_OUT = ("支出", "支", "花", "花了", "用了", "买了")
_LEDGER_IN = ("收入", "收", "入", "进账", "赚了")


def _wecom_parse_ledger(s: str):
    """'账 32 吃饭 和同事' -> (支出, 32.0, '吃饭', '和同事')

    前缀分三层剥：先剥「账 / 记账」这类动词，再看第二个词是不是「收入/支出」。
    """
    parts = (s or "").split()
    if parts and parts[0] in _LEDGER_LEAD:
        parts = parts[1:]
    if not parts:
        return None
    kind = "支出"
    if parts[0] in _LEDGER_IN:
        kind, parts = "收入", parts[1:]
    elif parts[0] in _LEDGER_OUT:
        kind, parts = "支出", parts[1:]
    if not parts:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", parts[0])
    if not m:
        return None
    try:
        amt = float(m.group(0))
    except ValueError:
        return None
    rest = parts[1:]
    cat = rest[0] if rest else ""
    note = " ".join(rest[1:]) if len(rest) > 1 else ""
    return kind, amt, cat, note


def _wecom_try_command(text: str, user: str = "") -> dict | None:
    """内置命令优先。返回 None 表示「这不是命令」，交给 OpenClaw。"""
    t = (text or "").strip()
    if not t:
        return {"text": _WECOM_HELP}
    low = t.lower()

    if low in ("帮助", "help", "?", "？", "菜单", "能干啥", "能做什么"):
        return {"text": _WECOM_HELP}

    if low in ("状态", "status", "工作台"):
        try:
            cnt = STORE.counts()
            ip = wecom_cfg().get("egress_ip") or "未知"
            return {"text": (
                f"工作台在跑。\n"
                f"文件索引 {cnt.get('inbox', 0) and ''}{IDX.count()} 份\n"
                f"收件箱 {cnt.get('inbox', 0)} 条 / 今日未完成 {cnt.get('today_undone', 0)} 条\n"
                f"公网出口 IP {ip}"
            )}
        except Exception as e:  # noqa: BLE001
            return {"text": f"查状态出错了：{e}"}

    if low in ("今日", "今天", "today"):
        try:
            rows = STORE.today_list(DAY())
            todo = [r for r in rows if not r.get("done")]
            if not todo:
                return {"text": f"{DAY()} 今天的事都干完了。"}
            lines = [f"{i}. {r.get('text', '')}" for i, r in enumerate(todo[:20], 1)]
            more = f"\n…还有 {len(todo) - 20} 条" if len(todo) > 20 else ""
            return {"text": f"今天还剩 {len(todo)} 件事：\n" + "\n".join(lines) + more}
        except Exception as e:  # noqa: BLE001
            return {"text": f"读今日清单出错：{e}"}

    if low in ("收件箱", "inbox", "待办列表"):
        try:
            rows = [r for r in STORE.inbox_list(200) if not r.get("done")]
            if not rows:
                return {"text": "收件箱是空的。"}
            lines = [f"{i}. {r.get('text', '')}" for i, r in enumerate(rows[:20], 1)]
            return {"text": f"收件箱 {len(rows)} 条：\n" + "\n".join(lines)}
        except Exception as e:  # noqa: BLE001
            return {"text": f"读收件箱出错：{e}"}

    m = re.match(r"^(?:记一下|记|备忘|memo|存一下)\s*[:：]?\s*(.+)$", t, re.I)
    if m and m.group(1).strip():
        try:
            STORE.inbox_add(m.group(1).strip())
            return {"text": f"收进收件箱了：{m.group(1).strip()}"}
        except Exception as e:  # noqa: BLE001
            return {"text": f"没记上：{e}"}

    m = re.match(r"^(?:待办|todo)\s*[:：]?\s*(.+)$", t, re.I)
    if m and m.group(1).strip():
        try:
            STORE.today_add(DAY(), m.group(1).strip())
            return {"text": f"加进今天了：{m.group(1).strip()}"}
        except Exception as e:  # noqa: BLE001
            return {"text": f"没加上：{e}"}

    m = re.match(r"^(?:搜|找|文件|find|search)\s*[:：]?\s*(.+)$", t, re.I)
    if m and m.group(1).strip():
        kw = m.group(1).strip()
        try:
            rows, total = IDX.search(kw, "", None, 6, 0)
            if not rows:
                return {"text": f"全盘没找到「{kw}」。"}
            lines = []
            for r in rows:
                lines.append(f"· {r.get('name', '')}\n  {r.get('path', '')}")
            more = f"\n（共 {total} 个匹配，先给前 6 个）" if total > len(rows) else ""
            return {"text": f"「{kw}」找到这些：\n" + "\n".join(lines) + more}
        except Exception as e:  # noqa: BLE001
            return {"text": f"搜的时候出错：{e}"}

    m = re.match(r"^(?:账|记账|花了|收入)\s*[:：]?\s*(.+)$", t, re.I)
    if m:
        parsed = _wecom_parse_ledger(t)
        if parsed:
            kind, amt, cat, note = parsed
            try:
                r = STORE.ledger_add(DAY(), kind, amt, cat, note)
                if not r.get("ok"):
                    return {"text": f"没记上：{r.get('error')}"}
                tail = ""
                over = r.get("over") or []
                if over:
                    tail = "\n⚠️ 这个月超支了：" + "、".join(
                        f"{o.get('category')} 超 {o.get('over')}" for o in over[:5])
                return {"text": f"记好了：{DAY()} {kind} ¥{amt:.2f}"
                                + (f" · {cat}" if cat else "") + tail}
            except Exception as e:  # noqa: BLE001
                return {"text": f"记账出错：{e}"}
    return None


def _wecom_log(user: str, req: str, resp: str, ok: bool) -> None:
    try:
        STORE.log_add("info" if ok else "warn",
                      f"[微信 {user or '-'}] {req[:80]} -> {(resp or '')[:200]}", "wecom")
    except Exception:  # noqa: BLE001
        pass


def _wecom_work(fields: dict) -> None:
    """后台真正干活的地方。企业微信只等 5 秒，所以必须异步 + 主动发送。"""
    user = (fields.get("FromUserName") or "").strip()
    text = (fields.get("Content") or "").strip()
    mtype = (fields.get("MsgType") or "").strip()

    if mtype == "event":
        ev = (fields.get("Event") or "").strip()
        if ev in ("subscribe", "enter_agent"):
            _wecom_send_to(user, _WECOM_HELP)
        return
    if mtype and mtype != "text":
        _wecom_send_to(user, f"我只认得文字消息（这条是 {mtype}），语音图片暂时处理不了。")
        return

    fast = _wecom_try_command(text, user)
    if fast is not None:
        _wecom_send_to(user, fast["text"])
        _wecom_log(user, text, fast["text"], True)
        return

    _wecom_send_to(user, f"收到，正在办：{text[:60]}\n（干完我把结果发回这个聊天框）")
    t0 = time.time()
    try:
        ctx = _openclaw_ctx_parts()
    except Exception:  # noqa: BLE001
        ctx = ""
    try:
        r = _claw_run_with_retry(text, ctx, 300)
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    dur = round(time.time() - t0, 1)
    out = (r.get("reply") or r.get("error") or "（它没给输出）").strip()
    head = f"办完了，用了 {dur}s" if r.get("ok") else f"没办成（{dur}s）"
    _wecom_send_to(user, f"{head}\n\n{out[:3500]}")
    _wecom_log(user, text, out, bool(r.get("ok")))


def wecom_handle_get(query: dict) -> tuple[int, str]:
    """企业微信后台点「保存」时的 URL 校验：签名对得上就原样回 echostr。"""
    cfg = wecom_cfg()
    g = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    try:
        c = wecommod.WeComCrypto(cfg.get("token"), cfg.get("aes_key"), cfg.get("corpid"))
    except Exception as e:  # noqa: BLE001
        return 500, f"企业微信配置不完整：{e}"
    if c.verify_url(g("msg_signature"), g("timestamp"), g("nonce"), g("echostr")):
        return 200, g("echostr")
    return 403, "签名校验失败 —— Token 对不上，检查后台「接收消息」里的 Token 跟工作台填的是不是同一个"


def wecom_handle_post(raw: bytes, query: dict) -> tuple[int, str]:
    """收到微信消息。校验 -> 解密 -> 立刻回空串（5 秒限制）-> 后台干活。"""
    cfg = wecom_cfg()
    if not cfg.get("enabled", False):
        return 200, ""
    g = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    try:
        c = wecommod.WeComCrypto(cfg.get("token"), cfg.get("aes_key"), cfg.get("corpid"))
    except Exception as e:  # noqa: BLE001
        try:
            STORE.log_add("error", f"企业微信回调配置不完整：{e}", "wecom")
        except Exception:  # noqa: BLE001
            pass
        return 200, ""
    outer = wecommod.parse_xml(raw.decode("utf-8", "ignore"))
    r = c.decrypt_message(g("msg_signature"), g("timestamp"), g("nonce"),
                          outer.get("Encrypt") or "")
    if not r.get("ok"):
        try:
            STORE.log_add("warn", f"企业微信回调被拒：{r.get('error')}", "wecom")
        except Exception:  # noqa: BLE001
            pass
        return 200, ""
    f = r.get("fields") or {}
    if _wecom_dedup(f.get("MsgId") or ""):
        return 200, ""
    try:
        threading.Thread(target=_wecom_work, args=(f,), daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
    return 200, ""


def wecom_ingest(fields: dict) -> dict:
    """本地模拟一条微信消息（前端「模拟一条」按钮 / 冒烟测试用）。"""
    if not fields:
        return {"ok": False, "error": "没给消息内容"}
    f = dict(fields)
    f.setdefault("FromUserName", (wecom_cfg().get("touser") or "").strip("@all") or "selftest")
    f.setdefault("MsgType", "text")
    f.setdefault("Content", "")
    # 命令类的直接同步跑，方便一眼看到结果；其余丢后台
    fast = _wecom_try_command(f.get("Content", ""), f["FromUserName"])
    if fast is not None:
        return {"ok": True, "sync": True, "reply": fast["text"]}
    threading.Thread(target=_wecom_work, args=(f,), daemon=True).start()
    return {"ok": True, "sync": False, "reply": "已丢给 OpenClaw，结果会发到微信"}


# ---- 隧道：把本机 8777 临时暴露成 https，给企业微信回调 ----
# 家里宽带通常没有公网 IP，cloudflared 的 quick tunnel 让本机主动连出去，
# 换回一个 https://xxx.trycloudflare.com。不用改路由器、不用买服务器、不用备案。

TUNNEL_STATE: dict = {"proc": None, "url": "", "status": "stopped",
                      "started_at": 0.0, "log": []}
SERVER_PORT = 8777
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")


def tunnel_find() -> str:
    """找 cloudflared 可执行文件。"""
    cands = [shutil.which("cloudflared") or ""]
    la = os.environ.get("LOCALAPPDATA") or ""
    if la:
        cands += [os.path.join(la, "cloudflared", "cloudflared.exe"),
                  os.path.join(la, "Microsoft", "WinGet", "Links", "cloudflared.exe")]
    cands += [os.path.join(BASE, "bin", "cloudflared.exe"),
              r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
              r"C:\Program Files\cloudflared\cloudflared.exe",
              "/usr/local/bin/cloudflared", "/opt/homebrew/bin/cloudflared"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def _tunnel_reader(proc) -> None:
    """cloudflared 把地址打在 stderr 上，逐行读出来抓 trycloudflare 域名。"""
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            TUNNEL_STATE["log"] = (TUNNEL_STATE.get("log") or [] + [line.strip()[:300]])[-40:]
            if not TUNNEL_STATE.get("url"):
                m = _TUNNEL_URL_RE.search(line)
                if m:
                    TUNNEL_STATE["url"] = m.group(0)
                    TUNNEL_STATE["status"] = "running"
                    cf = wecom_cfg()
                    cf["tunnel"] = m.group(0)
                    cf["callback_url"] = m.group(0) + "/wecom/callback"
                    save_config(CFG)
    except Exception:  # noqa: BLE001
        pass
    finally:
        TUNNEL_STATE["proc"] = None
        TUNNEL_STATE["status"] = "stopped"


def tunnel_state() -> dict:
    proc = TUNNEL_STATE.get("proc")
    running = bool(proc and proc.poll() is None)
    if not running:
        TUNNEL_STATE["status"] = "stopped"
    exe = tunnel_find()
    return {
        "ok": running,
        "status": TUNNEL_STATE.get("status") or "stopped",
        "url": (TUNNEL_STATE.get("url") or "") if running else "",
        "installed": bool(exe),
        "exe": exe,
        "log": TUNNEL_STATE.get("log") or [],
        "started_at": TUNNEL_STATE.get("started_at") or 0,
        "callback_url": _wecom_callback_url(),
    }


def tunnel_start(port: int = 0) -> dict:
    proc = TUNNEL_STATE.get("proc")
    if proc and proc.poll() is None:
        return {"ok": True, "msg": "隧道已经在跑了", **tunnel_state()}
    exe = tunnel_find()
    if not exe:
        return {"ok": False, "error": (
            "没找到 cloudflared。装法任选一个：\n"
            "· winget install --id Cloudflare.cloudflared\n"
            "· 或去 github.com/cloudflare/cloudflared/releases 下 "
            "cloudflared-windows-amd64.exe，改名 cloudflared.exe 丢进 workbench\\bin\\\n"
            "· macOS: brew install cloudflared")}
    p = int(port or SERVER_PORT or 8777)
    try:
        pr = subprocess.Popen(
            [exe, "tunnel", "--url", f"http://127.0.0.1:{p}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"启动 cloudflared 失败：{e}"}
    TUNNEL_STATE.update({"proc": pr, "url": "", "status": "starting",
                         "started_at": time.time(), "log": []})
    threading.Thread(target=_tunnel_reader, args=(pr,), daemon=True).start()
    return {"ok": True, "status": "starting", "msg": "隧道启动中，几秒后出地址", **tunnel_state()}


def tunnel_stop() -> dict:
    proc = TUNNEL_STATE.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    TUNNEL_STATE.update({"proc": None, "url": "", "status": "stopped"})
    return {"ok": True}


def _wecom_egress_watch() -> None:
    """启动后查一次公网出口 IP，跟上次记下的比。变了就提醒去更新可信IP。

    家庭宽带 IP 一动，企业微信发消息就会报 60020，用户很难自己想明白，
    所以这里主动喊一嗓子。
    """
    try:
        time.sleep(6)                       # 等服务完全起来，别跟启动抢资源
        r = integrations.egress_ip()
        if not r.get("ok"):
            return
        ip = r["ip"]
        cf = wecom_cfg()
        old = (cf.get("egress_ip") or "").strip()
        cf["egress_ip"] = ip
        save_config(CFG)
        if old and old != ip:
            try:
                STORE.log_add("warn",
                              f"公网出口 IP 变了：{old} -> {ip}。"
                              "如果不改「企业可信IP」，微信里就收不到工作台的消息了。", "wecom")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _rem_push_once() -> int:
    """75 第二通道：到点的提醒除了桌面通知，再往连接器推一份。

    同一条提醒只推一次。没配连接器也照样标记已处理 ——
    否则哪天配上一个连接器，会把积压的老提醒一次性全轰出来。
    """
    try:
        due = STORE.rem_due_unpushed(time.time())
    except Exception:  # noqa: BLE001
        return 0
    if not due:
        return 0
    conns = _enabled_connectors()
    for r in due:
        title = "工作台提醒"
        content = r.get("text") or "时间到了"
        for c in conns:
            try:
                res = integrations.connector_push(c, title, content)
                STORE.connector_push_log((c.get("type") or ""),
                                         (c.get("name") or c.get("id") or ""),
                                         title, bool(res.get("ok")),
                                         res.get("error") or res.get("msg") or "")
            except Exception as e:  # noqa: BLE001
                try:
                    STORE.connector_push_log((c.get("type") or ""), (c.get("name") or ""),
                                             title, False, f"{type(e).__name__}: {e}")
                except Exception:  # noqa: BLE001
                    pass
        try:
            STORE.rem_mark_pushed(r["id"])
        except Exception:  # noqa: BLE001
            pass
    _REM_PUSH_LAST.update(ts=time.time(), n=len(due), conn=len(conns))
    return len(due)


def _rem_push_loop():
    while True:
        time.sleep(30)
        try:
            _rem_push_once()
        except Exception:  # noqa: BLE001
            pass


def _bridge_summary(action: str, p: dict) -> str:
    """把一条桥动作说成人话，写进审计日志用（前端那份是给界面看的，这份给留痕）。"""
    p = p or {}
    g = lambda k, d="": str(p.get(k) if p.get(k) is not None else d)  # noqa: E731
    if action == "today/add":
        return "今日待办：" + g("text")
    if action == "today/toggle":
        return "待办勾选：#" + g("id") + " → " + ("完成" if str(p.get("done", 1)) == "1" else "取消")
    if action == "today/del":
        return "删待办：#" + g("id")
    if action == "kb/save":
        return "资料库：" + g("title")
    if action == "projects/save":
        return "项目：" + g("name")
    if action == "cal/add":
        return "日历：%s %s–%s %s" % (g("day"), g("start"), g("end"), g("title"))
    if action == "reminders/add":
        return "提醒：" + g("text")
    if action == "inbox/add":
        return "捕捉：" + g("text")
    return action + (" #" + g("id") if p.get("id") else "")


# ---- OpenClaw 预设任务模板：按场景预写，点一下就填进输入框 ----
CLAW_TEMPLATES = [
    {"id": "tidy-files", "name": "整理文件", "hint": "翻目录、找重复、报大文件",
     "task": "扫一遍我的 C 盘下载文件夹和桌面，列出：最占地方的 10 个文件、"
             "看起来重复的文件组、还有超过 90 天没动过的大文件。只列不删，"
             "给出建议的处理方式。"},
    {"id": "daily-summary", "name": "写今日总结", "hint": "结合工作台上下文",
     "task": "根据上下文里今天的待办完成情况和日志，写一份今天的工作总结，"
             "分「做完的」「没做完的」「明天先做哪件」三段，每段不超过 5 行。"},
    {"id": "sys-check", "name": "查系统状态", "hint": "磁盘/内存/进程",
     "task": "查一下这台机器的整体状态：三个盘各剩多少空间、内存占用、"
             "CPU 占用最高的 5 个进程。用表格回我，并指出有没有需要马上处理的。"},
    {"id": "room-plan", "name": "房间布置建议", "hint": "20 平米长方形",
     "task": "我有个 20 平米的长方形房间要布置，需要放下床、书桌、衣柜和一台台式机。"
             "给我 2 套布局方案，说明各自取舍，并列出需要买的东西和大致预算。"},
    {"id": "money-idea", "name": "赚钱方向评估", "hint": "诚实优先，别画饼",
     "task": "我还是学生，时间有限、没本钱。评估一下我目前能做的几个副业方向，"
             "按「上手难度 / 每月能挣多少 / 要投入多少时间」打分，"
             "并明确指出哪些是坑。别安慰我，说实话。"},
    {"id": "read-note", "name": "读书笔记", "hint": "把资料库里的东西写成小论文",
     "task": "基于上下文里资料库的近期条目，帮我整理成一篇有观点的小论文："
             "先给结论，再给三条依据，最后写一段「我不同意的地方」。"},
]

# OpenClaw 的 agent 跑起来是重活（会起自己的进程、碰系统资源），
# 同时丢几件事进去互相抢会出怪问题。这里排成一队一个接一个跑。
_Q_LOCK = threading.Lock()
_Q: list[dict] = []
_Q_SEQ = [0]
_Q_WORKER: list[threading.Thread] = []


def _q_snapshot() -> list[dict]:
    with _Q_LOCK:
        return [dict(x) for x in _Q]


def _q_add(task: str, ctx: str, agent: str, timeout: int, parts=None) -> dict:
    with _Q_LOCK:
        _Q_SEQ[0] += 1
        item = {
            "id": _Q_SEQ[0], "task": task, "status": "waiting", "ts": time.time(),
            "ms": 0, "error": "", "preview": "", "agent": agent,
            "_ctx": ctx, "_timeout": timeout, "_parts": parts,
        }
        _Q.append(item)
    _q_ensure_worker()
    return {"ok": True, "id": item["id"], "waiting": len(_q_snapshot())}


def _q_clear() -> dict:
    with _Q_LOCK:
        keep = [x for x in _Q if x["status"] in ("waiting", "running")]
        gone = len(_Q) - len(keep)
        _Q[:] = keep
    return {"ok": True, "cleared": gone}


def _q_ensure_worker() -> None:
    if any(t.is_alive() for t in _Q_WORKER):
        return
    t = threading.Thread(target=_q_loop, daemon=True)
    _Q_WORKER.append(t)
    t.start()


def _q_loop() -> None:
    while True:
        with _Q_LOCK:
            nxt = next((x for x in _Q if x["status"] == "waiting"), None)
            if nxt is None:
                return
            nxt["status"] = "running"
            nxt["ms"] = 0
        t0 = time.time()
        try:
            r = _claw_run_with_retry(nxt["task"], nxt.get("_ctx") or "",
                                     int(nxt.get("_timeout") or 240),
                                     nxt.get("agent") or "")
            ok = bool(r.get("ok"))
            reply = (r.get("reply") or r.get("error") or "")
            err = "" if ok else (r.get("error") or reply or "未知原因")
        except Exception as e:  # noqa: BLE001
            ok, reply, err = False, "", str(e)
        ms = int((time.time() - t0) * 1000)
        with _Q_LOCK:
            nxt["status"] = "done" if ok else "failed"
            nxt["ms"] = ms
            nxt["error"] = (err or "")[:400]
            nxt["preview"] = (reply or "")[:400]
            nxt.pop("_ctx", None)
        try:
            STORE.openclaw_log(nxt["task"], reply, 1 if ok else 0, "queue",
                               nxt.get("agent") or "", ms / 1000.0, nxt["id"])
        except Exception:
            pass


# Gateway 挂掉这类错通常是抽风，重试一次八成能过；任务本身写错就没必要重试
_CLAW_RETRY_RE = re.compile(
    r"no gateway|gateway (is )?not running|start the gateway|gateway unavailable"
    r"|ECONNREFUSED|ETIMEDOUT|socket hang up|timed? ?out|rate ?limit|429|50[234]",
    re.I,
)


def _claw_run_with_retry(task: str, ctx: str, timeout: int, agent: str = "",
                         model: str = "") -> dict:
    """失败重试：只在「像抽风」的错误上自动再试一次，并把试了几次带回给前端。"""
    r = integrations.openclaw_run(task, ctx, timeout, agent, model)
    if r.get("ok"):
        r["attempts"] = 1
        return r
    blob = (r.get("error") or "") + " " + (r.get("raw") or "")
    if not _CLAW_RETRY_RE.search(blob):
        r["attempts"] = 1
        r["retried"] = False
        return r
    r["attempts"] = 1
    r["retried"] = True
    time.sleep(1.2)
    r2 = integrations.openclaw_run(task, ctx, timeout, agent, model)
    r2["attempts"] = 2
    r2["retried"] = True
    r2["first_error"] = (r.get("error") or "")[:300]
    return r2


# ---------------- L 域：系统工具（105-114）----------------

def _ports_used() -> list[dict]:
    """111 端口占用：netstat -ano 取 LISTENING/UDP，tasklist 把 PID 换成进程名。"""
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                           timeout=20, errors="replace")
    except Exception:  # noqa: BLE001
        return []
    names: dict[str, str] = {}
    try:
        t = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, timeout=20, errors="replace")
        for line in t.stdout.splitlines():
            parts = [x.strip('"') for x in line.split('","')]
            if len(parts) >= 2:
                names[parts[1]] = parts[0]
    except Exception:  # noqa: BLE001
        pass
    seen, rows = set(), []
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) < 4:
            continue
        proto = f[0].upper()
        if proto not in ("TCP", "UDP"):
            continue
        state = f[3].upper() if proto == "TCP" and len(f) >= 5 else ""
        if proto == "TCP" and state != "LISTENING":
            continue
        local, pid = f[1], f[-1]
        port = local.rsplit(":", 1)[-1] if ":" in local else local
        if not port.isdigit():
            continue
        key = (proto, port, pid)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"proto": proto, "port": int(port), "addr": local,
                     "pid": int(pid) if pid.isdigit() else 0,
                     "name": names.get(pid, ""), "state": state or "-"})
    rows.sort(key=lambda x: x["port"])
    return rows[:400]


CLEAN_HINT_EXT = (".exe", ".msi", ".zip", ".7z", ".rar", ".iso", ".dmg", ".pkg",
                  ".cab", ".tmp", ".old", ".bak", ".log")
CLEAN_DIRS = ("%TEMP%", "%LOCALAPPDATA%\\Temp", "%USERPROFILE%\\Downloads")


def _cleanup_scan(min_mb: int = 100, days: int = 30, limit: int = 80) -> dict:
    """112 清理建议：扫临时/下载目录里的大文件与旧安装包。**只列不删**。"""
    import glob as _glob
    min_size = max(1, min_mb) * 1024 * 1024
    cutoff = time.time() - max(1, days) * 86400
    hits, dirs = [], []
    for d in CLEAN_DIRS:
        p = os.path.expandvars(d)
        if not p or not os.path.isdir(p):
            continue
        dirs.append(p)
        for fp in _glob.glob(os.path.join(p, "**", "*"), recursive=True):
            try:
                if not os.path.isfile(fp):
                    continue
                st = os.stat(fp)
            except OSError:
                continue
            ext = os.path.splitext(fp)[1].lower()
            big = st.st_size >= min_size
            old_pkg = ext in CLEAN_HINT_EXT and st.st_mtime < cutoff
            if not (big or old_pkg):
                continue
            hits.append({"path": fp, "size": st.st_size, "mtime": st.st_mtime,
                         "ext": ext, "reason": "大文件" if big else "旧安装包/临时"})
    hits.sort(key=lambda x: x["size"], reverse=True)
    return {"dirs": dirs, "rows": hits[:limit], "count": len(hits),
            "total": sum(h["size"] for h in hits),
            "min_mb": min_mb, "days": days}


def _env_check(cfg: dict) -> list[dict]:
    """113 环境体检：python / node / ollama / openclaw / git / wps 一键看版本。"""
    rows = []

    def probe(name, args):
        t0 = time.time()
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=25,
                               errors="replace")
            lines = (r.stdout or r.stderr or "").strip().splitlines()
            return {"name": name, "ok": bool(lines) and r.returncode == 0,
                    "detail": (lines[0] if lines else "")[:140],
                    "ms": int((time.time() - t0) * 1000)}
        except FileNotFoundError:
            return {"name": name, "ok": False, "detail": "没找到可执行文件", "ms": 0}
        except Exception as e:  # noqa: BLE001
            return {"name": name, "ok": False, "detail": str(e)[:140], "ms": 0}

    rows.append(probe("Python", [sys.executable, "-V"]))
    for name, exe, args in (("Node.js", shutil.which("node"), ["-v"]),
                            ("Ollama", shutil.which("ollama"), ["--version"]),
                            ("Git", shutil.which("git"), ["--version"])):
        rows.append(probe(name, [exe] + args) if exe else
                    {"name": name, "ok": False, "detail": "不在 PATH 里", "ms": 0})
    claw = integrations.resolve_openclaw_cmd()
    rows.append(probe("OpenClaw", list(claw) + ["--version"]) if claw else
                {"name": "OpenClaw", "ok": False, "detail": "没找到 openclaw 命令（npm i -g）", "ms": 0})
    for name, app, hint in (("WPS 文字", "wps", "没装 WPS 文字"), ("WPS 表格", "et", "没装 WPS 表格")):
        p = integrations.find_wps(app)
        rows.append({"name": name, "ok": bool(p), "detail": p or hint, "ms": 0})
    ai = ((cfg.get("ai") or {}).get("base_url") or "")
    rows.append({"name": "AI 后端", "ok": bool(ai), "detail": ai or "设置里没填 base_url", "ms": 0})
    rows.append({"name": "ConPTY 终端", "ok": conpty.AVAILABLE, "ms": 0,
                 "detail": "可用（Windows 10 1809+）" if conpty.AVAILABLE else "本机不支持 ConPTY"})
    rows.append({"name": "配置文件", "ok": os.path.isfile(CONFIG_PATH), "ms": 0,
                 "detail": CONFIG_PATH})
    return rows


def _cron_exec(c) -> dict:
    """108 跑一条定时任务：kind=cmd 走 shell，kind=claw 交给 OpenClaw。"""
    payload = (c.get("payload") or "").strip()
    if not payload:
        return {"ok": False, "error": "任务是空的"}
    kind = (c.get("kind") or "cmd").lower()
    t0 = time.time()
    if kind == "claw":
        ctx = ""
        try:
            ctx = _openclaw_ctx_parts()
        except Exception:  # noqa: BLE001
            ctx = ""
        r = _claw_run_with_retry(payload, ctx, 180)
        out = r.get("reply") or r.get("error") or ""
        return {"ok": bool(r.get("ok")), "out": out[:4000], "error": r.get("error", ""),
                "dur": round(time.time() - t0, 1)}
    try:
        rr = subprocess.run(payload, shell=True, cwd=BASE, capture_output=True,
                            text=True, timeout=120, errors="replace")
        return {"ok": rr.returncode == 0, "out": (rr.stdout or "")[-4000:],
                "error": (rr.stderr or "")[-2000:], "code": rr.returncode,
                "dur": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超时（120 秒）", "dur": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "dur": round(time.time() - t0, 1)}


def _openclaw_ctx_parts() -> str:
    """给 cron 用的轻上下文（不依赖 Handler 实例）。"""
    try:
        d = today_str()
    except Exception:  # noqa: BLE001
        d = ""
    return f"今天是 {d}。" if d else ""


# ---- M 域：技能推荐（120）----

def _skill_tokens(s: str) -> set:
    """把技能名/说明拆成可比的关键词：ASCII 词（≥3 字）+ 中文二元组。"""
    s = (s or "").lower()
    toks = set(re.findall(r"[a-z0-9_]{3,}", s))
    # 中日韩统一表意文字：按单字成二元组，跟 J 域倒排索引一个思路
    cn = re.findall(r"[\u4e00-\u9fff]", s)
    for i in range(len(cn) - 1):
        toks.add(cn[i] + cn[i + 1])
    return toks


def _skill_recommend(limit: int = 8) -> dict:
    """按使用习惯推荐：拿「常用 + 收藏」技能的关键词当画像，
    在没用过、又能用的技能里按关键词重合度打分排序。没有画像时
    退化成「都可用但还没用过」的清单，并如实标注原因。"""
    wb = integrations.workbuddy_skills(extra_roots=STORE.skill_dirs_list()).get("rows", [])
    claw = integrations.openclaw_skills().get("rows", [])
    cand = []
    for r in wb:
        cand.append({"key": "wb|" + r["name"], "name": r["name"], "desc": r.get("desc", ""),
                     "src": r.get("src", "WorkBuddy"), "srcKey": "wb", "ok": True})
    for r in claw:
        cand.append({"key": "claw|" + r["name"], "name": r["name"], "desc": r.get("desc", ""),
                     "src": "OpenClaw", "srcKey": "claw",
                     "ok": bool(r.get("eligible")) and not r.get("disabled")})

    used = STORE.skill_runs_map()
    favs = set(STORE.skill_fav_list())
    used_keys = set(used.keys())

    # 画像：用得最多的前 5 + 收藏的
    top = sorted(used.values(), key=lambda x: x.get("runs", 0), reverse=True)[:5]
    prof: set = set()
    name_of = {}
    for r in cand:
        name_of[r["key"]] = r["name"]
    for t in top:
        prof |= _skill_tokens(t.get("name", ""))
    for k in favs:
        prof |= _skill_tokens(name_of.get(k, k.split("|", 1)[-1]))

    out = []
    for c in cand:
        if c["key"] in used_keys or c["key"] in favs:
            continue
        if not c["ok"]:
            continue
        toks = _skill_tokens(c["name"] + " " + c["desc"])
        inter = prof & toks
        score = len(inter) * 3
        if prof and not inter:
            continue
        reason = "和你常用的技能相关" if inter else "可用但还没用过，试试"
        out.append({**c, "score": score, "reason": reason})

    out.sort(key=lambda x: (-x["score"], x["name"].lower()))
    return {"ok": True, "rows": out[:limit], "has_profile": bool(prof)}


def today_str() -> str:
    return time.strftime("%Y-%m-%d")


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

    def _text(self, body: str, ctype: str = "text/plain; charset=utf-8",
              filename: str = "", code: int = 200):
        """非 JSON 的裸文本响应（ICS 导出、企业微信回调这类要落成文件用）。"""
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data: bytes, ctype: str = "application/octet-stream",
               filename: str = ""):
        """二进制响应（zip 打包导出用）。"""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.wfile.write(data)

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

    def _openclaw_context(self, parts=None) -> str:
        """拼一份工作台真实状态快照，注入给 OpenClaw 当背景上下文。

        parts 是模块勾选（['today','projects','kb','daylog','habits','inbox','files','cal']）。
        None 表示全给（保持老行为）；空列表表示什么都不带。
        """
        want = None if parts is None else {str(x) for x in parts}
        day = DAY()
        lines = []

        def on(k: str) -> bool:
            return want is None or k in want

        if on("today"):
            try:
                pend = STORE.today_pending(day)
            except Exception:
                pend = []
            if pend:
                lines.append("今日待办（%s）：" % day)
                for t in pend[:12]:
                    lines.append("  - " + (t.get("text") or ""))
        if on("projects"):
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
        if on("kb"):
            try:
                kbs = STORE.kb_list() or []
            except Exception:
                kbs = []
            if kbs:
                lines.append("资料库近期条目：")
                for k in kbs[:6]:
                    lines.append("  - " + (k.get("title") or "(无标题)"))
        if on("daylog"):
            try:
                dl = STORE.daylog_get(day)
            except Exception:
                dl = ""
            if dl and dl.strip():
                lines.append("今日日志摘要：" + dl.strip()[:600])
        if on("habits"):
            try:
                hs = STORE.habits_list() or []
            except Exception:
                hs = []
            if hs:
                lines.append("在跟的习惯：")
                for h in hs[:8]:
                    lines.append("  - " + (h.get("name") or ""))
        if on("inbox"):
            try:
                ib = STORE.inbox_list() or []
            except Exception:
                ib = []
            if ib:
                lines.append("快速捕捉（还没归置）：")
                for it in ib[:8]:
                    lines.append("  - " + (it.get("text") or "")[:80])
        if on("cal"):
            try:
                evs = [e for e in (STORE.events_list(day[:7]) or []) if e.get("day") == day]
            except Exception:
                evs = []
            if evs:
                lines.append("今天的日程：")
                for e in evs[:10]:
                    lines.append("  - %s–%s %s" % (e.get("start") or "", e.get("end") or "",
                                                   e.get("title") or ""))
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

    def _term_out(self, sid: str = ""):
        """SSE 流：持续把 PTY 累积输出推给前端（base64）。会话关闭时发 closed 事件。"""
        sid = sid or conpty.DEFAULT_SID
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                if not conpty.is_active(sid):
                    # 首帧就发现没活着的会话，或中途退出
                    try:
                        self.wfile.write(b"event: closed\ndata: 1\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    break
                chunk = conpty.read_available(sid)
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

    # ---------- 批量重命名：先出计划（不落盘），确认了才执行 ----------

    RENAME_BAD = set('\\/:*?"<>|')

    def _bad_new_name(self, base: str) -> str:
        b = (base or "").strip()
        if not b or b in (".", ".."):
            return "名字不能为空"
        if any(c in self.RENAME_BAD for c in b):
            return '名字里不能有 \\ / : * ? " < > |'
        if len(b) > 200:
            return "名字太长"
        return ""

    def _new_stem(self, stem: str, i: int, rule: dict) -> tuple:
        """按规则算出新主名；返回 (新主名, 新扩展名)。"""
        mode = (rule.get("mode") or "replace").lower()
        ext = rule.get("_ext", "")
        if mode == "replace":
            find = rule.get("find") or ""
            return (stem.replace(find, rule.get("repl") or "") if find else stem), ext
        if mode == "prefix":
            return (rule.get("prefix") or "") + stem, ext
        if mode == "suffix":
            return stem + (rule.get("suffix") or ""), ext
        if mode == "seq":
            try:
                start = int(rule.get("start") or 1)
                pad = max(1, min(6, int(rule.get("pad") or 2)))
            except (ValueError, TypeError):
                start, pad = 1, 2
            return ((rule.get("prefix") or "") + str(start + i).zfill(pad)
                    + (rule.get("suffix") or "")), ext
        if mode == "ext":
            newext = (rule.get("to_ext") or "").lstrip(".")
            return stem, ("." + newext if newext else "")
        return stem, ext

    def _rename_plan(self, paths: list, rule: dict) -> dict:
        if not isinstance(paths, list) or not paths:
            return {"ok": False, "error": "没有选中文件", "items": []}
        keep_ext = rule.get("keep_ext", True)
        items, used = [], set()
        for i, p in enumerate(paths[:300]):
            p = str(p or "")
            if not p:
                continue
            d, base = os.path.dirname(p), os.path.basename(p)
            stem, ext = os.path.splitext(base)
            r2 = dict(rule)
            r2["_ext"] = ext if keep_ext else ""
            newstem, newext = self._new_stem(stem, i, r2)
            newbase = newstem + (newext if keep_ext else "")
            newpath = (d.rstrip("/\\") + "/" + newbase) if newbase else ""
            why = ""
            if not os.path.isfile(p):
                why = "源文件不在了"
            elif not IDX.by_paths([p]):
                why = "不在索引里 —— 只整理扫出来的文件"
            elif newbase == base:
                why = "新名字和原来一样"
            else:
                why = self._bad_new_name(newbase)
            if not why:
                if os.path.exists(newpath):
                    why = "已经有同名文件，不覆盖"
                elif newpath.lower() in used:
                    why = "和本批另一条撞名"
            if newpath:
                used.add(newpath.lower())
            items.append({"from": p, "to": newpath, "ok": not why, "why": why})
        return {"ok": True, "items": items,
                "n_ok": sum(1 for x in items if x["ok"]), "n": len(items)}

    def _rename_go(self, items: list) -> dict:
        if not isinstance(items, list) or not items:
            return {"ok": False, "error": "没有要执行的计划", "results": []}
        results = []
        for it in items[:300]:
            a, b = str(it.get("from") or ""), str(it.get("to") or "")
            why = ""
            if not a or not b:
                why = "参数不全"
            elif not os.path.isfile(a):
                why = "源文件不在了"
            elif (os.path.dirname(os.path.normpath(a)).lower()
                  != os.path.dirname(os.path.normpath(b)).lower()):
                why = "不允许跨目录改名"
            elif os.path.exists(b):
                why = "目标已存在，拒绝覆盖"
            else:
                why = self._bad_new_name(os.path.basename(b))
            if why:
                results.append({"ok": False, "from": a, "error": why})
                continue
            try:
                os.rename(a, b)
                IDX.rename_path(a, b)
                STORE.rename_path(a, b)
                results.append({"ok": True, "from": a, "to": b})
            except OSError as e:
                results.append({"ok": False, "from": a, "error": str(e)})
        return {"ok": True, "results": results,
                "n_ok": sum(1 for r in results if r["ok"])}

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
                    "mail_accounts": _mail_accounts_public(),
                    "mail_active": _mail_acct_id(),
                    # 只报缓存值：status 每 2 秒被轮一次，不能在这里等 IMAP
                    "mail_unread": _MAIL_UNREAD["n"],
                    "mail_unread_age": round(time.time() - _MAIL_UNREAD["ts"], 1)
                    if _MAIL_UNREAD["ts"] else None,
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

        # ---- 企业微信：回调入口必须放在最前面，它不走 JSON ----
        if p == "/wecom/callback":
            code, body = wecom_handle_get(parse_qs(u.query))
            self._text(body, code=code)
            return

        if p == "/api/wecom/status":
            c = wecom_cfg()
            # Secret 是发消息的总钥匙，绝不回前端；Token / AESKey 必须回，
            # 因为要粘到企业微信后台的「接收消息」里，不显示用户没法配。
            pub = {k: v for k, v in c.items() if k != "secret"}
            pub["secret_set"] = bool(c.get("secret"))
            pub["secret_tail"] = (c.get("secret") or "")[-4:]
            t = tunnel_state()
            pub["tunnel_status"] = t["status"]
            pub["tunnel_url"] = t["url"]
            pub["tunnel_installed"] = t["installed"]
            pub["tunnel_exe"] = t["exe"]
            pub["tunnel_log"] = t["log"]
            pub["callback_url"] = _wecom_callback_url()
            pub["ready_send"] = bool(c.get("corpid") and c.get("secret") and c.get("agentid"))
            pub["ready_recv"] = bool(c.get("token") and c.get("aes_key"))
            self._json(pub)
            return

        if p == "/api/wecom/egress":
            r = integrations.egress_ip()
            if r.get("ok"):
                cf = wecom_cfg()
                cf["egress_ip"] = r["ip"]
                save_config(CFG)
            self._json(r)
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
                "wb": integrations.workbuddy_skills(extra_roots=STORE.skill_dirs_list()),
                "claw": integrations.openclaw_skills(),
                "fav": STORE.skill_fav_list(),
                "stats": STORE.skill_stats(),
                "dirs": STORE.skill_dirs_list(),
            })
            return

        if p == "/api/skills/recommend":               # 120 按使用习惯推荐
            self._json(_skill_recommend())
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
            cmd = integrations.resolve_openclaw_cmd()
            self._json({
                "exists": cmd is not None,
                "path": cmd[0] if cmd else "",
                "node": integrations.resolve_node(),
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

        if p == "/api/events/stats":
            # 74 时长统计：给周/月两种窗口各算一份
            q = parse_qs(u.query)
            from_, to_ = q.get("from", [""])[0], q.get("to", [""])[0]
            period = q.get("period", [""])[0]
            if period or not from_:
                today = DAY()
                t = datetime.strptime(today, "%Y-%m-%d")
                if period == "month":
                    a = t.strftime("%Y-%m-01")
                    b = t.strftime("%Y-%m-") + str(
                        calendar.monthrange(t.year, t.month)[1])
                else:                                  # 默认本周（周一起）
                    a = (t - timedelta(days=t.weekday())).strftime("%Y-%m-%d")
                    b = (t - timedelta(days=t.weekday()) + timedelta(days=6)).strftime("%Y-%m-%d")
            else:
                a, b = from_, to_
            self._json(STORE.events_stats(a, b))
            return

        if p == "/api/events/ics":
            q = parse_qs(u.query)
            a = q.get("from", [""])[0]
            b = q.get("to", [""])[0]
            if not a or not b:
                t = datetime.strptime(DAY(), "%Y-%m-%d")
                a = (t - timedelta(days=90)).strftime("%Y-%m-%d")
                b = (t + timedelta(days=180)).strftime("%Y-%m-%d")
            self._text(_ics_cal(a, b), "text/calendar; charset=utf-8",
                       "openworkbench.ics")
            return

        if p == "/api/today/pending":
            self._json({"rows": STORE.today_pending(parse_qs(u.query).get("day", [""])[0] or DAY())})
            return

        if p == "/api/today/stats":
            self._json(STORE.today_stats(30))
            return

        if p == "/api/today/templates":
            self._json({"rows": STORE.today_tpl_list()})
            return

        if p == "/api/today/review":
            self._json(STORE.today_review(parse_qs(u.query).get("day", [""])[0] or DAY()))
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

        # ---- K 域 生活（95-104）----

        if p == "/api/ledger":                         # 95 流水 + 当月汇总
            q = parse_qs(u.query)
            month = (q.get("month", [""])[0] or "").strip()
            self._json({
                "ok": True,
                "rows": STORE.ledger_list(month, (q.get("kind", [""])[0] or "").strip()),
                "summary": STORE.ledger_summary(month),
            })
            return

        if p == "/api/ledger/months":                  # 102 收入看板：按月对比
            self._json(STORE.ledger_months(
                int(parse_qs(u.query).get("limit", ["12"])[0] or 12)))
            return

        if p == "/api/budget":                         # 96 阈值 + 本月超标情况
            month = (parse_qs(u.query).get("month", [""])[0] or "").strip()
            self._json({"ok": True, "limits": STORE.budget_limits(),
                        "check": STORE.budget_check(month)})
            return

        if p == "/api/devices":                        # 97 设备台账 + 99 充电区
            self._json({"ok": True, "rows": STORE.devices_list(),
                        "charge": STORE.charge_board()})
            return

        if p == "/api/netmap":                         # 100 网络拓扑
            self._json({"ok": True, "rows": STORE.net_list()})
            return

        if p == "/api/wishes":                         # 101 采购清单
            self._json(STORE.wishes_list())
            return

        if p == "/api/weights":                        # 104 体重简记
            self._json({"ok": True, "rows": STORE.weight_list(),
                        "stats": STORE.weight_stats()})
            return

        if p == "/api/clip":                           # 106 剪贴板历史（?q= 搜索）
            _q = parse_qs(u.query)
            self._json({"rows": STORE.clip_list_q(
                _q.get("q", [""])[0], int(_q.get("limit", ["200"])[0] or 200))})
            return

        if p == "/api/reminders":
            self._json({"rows": STORE.rem_list()})
            return

        if p == "/api/meetings":
            month = parse_qs(u.query).get("month", [""])[0]
            self._json({"rows": STORE.meeting_list(month) if month else STORE._run(
                "SELECT * FROM meetings ORDER BY day, start LIMIT 200")})
            return

        if p == "/api/meetings/minutes":
            # 78 会议纪要：先把会议信息拼成给 OpenClaw 的写作任务返回给前端
            mid = int(parse_qs(u.query).get("id", ["0"])[0] or 0)
            rows = STORE._run("SELECT * FROM meetings WHERE id=?", (mid,))
            if not rows:
                self._json({"ok": False, "error": "没这场会议"})
                return
            row = rows[0]
            self._json({"ok": True, "row": row, "prompt": _cal_minutes_prompt(row)})
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

        if p == "/api/files/ext":
            q = parse_qs(u.query)
            self._json(IDX.ext_stats(int(q.get("limit", ["80"])[0])))
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

        if p == "/api/files/favs":
            favs = STORE.fav_paths()
            meta = {m["path"]: m for m in IDX.by_paths([f["path"] for f in favs])}
            rows = []
            for f in favs:
                m = meta.get(f["path"])
                if m:
                    m = dict(m)
                    m["fav_at"] = f.get("created")
                    rows.append(m)
            self._json({"rows": rows, "count": len(favs)})
            return

        if p == "/api/files/recent-open":
            limit = int(parse_qs(u.query).get("limit", ["200"])[0])
            rec = STORE.open_recent(limit)
            meta = {m["path"]: m for m in IDX.by_paths([r["path"] for r in rec])}
            rows = []
            for r in rec:
                m = meta.get(r["path"])
                if m:
                    m = dict(m)
                    m["opened"] = r.get("opened")
                    m["count"] = r.get("count")
                    rows.append(m)
            self._json({"rows": rows})
            return

        if p == "/api/files/ft":
            self._json(IDX.ft_stats())
            return

        if p == "/api/files/ft/search":
            q = parse_qs(u.query)
            hits = IDX.ft_search(q.get("q", [""])[0], int(q.get("limit", ["80"])[0]))
            self._json({"hits": hits, "indexed": IDX.ft_stats().get("indexed", 0)})
            return

        if p == "/api/grep":
            q = parse_qs(u.query)
            self._grep(q.get("q", [""])[0], int(q.get("limit", ["40"])[0]))
            return

        if p == "/api/projects":
            self._json({"rows": STORE.projects_board()})
            return

        if p == "/api/projects/templates":
            # 84 可选的起手模板
            self._json({"rows": store.project_templates(),
                        "default_stale_days": STORE.stale_days()})
            return

        if p == "/api/projects/timeline":
            # 85 甘特简版
            q = parse_qs(u.query)
            self._json(STORE.projects_timeline(int(q.get("project_id", ["0"])[0] or 0)))
            return

        if p == "/api/milestones":
            q = parse_qs(u.query)
            self._json({"rows": STORE.milestone_list(int(q.get("project_id", ["0"])[0] or 0))})
            return

        if p == "/api/tasks/all":
            # 83 跨项目任务一屏看
            q = parse_qs(u.query)
            self._json({"rows": STORE.tasks_all(
                q.get("state", [""])[0], int(q.get("project_id", ["0"])[0] or 0))})
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
            qq = parse_qs(u.query)
            self._json({"rows": STORE.kb_list(
                (qq.get("status", [""])[0] or "").strip(),
                int(qq.get("fav", ["-1"])[0] or -1))})
            return

        # ---- J 域资料 / 知识库（87-94）----

        if p == "/api/kb/get":                        # 详情：正文 + 双链 + 相关
            qq = parse_qs(u.query)
            kid = int(qq.get("id", ["0"])[0] or 0)
            row = STORE.kb_get(kid)
            if not row:
                self._json({"ok": False, "error": "找不到这条资料"}, 404)
                return
            self._json({"ok": True, "row": row,
                        "backlinks": STORE.kb_backlinks(kid),
                        "outlinks": STORE.kb_outlinks(kid),
                        "related": STORE.kb_related(kid, 5)})
            return

        if p == "/api/kb/search":                     # 87 全文检索
            qq = parse_qs(u.query)
            self._json(STORE.kb_search(
                (qq.get("q", [""])[0] or "").strip(),
                int(qq.get("limit", ["40"])[0] or 40)))
            return

        if p == "/api/kb/queue":                      # 89 阅读队列统计
            self._json(STORE.kb_queue())
            return

        if p == "/api/kb/graph":                      # 88 全库双链图
            self._json(STORE.kb_link_graph())
            return

        if p == "/api/kb/related":                    # 92 相关推荐
            qq = parse_qs(u.query)
            self._json({"ok": True, "rows": STORE.kb_related(
                int(qq.get("id", ["0"])[0] or 0),
                int(qq.get("limit", ["5"])[0] or 5))})
            return

        if p == "/api/kb/export":                     # 93 整库导出 zip
            items = STORE.kb_export()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                used = {}
                for it in items:
                    name = it["name"] or "kb"
                    if name in used:
                        used[name] += 1
                        name = "%s-%d" % (name, used[name])
                    else:
                        used[name] = 0
                    z.writestr(name + ".md", it["md"])
                z.writestr("_index.md",
                           "# 资料库导出\n\n共 %d 条\n\n" % len(items)
                           + "\n".join("- [%s](%s.md)" % (i["name"], i["name"])
                                       for i in items))
            self._bytes(buf.getvalue(), "application/zip", "kb-export.zip")
            return

        if p == "/api/openclaw/history":
            self._json({"rows": STORE.openclaw_recent(
                int(parse_qs(u.query).get("limit", ["30"])[0] or 30))})
            return

        if p == "/api/openclaw/search":
            q = parse_qs(u.query)
            self._json({"rows": STORE.openclaw_search(
                q.get("q", [""])[0], q.get("only", ["all"])[0],
                int(q.get("limit", ["50"])[0] or 50))})
            return

        if p == "/api/openclaw/favs":
            self._json({"rows": STORE.openclaw_favs()})
            return

        if p == "/api/openclaw/get":
            row = STORE.openclaw_get(int(parse_qs(u.query).get("id", ["0"])[0] or 0))
            self._json({"ok": bool(row), "row": row})
            return

        if p == "/api/openclaw/stats":
            days = int(parse_qs(u.query).get("days", ["30"])[0] or 30)
            self._json(STORE.openclaw_stats(days))
            return

        if p == "/api/openclaw/queue":
            now = time.time()
            rows = _q_snapshot()
            for x in rows:
                if x["status"] == "running" and x.get("ms"):
                    x["ms"] = int((now - x["ts"]) * 1000)
                x.pop("_parts", None)
            self._json({
                "rows": rows,
                "waiting": sum(1 for x in rows if x["status"] == "waiting"),
                "running": sum(1 for x in rows if x["status"] == "running"),
            })
            return

        if p == "/api/bridge/audit":
            q = parse_qs(u.query)
            self._json({"rows": STORE.bridge_audit_list(
                int(q.get("limit", ["100"])[0] or 100), q.get("action", [""])[0])})
            return

        if p == "/api/claw/templates":
            self._json({"rows": CLAW_TEMPLATES})
            return

        if p == "/api/bridge/pending":
            self._json({"rows": STORE.bridge_pending_list()})
            return

        # 交互终端输出流（SSE）：把 PTY 累积的输出以 base64 推给前端（105 多标签：?sid=）
        if p == "/api/term/out":
            self._term_out(parse_qs(u.query).get("sid", [""])[0])
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

        if p == "/api/connectors/log":
            self._json({"rows": STORE.connector_push_recent(50)})
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

        if p == "/api/term/sessions":                  # 105 现存的终端标签会话
            self._json({"rows": conpty.sessions(), "conpty": conpty.AVAILABLE})
            return

        if p == "/api/cron":                           # 108 定时任务列表
            self._json({"ok": True, "rows": STORE.cron_list(),
                        "due": STORE.cron_due(),
                        "openclaw": integrations.resolve_openclaw_cmd() is not None})
            return

        if p == "/api/cron/due":                       # 108 到点该跑的（前端轮询）
            self._json({"ok": True, "rows": STORE.cron_due()})
            return

        if p == "/api/logs":                           # 114 工作台自身运行日志
            q = parse_qs(u.query)
            rows = STORE.log_list(int(q.get("limit", ["300"])[0] or 300),
                                  q.get("level", [""])[0])
            self._json({"ok": True, "rows": rows, "stats": STORE.log_stats()})
            return

        if p == "/api/ports":                          # 111 端口占用
            self._json({"ok": True, "rows": _ports_used()})
            return

        if p == "/api/cleanup":                        # 112 清理建议（只报不删）
            q = parse_qs(u.query)
            self._json({"ok": True, **_cleanup_scan(
                int(q.get("min_mb", ["100"])[0] or 100),
                int(q.get("days", ["30"])[0] or 30),
                int(q.get("limit", ["80"])[0] or 80))})
            return

        if p == "/api/envcheck":                       # 113 环境体检
            self._json({"ok": True, "rows": _env_check(CFG)})
            return

        if p == "/api/speedtest":                      # 110 网速测试：下发测试数据，前端计时算 Mbps
            mb = parse_qs(u.query).get("mb", ["4"])[0]
            try:
                mb = max(1, min(32, int(mb or 4)))
            except (TypeError, ValueError):
                mb = 4
            self._bytes(os.urandom(mb * 1024 * 1024), "application/octet-stream",
                        f"speedtest_{mb}mb.bin")
            return

        if p == "/api/files/preview":
            _pv = parse_qs(u.query).get("path", [""])[0]
            if _pv:
                STORE.open_log(_pv)   # 看过也算用过，进「最近打开」
            self._preview(_pv)
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

        # ---------- F 域：文档工作台（列表 / 搜索 / 版本历史）----------
        if p == "/api/docs/list":
            q = parse_qs(u.query)
            self._json({"rows": STORE.docs_list(
                q.get("q", [""])[0], int(q.get("limit", ["200"])[0] or 200))})
            return

        if p == "/api/docs/get":
            row = STORE.docs_get(int(parse_qs(u.query).get("id", ["0"])[0] or 0))
            self._json({"ok": bool(row), "row": row})
            return

        if p == "/api/docs/snaps":
            q = parse_qs(u.query)
            self._json({"rows": STORE.docs_snaps(
                int(q.get("id", ["0"])[0] or 0), int(q.get("limit", ["50"])[0] or 50))})
            return

        if p == "/api/docs/snap":
            row = STORE.docs_snap_get(int(parse_qs(u.query).get("sid", ["0"])[0] or 0))
            self._json({"ok": bool(row), "row": row})
            return

        if p == "/api/docs/raw":
            row = STORE.docs_get(int(parse_qs(u.query).get("id", ["0"])[0] or 0))
            if not row:
                self._json({"ok": False, "error": "没这篇文档"})
                return
            self._json({"ok": True, "title": row.get("title") or "文档",
                        "md": row.get("md") or ""})
            return

        # ---------- G 域：邮件（多账号 / 规则 / 正文搜 / 草稿 / 发件队列 / 未读）----------
        if p == "/api/mail/unread":
            force = parse_qs(u.query).get("force", ["0"])[0] in ("1", "true")
            self._json(_mail_unread_cached(0 if force else 300))
            return

        if p == "/api/mail/accounts":
            cur = {k: CFG["mail"].get(k) for k in MAIL_TLS_FIELDS if k != "password"}
            cur["password_set"] = bool(CFG["mail"].get("password"))
            self._json({"rows": _mail_accounts_public(), "active": _mail_acct_id(),
                        "mail": cur})
            return

        if p == "/api/mail/rules":
            self._json({"rows": STORE.mail_rules_list()})
            return

        if p == "/api/mail/search":
            q = parse_qs(u.query)
            term = q.get("q", [""])[0]
            self._json({"rows": STORE.mail_body_search(
                term, int(q.get("limit", ["50"])[0] or 50)),
                "cached_total": STORE.mail_body_count(), "q": term})
            return

        if p == "/api/mail/drafts":
            self._json({"rows": STORE.mail_drafts()})
            return

        if p == "/api/mail/draft":
            row = STORE.mail_draft_get(int(parse_qs(u.query).get("id", ["0"])[0] or 0))
            self._json({"ok": bool(row), "row": row})
            return

        if p == "/api/mail/outbox":
            self._json({"rows": STORE.mail_outbox_list(
                int(parse_qs(u.query).get("limit", ["100"])[0] or 100)),
                "pending": STORE.mail_outbox_pending()})
            return

        if p == "/api/mail/list":
            q = parse_qs(u.query)
            r = mail_client().list(
                int(q.get("limit", ["30"])[0]),
                q.get("unseen", ["0"])[0] == "1",
                q.get("q", [""])[0],
            )
            # 64 收件规则 + 本地标签/星标：列表回来就地补齐，前端不用再问一遍
            if r.get("ok"):
                acct = _mail_acct_id()
                uids = [x["uid"] for x in r.get("rows") or []]
                marks = STORE.mail_meta_map(acct, uids)
                for x in r.get("rows") or []:
                    auto = _mail_rules_tags(x.get("subject"), x.get("from"))
                    mine = (marks.get(x["uid"]) or {}).get("tags") or ""
                    merged = " / ".join([t for t in (auto, mine) if t])
                    x["tags"] = merged
                    x["auto_tags"] = auto
                    x["starred"] = (marks.get(x["uid"]) or {}).get("starred") or 0
            self._json(r)
            return

        if p == "/api/mail/diag":
            self._json(mail_client().diagnose())
            return

        if p == "/api/mail/read":
            q = parse_qs(u.query)
            r = mail_client().read(q.get("uid", [""])[0], q.get("mark", ["1"])[0] != "0")
            # 67 正文搜索要有料：读过的信就把正文缓存到本机，之后离线也能搜
            if r.get("ok"):
                try:
                    STORE.mail_body_put(_mail_acct_id(), r.get("uid") or "",
                                        r.get("subject") or "", r.get("from") or "",
                                        r.get("date") or "", r.get("body") or "")
                except Exception:  # noqa: BLE001
                    pass
                r["tags"] = _mail_rules_tags(r.get("subject"), r.get("from"))
                r["auto_tags"] = r["tags"]
                m = STORE.mail_meta_map(_mail_acct_id(), [r.get("uid") or ""])
                r["my_tags"] = (m.get(r.get("uid") or "") or {}).get("tags") or ""
                r["starred"] = (m.get(r.get("uid") or "") or {}).get("starred") or 0
            self._json(r)
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

        # 110 上传测速：只量客户端送上来多少字节，不落盘
        if p == "/api/speedtest/upload":
            n = int(self.headers.get("Content-Length") or 0)
            got = 0
            try:
                while got < n:
                    chunk = self.rfile.read(min(65536, n - got))
                    if not chunk:
                        break
                    got += len(chunk)
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "bytes": got})
            return

        # ---- 企业微信回调：原始 XML + query 签名，不能用 _body() 解 JSON ----
        if p == "/wecom/callback":
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            code, text = wecom_handle_post(raw, parse_qs(u.query))
            self._text(text, code=code)
            return

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
            b_pri = body.get("priority")
            self._json(STORE.today_add(
                body.get("day") or DAY(), body.get("text", "").strip(),
                int(body.get("project_id", 0) or 0),
                priority=1 if b_pri is None else int(b_pri),
                est=body.get("est", 0) or 0,
                note=body.get("note", "") or "",
                repeat=body.get("repeat", "") or "",
                parent_id=int(body.get("parent_id", 0) or 0),
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

        if p == "/api/today/priority":
            self._json(STORE.today_priority(int(body.get("id", 0)), int(body.get("p", 1))))
            return

        if p == "/api/today/est":
            self._json(STORE.today_est(int(body.get("id", 0)), body.get("est", 0)))
            return

        if p == "/api/today/note":
            self._json(STORE.today_note(int(body.get("id", 0)), body.get("note", "")))
            return

        if p == "/api/today/sub":
            self._json(STORE.today_add(
                body.get("day") or DAY(), body.get("text", "").strip(),
                parent_id=int(body.get("parent_id", 0) or 0),
            ))
            return

        if p == "/api/today/defer":
            self._json(STORE.today_defer(int(body.get("id", 0)), body.get("to", "") or ""))
            return

        if p == "/api/today/batch":
            self._json(STORE.today_batch(body.get("ids") or [], body.get("op", "")))
            return

        if p == "/api/today/pomo":
            if body.get("op") == "start":
                self._json(STORE.today_pomo_start(int(body.get("id", 0))))
            else:
                self._json(STORE.today_pomo_stop())
            return

        if p == "/api/today/template/save":
            self._json(STORE.today_tpl_save(body.get("name", ""), body.get("items") or []))
            return

        if p == "/api/today/template/del":
            self._json(STORE.today_tpl_del(int(body.get("id", 0))))
            return

        if p == "/api/today/template/apply":
            self._json(STORE.today_tpl_apply(
                int(body.get("id", 0)), body.get("day") or DAY()))
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

        # ---- K 域 生活（95-104）----

        if p == "/api/ledger/add":
            self._json(STORE.ledger_add(
                body.get("day") or DAY(), (body.get("kind") or "支出").strip(),
                body.get("amount"), (body.get("category") or "").strip(),
                body.get("note", "")))
            return

        if p == "/api/ledger/del":
            self._json(STORE.ledger_del(int(body.get("id", 0))))
            return

        if p == "/api/budget/save":                    # 96 存分类阈值
            self._json(STORE.budget_limits_save(body.get("limits") or {}))
            return

        if p == "/api/budget/push":                    # 96 把超支提醒推给连接器
            month = (body.get("month") or "").strip()
            chk = STORE.budget_check(month)
            over = chk.get("over") or []
            if not over:
                self._json({"ok": False, "error": "这个月没有超支的分类，不用推"})
                return
            txt = "【超支提醒】" + chk["month"] + "\n" + "\n".join(
                "· %s：已花 ¥%.2f / 阈值 ¥%.2f（超 ¥%.2f）"
                % (o["cat"], o["used"], o["limit"], o["used"] - o["limit"]) for o in over)
            conns = _enabled_connectors()
            if not conns:
                self._json({"ok": False, "error": "还没启用任何连接器（设置页里加一个）"})
                return
            title = "超支提醒"
            sent, failed = [], []
            for c in conns:
                try:
                    res = integrations.connector_push(c, title, txt)
                except Exception as e:  # noqa: BLE001
                    res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                who = c.get("name") or c.get("id") or c.get("type") or "?"
                (sent if res.get("ok") else failed).append(who)
                STORE.connector_push_log((c.get("type") or ""), who, title,
                                         bool(res.get("ok")),
                                         res.get("error") or res.get("msg") or "")
            self._json({"ok": bool(sent), "sent": sent, "failed": failed, "text": txt,
                        "error": "" if sent else "推送都失败了，看连接器日志"})
            return

        if p == "/api/budget/check":                   # 96 只查不改，给前端弹窗用
            self._json(STORE.budget_check((body.get("month") or "").strip()))
            return

        if p == "/api/devices/save":
            self._json(STORE.device_save(
                body.get("id") or None, body.get("name", ""), body.get("kind", ""),
                body.get("zone", ""), body.get("bought", ""), body.get("warranty") or 0,
                body.get("price") or 0, body.get("charge", ""), body.get("note", "")))
            return

        if p == "/api/devices/charge":                 # 99 改充电状态
            self._json(STORE.device_charge(
                int(body.get("id", 0)), (body.get("charge") or "").strip()))
            return

        if p == "/api/devices/del":
            self._json(STORE.device_del(int(body.get("id", 0))))
            return

        if p == "/api/netmap/save":
            self._json(STORE.net_save(
                body.get("id") or None, body.get("name", ""), body.get("kind", ""),
                body.get("parent") or 0, body.get("port", ""), body.get("ip", ""),
                body.get("note", "")))
            return

        if p == "/api/netmap/del":
            self._json(STORE.net_del(int(body.get("id", 0))))
            return

        if p == "/api/wishes/save":
            self._json(STORE.wish_save(
                body.get("id") or None, body.get("name", ""), body.get("price") or 0,
                body.get("shop", ""), body.get("url", ""), body.get("priority") or 2,
                (body.get("status") or "想要").strip(), body.get("note", "")))
            return

        if p == "/api/wishes/buy":                     # 101 一键已购（顺手记支出）
            self._json(STORE.wish_buy(int(body.get("id", 0)), body.get("day") or ""))
            return

        if p == "/api/wishes/del":
            self._json(STORE.wish_del(int(body.get("id", 0))))
            return

        if p == "/api/weights/add":
            self._json(STORE.weight_add(
                body.get("day") or DAY(), body.get("kg"), body.get("note", "")))
            return

        if p == "/api/weights/del":
            self._json(STORE.weight_del(int(body.get("id", 0))))
            return

        if p == "/api/life/migrate":                   # 老 lists 数据搬到新表
            self._json(STORE.life_migrate())
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
        if p == "/api/clip/pin":                       # 106 置顶
            self._json(STORE.clip_pin(int(body.get("id", 0)), body.get("on", 1)))
            return

        # ---- 108 定时任务（cron 简版）----
        if p == "/api/cron/save":
            self._json(STORE.cron_save(
                body.get("id") or None, body.get("name", ""), body.get("kind", "cmd"),
                body.get("payload", ""), body.get("sched", ""),
                body.get("enabled", 1), int(body.get("notify", 0) or 0)))
            return
        if p == "/api/cron/toggle":
            self._json(STORE.cron_toggle(int(body.get("id", 0)), body.get("on", 1)))
            return
        if p == "/api/cron/del":
            self._json(STORE.cron_del(int(body.get("id", 0))))
            return
        if p == "/api/cron/run":                       # 立即跑一次（也用于到点后前端触发）
            cid = int(body.get("id", 0))
            c = STORE.cron_get(cid)
            if not c:
                self._json({"ok": False, "error": "没这条任务"})
                return
            r = _cron_exec(c)
            STORE.cron_mark(cid, bool(r.get("ok")), (r.get("out") or r.get("error") or "")[:800])
            STORE.log_add("ok" if r.get("ok") else "err",
                          f"定时任务「{c.get('name') or cid}」执行{'成功' if r.get('ok') else '失败'}",
                          "cron")
            if c.get("notify") and (r.get("out") or r.get("error")):
                try:
                    _push_all(f"⏰ {c.get('name') or '定时任务'}",
                              (r.get("out") or r.get("error") or "")[:1500])
                except Exception:  # noqa: BLE001
                    pass
            r["row"] = STORE.cron_get(cid)
            self._json(r)
            return

        # ---- 114 日志 ----
        if p == "/api/logs/clear":
            self._json(STORE.log_clear())
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

        # ---- 交互终端（ConPTY 真终端，仅 Windows 10 1809+ 可用）105 多标签：按 sid 分会话 ----
        if p == "/api/term/start":
            ok, msg = conpty.start_session(
                cols=int(body.get("cols") or 120), rows=int(body.get("rows") or 30),
                sid=str(body.get("sid") or conpty.DEFAULT_SID))
            self._json({"ok": ok, "error": msg, "sid": str(body.get("sid") or conpty.DEFAULT_SID)})
            return

        if p == "/api/term/in":
            ok, msg = conpty.write_input(body.get("data", ""), str(body.get("sid") or conpty.DEFAULT_SID))
            self._json({"ok": ok, "error": msg})
            return

        if p == "/api/term/resize":
            conpty.resize(int(body.get("cols") or 0), int(body.get("rows") or 0),
                          str(body.get("sid") or conpty.DEFAULT_SID))
            self._json({"ok": True})
            return

        if p == "/api/term/close":                     # 105 关掉某个标签的会话
            conpty.close_session(str(body.get("sid") or conpty.DEFAULT_SID))
            self._json({"ok": True, "sessions": conpty.sessions()})
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
            # 73 重复规则 / 77 颜色分类 / 75 提前提醒，一并交给 store
            self._json(STORE.event_save(
                body.get("id") or None, body.get("day", ""), body.get("start", ""),
                body.get("end", ""), body.get("title", "").strip(), body.get("note", ""),
                body.get("source", "manual"),
                body.get("repeat", "") or "", body.get("repeat_until", "") or "",
                body.get("color", "") or "", body.get("remind_before", 0) or 0,
            ))
            return

        if p == "/api/events/exdate":
            # 73 删重复日程里的某一次
            self._json(STORE.event_exdate(int(body.get("id", 0)), body.get("day", "")))
            return

        if p == "/api/events/move":
            # 72 拖拽改时间（重复日程拖某次会自动拆成独立一条）
            self._json(STORE.event_move(
                int(body.get("id", 0)), body.get("occ", ""), body.get("day", ""),
                body.get("start", ""), body.get("end", ""),
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

        # ---------- G 域：邮件写操作 ----------
        if p == "/api/mail/accounts/save":
            self._mail_account_save(body)
            return

        if p == "/api/mail/accounts/del":
            aid = str(body.get("id") or "")
            CFG["mail_accounts"] = [x for x in (CFG.get("mail_accounts") or [])
                                    if str(x.get("id")) != aid]
            if _mail_acct_id() == aid:
                CFG["mail_active"] = ""
            save_config(CFG)
            self._json({"ok": True, "rows": _mail_accounts_public()})
            return

        if p == "/api/mail/accounts/active":
            self._json(_mail_apply_active(str(body.get("id") or "")))
            return

        if p == "/api/mail/rules/save":
            self._json(STORE.mail_rule_save(
                int(body.get("id", 0) or 0), (body.get("name") or "").strip(),
                (body.get("field") or "from").strip(),
                (body.get("contains") or "").strip(), (body.get("tag") or "").strip()))
            return

        if p == "/api/mail/rules/del":
            self._json(STORE.mail_rule_del(int(body.get("id", 0) or 0)))
            return

        if p == "/api/mail/tag":
            self._json(STORE.mail_tag(_mail_acct_id(), str(body.get("uid") or ""),
                                      body.get("tags") or ""))
            return

        if p == "/api/mail/star":
            self._json(STORE.mail_star(_mail_acct_id(), str(body.get("uid") or ""),
                                       body.get("on")))
            return

        if p == "/api/mail/att/save":
            uid = str(body.get("uid") or "")
            if not uid:
                self._json({"ok": False, "error": "没给 uid"})
                return
            outdir = os.path.join(MAIL_ATT, _uid_dir(uid))
            self._json(mail_client().fetch_attachments(uid, outdir))
            return

        if p == "/api/mail/draft/save":
            self._json(STORE.mail_draft_save(
                int(body.get("id", 0) or 0), _mail_acct_id(), body.get("to") or "",
                body.get("subject") or "", body.get("body") or ""))
            return

        if p == "/api/mail/draft/del":
            self._json(STORE.mail_draft_del(int(body.get("id", 0) or 0)))
            return

        if p == "/api/mail/schedule":
            self._json(_mail_send_queued(body))
            return

        if p == "/api/mail/outbox/cancel":
            self._json(STORE.mail_outbox_cancel(int(body.get("id", 0) or 0)))
            return

        if p == "/api/mail/outbox/run":
            n = _mail_tick()
            self._json({"ok": True, "processed": n,
                        "rows": STORE.mail_outbox_list(50),
                        "pending": STORE.mail_outbox_pending()})
            return

        if p == "/api/docs/make":
            self._doc_make(body)
            return

        # ---------- F 域：文档工作台写操作 ----------
        if p == "/api/docs/save":
            self._json(STORE.docs_save(
                int(body.get("id", 0) or 0), body.get("title", ""), body.get("md", ""),
                body.get("note", ""), bool(body.get("snap", True))))
            return

        if p == "/api/docs/del":
            self._json(STORE.docs_del(int(body.get("id", 0) or 0)))
            return

        if p == "/api/docs/fav":
            self._json(STORE.docs_fav(int(body.get("id", 0) or 0), body.get("on")))
            return

        if p == "/api/docs/restore":
            self._json(STORE.docs_restore(int(body.get("id", 0) or 0),
                                          int(body.get("sid", 0) or 0)))
            return

        if p == "/api/docs/batch":
            self._json(self._docs_batch(body))
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
            parts = body.get("ctx_parts")
            ctx = ""
            if body.get("ctx", True):
                try:
                    ctx = self._openclaw_context(parts if isinstance(parts, list) else None)
                except Exception:
                    ctx = ""
            agent = (body.get("agent") or "").strip()
            model = (body.get("model") or "").strip()
            t0 = time.time()
            r = _claw_run_with_retry(task, ctx, int(body.get("timeout", 240)), agent, model)
            dur = time.time() - t0
            # 运行记录写回工作台（统一活动），不依赖 OpenClaw 是否成功
            try:
                STORE.openclaw_log(
                    task, (r.get("reply") or r.get("error") or "")[:4000],
                    bool(r.get("ok")), "run", agent, dur, 0,
                )
            except Exception:
                pass
            r["dur"] = round(dur, 1)
            self._json(r)
            return

        if p == "/api/openclaw/queue":
            task = (body.get("task") or "").strip()
            if not task:
                self._json({"ok": False, "error": "空任务"})
                return
            parts = body.get("ctx_parts")
            ctx = ""
            if body.get("ctx", True):
                try:
                    ctx = self._openclaw_context(parts if isinstance(parts, list) else None)
                except Exception:
                    ctx = ""
            self._json(_q_add(task, ctx, (body.get("agent") or "").strip(),
                              int(body.get("timeout", 240) or 240),
                              parts if isinstance(parts, list) else None))
            return

        if p == "/api/openclaw/queue/clear":
            self._json(_q_clear())
            return

        if p == "/api/openclaw/fav":
            self._json(STORE.openclaw_fav(int(body.get("id", 0) or 0),
                                          body.get("on")))
            return

        if p == "/api/openclaw/rerun":
            oid = int(body.get("id", 0) or 0)
            row = STORE.openclaw_get(oid)
            if not row:
                self._json({"ok": False, "error": "没这条记录"})
                return
            task = (row.get("task") or "").strip()
            parts = body.get("ctx_parts")
            ctx = ""
            if body.get("ctx", True):
                try:
                    ctx = self._openclaw_context(parts if isinstance(parts, list) else None)
                except Exception:
                    ctx = ""
            agent = (body.get("agent") or row.get("agent") or "").strip()
            t0 = time.time()
            r = _claw_run_with_retry(task, ctx, int(body.get("timeout", 240)), agent)
            dur = time.time() - t0
            try:
                STORE.openclaw_log(task, (r.get("reply") or r.get("error") or "")[:4000],
                                   bool(r.get("ok")), "rerun", agent, dur, 0)
            except Exception:
                pass
            r["dur"] = round(dur, 1)
            r["task"] = task
            self._json(r)
            return

        # ---- OpenClaw 神经桥：写操作先入待审队列，用户确认后才执行 ----
        if p == "/api/skills/install":
            name = (body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "没指定技能名"})
                return
            r = integrations.openclaw_skill_install(name)
            if r.get("ok"):
                # 装上了就算用过一次（118）
                STORE.skill_use("claw|" + name, name, "OpenClaw", 1)
                STORE.log_add("ok", f"装了 OpenClaw 技能「{name}」", "skills")
            self._json(r)
            return

        # ---- M 域：技能库（115-120）----
        if p == "/api/skills/fav":                     # 115 收藏钉顶
            self._json(STORE.skill_fav_toggle(body.get("key", ""), body.get("on")))
            return
        if p == "/api/skills/use":                     # 118 记一次使用
            r = STORE.skill_use(body.get("key", ""), body.get("name", ""),
                                body.get("src", ""), body.get("ok", 1))
            if r.get("ok"):
                STORE.log_add("info", f"用了一次技能「{body.get('name') or body.get('key')}」", "skills")
            self._json(r)
            return
        if p == "/api/skills/dir/add":                 # 117 注册自定义技能目录
            r = STORE.skill_dir_add(body.get("path", ""), body.get("label", ""))
            if r.get("ok"):
                STORE.log_add("info", f"注册自定义技能目录：{body.get('path')}", "skills")
            self._json(r)
            return
        if p == "/api/skills/dir/del":
            self._json(STORE.skill_dir_del(int(body.get("id", 0) or 0)))
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
                try:
                    STORE.bridge_audit_add(action, json.dumps(payload, ensure_ascii=False),
                                           _bridge_summary(action, payload),
                                           "submitted", body.get("actor", "openclaw"),
                                           "待确认 #%s" % pid)
                except Exception:
                    pass
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
                try:
                    STORE.bridge_audit_add(row["action"], row.get("payload") or "",
                                           _bridge_summary(row["action"], pl),
                                           "confirmed" if res.get("ok") else "confirmed_failed",
                                           "user", str(res.get("error") or "ok"))
                except Exception:
                    pass
                self._json({"ok": True, "result": res})
                return
            if p == "/api/bridge/reject":
                rid = int(body.get("id", 0) or 0)
                row = STORE.bridge_get(rid) or {}
                STORE.bridge_resolve(rid, "rejected", "用户拒绝")
                try:
                    pl = json.loads(row.get("payload") or "{}")
                except Exception:
                    pl = {}
                try:
                    STORE.bridge_audit_add(row.get("action") or "", row.get("payload") or "",
                                           _bridge_summary(row.get("action") or "", pl),
                                           "rejected", "user", "用户拒绝")
                except Exception:
                    pass
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": "未知桥端点"}, 404)
            return

        if p == "/api/projects/save":
            self._json(STORE.project_save(
                body.get("id") or None, body.get("name", ""),
                body.get("status", ""), body.get("next_step", ""),
                body.get("deadline", "") or "", body.get("color", "") or "",
                body.get("template", "") or "",
            ))
            return

        if p == "/api/projects/del":
            self._json(STORE.project_del(int(body.get("id", 0))))
            return

        if p == "/api/projects/archive":
            self._json(STORE.project_archive(int(body.get("id", 0)),
                                             int(body.get("on", 1) or 0)))
            return

        if p == "/api/projects/template/apply":
            self._json(STORE.apply_template(int(body.get("project_id", 0)),
                                            body.get("template", "")))
            return

        if p == "/api/milestones/save":
            self._json(STORE.milestone_save(
                body.get("id") or None, int(body.get("project_id", 0) or 0),
                body.get("title", ""), body.get("day", "") or "",
                body.get("pct", 0) or 0,
            ))
            return

        if p == "/api/milestones/done":
            self._json(STORE.milestone_done(int(body.get("id", 0)),
                                            int(body.get("done", 1) or 0),
                                            int(body.get("pct", -1) or -1)))
            return

        if p == "/api/milestones/del":
            self._json(STORE.milestone_del(int(body.get("id", 0))))
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
                int(body.get("today_id", 0) or 0),
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
                (body.get("status") or "").strip(),
                body.get("fav"),
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

        if p == "/api/kb/status":                     # 89 阅读状态
            self._json(STORE.kb_status(
                int(body.get("id", 0)), (body.get("status") or "").strip()))
            return

        if p == "/api/kb/summary":                    # 90 摘要卡
            self._json(STORE.kb_set_summary(
                int(body.get("id", 0)), body.get("summary", "")))
            return

        if p == "/api/kb/tags":                       # 91 批量改标签
            self._json(STORE.kb_tags_bulk(
                [int(x) for x in (body.get("ids") or [])],
                (body.get("op") or "add").strip(),
                (body.get("tag") or "").strip()))
            return

        if p == "/api/kb/fav":                        # 94 收藏
            self._json(STORE.kb_fav(
                int(body.get("id", 0)),
                0 if body.get("on") in (0, False, "0") else 1))
            return

        if p == "/api/kb/reindex":                    # 87 老数据补建索引
            self._json(STORE.kb_reindex_all())
            return

        if p == "/api/chats/save":
            self._json(STORE.chat_save(
                body.get("title", ""), body.get("model", ""), body.get("messages", []),
                body.get("id") or None, body.get("sys", ""),
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

        if p == "/api/wecom/save":
            c = wecom_cfg()
            for k in ("enabled", "corpid", "secret", "agentid", "touser", "token",
                      "aes_key", "msgtype", "callback_url"):
                if k in body:
                    c[k] = body[k]
            if (c.get("callback_url") or "").strip():
                c["callback_url"] = c["callback_url"].strip().rstrip("/")
            save_config(CFG)
            self._json({"ok": True, "callback_url": _wecom_callback_url()})
            return

        if p == "/api/wecom/genkey":
            # Token / EncodingAESKey 必须由客户端随机生成（官方要求），
            # 但手搓一串 43 位 base64 太反人类，这里代劳。
            tok = wecommod.random_nonce() + wecommod.random_nonce()[:6]
            key = wecommod.random_aes_key()
            self._json({"ok": True, "token": tok, "aes_key": key})
            return

        if p == "/api/wecom/selfcheck":
            self._json(integrations.wecom_selfcheck(dict(wecom_cfg())))
            return

        if p == "/api/wecom/ingest":
            self._json(wecom_ingest(body or {}))
            return

        if p == "/api/wecom/tunnel/start":
            self._json(tunnel_start(int(body.get("port") or 0)))
            return

        if p == "/api/wecom/tunnel/stop":
            self._json(tunnel_stop())
            return

        if p == "/api/connectors/push":
            cid = body.get("id")
            cons = CFG.get("connectors") or []
            c = next((x for x in cons if x.get("id") == cid), None)
            if not c:
                self._json({"ok": False, "error": "找不到这个连接器（去设置里添加一个）"})
                return
            if not c.get("enabled", True):
                self._json({"ok": False, "error": "这个连接器已被停用（去设置里开启）"})
                return
            r = integrations.connector_push(c, body.get("title", "工作台"), body.get("content", ""))
            # 每次推送留痕：成功失败都可查（测试推送也记，方便排错）
            try:
                STORE.connector_push_log(
                    (c.get("type") or ""), (c.get("name") or c.get("id") or ""),
                    body.get("title", "工作台"), bool(r.get("ok")), r.get("error") or r.get("msg") or "")
            except Exception:  # noqa: BLE001
                pass
            self._json(r)
            return

        if p == "/api/connectors/log":
            self._json({"rows": STORE.connector_push_recent(50)})
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
                    STORE.open_log(target)   # 「打开」也进最近使用
                self._json({"ok": True})
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)})
            return

        if p == "/api/files/fav":
            self._json(STORE.fav_toggle(body.get("path", "")))
            return

        if p == "/api/files/rename/plan":
            self._json(self._rename_plan(
                body.get("paths") or [], body.get("rule") or {}))
            return

        if p == "/api/files/rename/go":
            self._json(self._rename_go(body.get("items") or []))
            return

        if p == "/api/files/ft/toggle":
            on = bool(body.get("on", True))
            IDX.ft_set(on)
            self._json({"ok": True, **IDX.ft_stats()})
            return

        if p == "/api/files/ft/build":
            self._json(IDX.ft_build(int(body.get("limit", 2000) or 2000)))
            return

        if p == "/api/files/ft/clear":
            IDX.ft_clear()
            self._json({"ok": True, **IDX.ft_stats()})
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

        if ext == "pdf":
            # PDF 直接在台内嵌浏览器自己的阅读器看，不用跳出去
            self._json({
                "kind": "pdf",
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
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = self.IMG_EXT.get(ext)
        if not mime:
            if ext == "pdf":
                mime = "application/pdf"       # 内联显示，别触发下载
            elif ext in ("mp4", "webm"):
                mime = "video/" + ("mp4" if ext == "mp4" else "webm")
            elif ext in ("mp3", "wav", "ogg", "m4a"):
                mime = "audio/" + ("mpeg" if ext == "mp3" else ext)
            else:
                mime = "application/octet-stream"
        try:
            with open(path, "rb") as f:
                data = f.read(24 << 20)
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", "inline")
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

    # ---------- 邮件：多账号保存（63） ----------

    def _mail_account_save(self, body: dict):
        """新增或改一个邮箱账号。password 留空 = 不动原有授权码。"""
        accs = list(CFG.get("mail_accounts") or [])
        aid = str(body.get("id") or "").strip()
        user = (body.get("user") or "").strip()
        if not user:
            self._json({"ok": False, "error": "邮箱地址没填"})
            return
        rec = next((x for x in accs if str(x.get("id")) == aid), None)
        fields = {
            "name": (body.get("name") or user).strip(),
            "user": user,
            "imap_host": (body.get("imap_host") or "").strip(),
            "imap_port": str(body.get("imap_port") or "993").strip(),
            "smtp_host": (body.get("smtp_host") or "").strip(),
            "smtp_port": str(body.get("smtp_port") or "465").strip(),
            "smtp_tls": (body.get("smtp_tls") or "").strip(),
        }
        if rec is None:
            rec = {"id": aid or str(int(time.time() * 1000))}
            accs.append(rec)
        rec.update(fields)
        pw = body.get("password")
        if pw:
            rec["password"] = pw
        CFG["mail_accounts"] = accs
        if not _mail_acct_id():            # 第一个存进来的自动顶上
            CFG["mail_active"] = str(rec["id"])
        save_config(CFG)
        if _mail_acct_id() == str(rec["id"]):
            _mail_apply_active(str(rec["id"]))
        self._json({"ok": True, "id": rec["id"], "rows": _mail_accounts_public(),
                    "active": _mail_acct_id(), "password_set": bool(rec.get("password"))})

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

    def _docs_batch(self, body: dict) -> dict:
        """多选文档批量转 docx/pptx（61）。一份一份写，最后把成败清单带回去。"""
        ids = body.get("ids") or []
        kind = (body.get("kind") or "word").strip() or "word"
        if not isinstance(ids, list) or not ids:
            return {"ok": False, "error": "没选文档"}
        made, failed = [], []
        for i in ids[:80]:
            row = STORE.docs_get(int(i or 0))
            if not row:
                failed.append({"id": int(i or 0), "title": "", "error": "找不到这篇"})
                continue
            title = row.get("title") or "文档"
            md = row.get("md") or ""
            if not md.strip():
                failed.append({"id": row["id"], "title": title, "error": "正文是空的"})
                continue
            try:
                name = docswrite.safe_name(title, kind)
                r = docswrite.write_any(os.path.join(EXPORTS, name), kind, md, title)
            except Exception as e:  # noqa: BLE001
                failed.append({"id": row["id"], "title": title,
                               "error": f"{type(e).__name__}: {e}"})
                continue
            if r.get("ok"):
                made.append({"id": row["id"], "title": title,
                             "file": os.path.basename(r.get("path") or name),
                             "url": f"/api/download/{os.path.basename(r.get('path') or name)}",
                             "note": r.get("note", "")})
            else:
                failed.append({"id": row["id"], "title": title,
                               "error": r.get("error") or "转换失败"})
        return {"ok": True, "made": made, "failed": failed,
                "n": len(made), "nfail": len(failed)}

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
        """一次性问答：从本地知识库召回相关条目当上下文，交给模型答。
        也可以直接指定 id/ids，只拿这几条当上下文（摘要卡就走这条路）。"""
        q = (body.get("q") or "").strip()
        if not q:
            self._json({"ok": False, "error": "还没写问题"})
            return
        rows = STORE.kb_list()
        if not rows:
            self._json({"ok": False, "error": "知识库还是空的，先去「知识」页加几条或导入文件"})
            return
        want = set()
        for x in (body.get("ids") or []):
            try:
                want.add(int(x))
            except (TypeError, ValueError):
                pass
        try:
            if body.get("id"):
                want.add(int(body["id"]))
        except (TypeError, ValueError):
            pass
        if want:
            ctx = [r for r in rows if int(r.get("id") or 0) in want]
            if not ctx:
                self._json({"ok": False, "error": "指定的资料没找到"})
                return
        else:
            ctx = (STORE.kb_search(q, 6).get("rows") or []) or _kb_retrieve(q, rows)
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
    global SERVER_PORT
    port = 8777
    host = (CFG.get("remote") or {}).get("bind") or "127.0.0.1"
    argv = sys.argv[1:]
    if argv and argv[0].isdigit():
        port = int(argv[0])
    if "--host" in argv:
        host = argv[argv.index("--host") + 1]
    SERVER_PORT = port
    srv = ThreadingHTTPServer((host, port), Handler)
    # 69 定时发送的看门人在后台，到点就把排队的邮件发出去
    threading.Thread(target=_mail_loop, daemon=True).start()
    # 企业微信：出口 IP 变了要提醒（家宽动态 IP 一变，发消息就报 60020）
    if wecom_cfg().get("enabled"):
        threading.Thread(target=_wecom_egress_watch, daemon=True).start()
    # 114 启动留痕，日志页一眼能看到这次是几点起的
    try:
        STORE.log_add("info", f"工作台已启动：http://{host}:{port}", "server")
    except Exception:  # noqa: BLE001
        pass
    print(f"工作台已启动： http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
