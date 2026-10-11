# -*- coding: utf-8 -*-
"""OpenWorkbench MCP Server —— 把工作台变成 OpenClaw 的**真工具**。

## 为什么需要这个

以前「让 OpenClaw 用工作台」只是在任务里拼一段提示词（_NEURO_MANUAL），
告诉它"你可以 POST http://127.0.0.1:8777/api/bridge/submit"。
那本质是**教它怎么用手**，它得自己记住 URL、自己拼 JSON、自己判断该调哪个。
漏一个字段就是 400，它也不知道。

这里做的是**底层适配**：把这些能力注册成标准 MCP 工具。OpenClaw 侧
`openclaw mcp add` 挂上之后，它在会话里看到的是一排带参数说明的工具，
该调哪个、按什么结构传、返回什么意思，全由 schema 说了算，不靠它记。

## 为什么零第三方依赖

MCP over stdio 就是「一行一个 JSON-RPC 消息，Content-Length 分帧或换行分隔」。
标准库足够。装依赖会破坏 "clone 就能跑" 这条铁律。

## 传输：stdio（不是 HTTP）

OpenClaw 用 `command` + `args` 拉起本进程，通过 stdin/stdout 对话。
⚠️ **任何 print / 调试输出都会污染协议流**，必须写 stderr。
本文件里唯一允许写 stdout 的地方是协议帧本身。

## 工具清单（分组）

邮件    mail_list / mail_read / mail_search / mail_unread_count
工作台  today_list / today_add / today_toggle / today_del
        kb_save / kb_search / inbox_add / note_save
        calendar_add / project_save
诊断    wb_status / wb_diagnostics

刻意**不提供**删除类动作的"批量"版本，也**不提供**任意 HTTP 转发 ——
让 agent 能"删整个知识库"或"往任意 URL POST"不是我们要的能力。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("WB_BASE", "http://127.0.0.1:8777").rstrip("/")
TIMEOUT = int(os.environ.get("WB_TIMEOUT", "60"))

PROTO = "2024-11-05"
SERVER_INFO = {"name": "openworkbench", "version": "2.1.0"}


# ---------------------------------------------------------------- 传输层

def _log(msg):
    """调试信息一律走 stderr —— stdout 是协议流，碰不得。"""
    try:
        sys.stderr.write("[wb-mcp] %s\n" % msg)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _send(obj):
    """MCP stdio 帧：一行一个 JSON（newline-delimited JSON，不是 Content-Length）。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read():
    """读一行 JSON。stdin 关了就返回 None 让主循环退出。"""
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return {}
    try:
        return json.loads(line)
    except Exception as e:  # noqa: BLE001
        _log("bad json: %s" % e)
        return {}


# ---------------------------------------------------------------- 工作台调用

def _get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return _call("GET", url, None)


def _post(path, payload=None):
    return _call("POST", BASE + path, payload or {})


def _call(method, url, payload):
    # 必须绕开环境代理，否则来源被归一成别的地址，局域网门禁会误判
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with op.open(req, timeout=TIMEOUT) as r:
            return _decode(r.read(), r.status)
    except urllib.error.HTTPError as e:
        return _decode(e.read(), e.code)
    except Exception as e:  # noqa: BLE001
        # 服务没起是**常态**（工作台可能没开），必须给 agent 一句能行动的中文，
        # 而不是把 traceback 甩给它让它瞎猜
        return {"ok": False,
                "error": "连不上工作台 %s（%s）。请先双击 workbench/start.bat 启动。"
                         % (BASE, type(e).__name__)}


def _decode(raw, code):
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {"ok": code == 200, "http": code,
                "error": raw.decode("utf-8", "replace")[:400]}
    if isinstance(d, dict):
        d.setdefault("ok", code == 200)
        d.setdefault("http", code)
    return d


def _clip(v, n):
    """所有回给模型的文本都截断 —— 邮件正文动辄几万字，
    全塞进上下文会把 agent 的窗口吃光，反而看不到重点。"""
    v = "" if v is None else str(v)
    return v if len(v) <= n else v[:n] + "\n...[已截断，原文 %d 字]" % len(v)


# ---------------------------------------------------------------- 工具实现

def t_mail_list(limit=20, unseen_only=False, query=""):
    r = _get("/api/mail/list", {"limit": limit,
                               "unseen": "1" if unseen_only else "0",
                               "q": query})
    rows = []
    for x in (r.get("rows") or [])[:50]:
        rows.append({"uid": x.get("uid"), "from": x.get("from"),
                     "subject": x.get("subject"), "date": x.get("date"),
                     "tags": x.get("tags") or "", "starred": bool(x.get("starred")),
                     "snippet": _clip(x.get("snippet") or x.get("preview") or "", 160)})
    return {"ok": r.get("ok"), "count": len(rows), "emails": rows,
            "error": r.get("error") or ""}


def t_mail_read(uid, mark_seen=True):
    if not uid:
        return {"ok": False, "error": "必须给 uid"}
    r = _get("/api/mail/read", {"uid": uid, "mark": "1" if mark_seen else "0"})
    if not r.get("ok"):
        return r
    return {"ok": True, "uid": r.get("uid"), "from": r.get("from"),
            "to": r.get("to"), "subject": r.get("subject"), "date": r.get("date"),
            "tags": r.get("tags") or "", "body": _clip(r.get("body") or "", 8000)}


def t_mail_search(query, limit=20):
    if not query:
        return {"ok": False, "error": "必须给 query"}
    r = _get("/api/mail/search", {"q": query, "limit": limit})
    rows = []
    for x in (r.get("rows") or [])[:50]:
        rows.append({"uid": x.get("uid"), "from": x.get("from"),
                     "subject": x.get("subject"), "date": x.get("date"),
                     "hit": _clip(x.get("snippet") or x.get("hit") or "", 160)})
    return {"ok": r.get("ok"), "count": len(rows), "hits": rows,
            "error": r.get("error") or ""}


def t_mail_unread_count():
    r = _get("/api/mail/unread")
    return {"ok": r.get("ok"), "unread": r.get("unread", r.get("count", 0)),
            "error": r.get("error") or ""}


def t_mail_diag():
    r = _get("/api/mail/diag")
    return {"ok": r.get("ok"), "diag": r}


def _bridge(action, payload):
    """走工作台的待审队列。**所有写操作都必须过这里** —— 用户点确认才真执行。
    直接调 /api/today/add 之类的接口会绕过确认，那就不是自动化而是失控。"""
    r = _post("/api/bridge/submit", {"action": action, "payload": payload})
    return {"ok": r.get("ok"), "action": action, "queued": r.get("queued", r.get("id")),
            "message": r.get("message") or r.get("error") or "",
            "hint": "已提交待审队列，请让用户在 OpenClaw 页点「确认」" if r.get("ok") else ""}


def t_today_list(day=""):
    r = _get("/api/today", {"day": day} if day else None)
    items = []
    for x in (r.get("rows") or r.get("items") or []):
        items.append({"id": x.get("id"), "text": x.get("text"),
                      "done": bool(x.get("done")), "project_id": x.get("project_id")})
    return {"ok": r.get("ok"), "day": r.get("day") or day, "items": items,
            "error": r.get("error") or ""}


def t_today_add(text, day="", project_id=0):
    if not text:
        return {"ok": False, "error": "必须给 text"}
    return _bridge("today/add", {"text": text, "day": day, "project_id": project_id})


def t_today_toggle(item_id, done=True):
    try:
        i = int(item_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "item_id 必须是数字"}
    return _bridge("today/toggle", {"id": i, "done": 1 if done else 0})


def t_today_del(item_id):
    try:
        i = int(item_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "item_id 必须是数字"}
    return _bridge("today/del", {"id": i})


def t_inbox_add(text):
    if not text:
        return {"ok": False, "error": "必须给 text"}
    return _bridge("inbox/add", {"text": text})


def t_kb_save(title, body="", tags=""):
    if not title:
        return {"ok": False, "error": "必须给 title"}
    return _bridge("kb/save", {"title": title, "body": body, "tags": tags})


def t_kb_search(query, limit=10):
    r = _get("/api/kb", {"q": query, "limit": limit} if query else {"limit": limit})
    rows = []
    for x in (r.get("rows") or [])[:30]:
        rows.append({"id": x.get("id"), "title": x.get("title"),
                     "tags": x.get("tags") or "", "snippet": _clip(x.get("body") or "", 200)})
    return {"ok": r.get("ok"), "hits": rows, "error": r.get("error") or ""}


def t_note_save(title, body="", project=0):
    if not title:
        return {"ok": False, "error": "必须给 title"}
    return _bridge("projects/save" if project else "kb/save",
                   {"title": title, "body": body} if not project
                   else {"name": title, "status": "进行中"})


def t_calendar_add(day, title, start="", end="", note=""):
    if not day or not title:
        return {"ok": False, "error": "必须给 day 和 title"}
    return _bridge("cal/add", {"day": day, "title": title,
                               "start": start, "end": end, "note": note})


def t_project_save(name, status="进行中", next_step=""):
    if not name:
        return {"ok": False, "error": "必须给 name"}
    return _bridge("projects/save", {"name": name, "status": status, "next_step": next_step})


def t_wb_status():
    r = _get("/api/status")
    return {"ok": r.get("ok"), "files": r.get("count"), "counts": r.get("counts") or {},
            "claude": bool(r.get("claw")) if isinstance(r.get("claw"), (bool, int)) else None}


def t_wb_diagnostics():
    """一次看全：服务通不通、邮件配没配、连接器状态、打印设备。
    agent 报"工作台有问题"时先调它，别自己猜。"""
    out = {"mail": {}, "printers": [], "connectors": [], "ok": True}
    st = _get("/api/status")
    out["workbench_ok"] = bool(st.get("ok"))
    out["files"] = st.get("count")
    d = _get("/api/mail/diag")
    out["mail"] = {"ok": d.get("ok"), "detail": d if not d.get("ok") else
                   {"user": d.get("user"), "host": d.get("host")}}
    pv = _get("/api/print/devices")
    out["printers"] = [{"name": x.get("name"), "kind": x.get("kind")}
                       for x in (pv.get("devices") or [])]
    cn = _get("/api/connectors")
    out["connectors"] = [{"name": x.get("name"), "type": x.get("type"),
                          "enabled": bool(x.get("enabled"))}
                         for x in (cn.get("connectors") or [])]
    return out


# ---------------------------------------------------------------- 工具声明

def _t(name, desc, props=None, required=None):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object",
                            "properties": props or {}, "required": required or []}}


_S = lambda d: {"type": "string", "description": d}   # noqa: E731
_I = lambda d: {"type": "integer", "description": d}  # noqa: E731
_B = lambda d: {"type": "boolean", "description": d}  # noqa: E731

TOOLS = [
    # ---- 邮件 ----
    _t("mail_list", "列出邮箱里的邮件。用于「看看最近有什么信」「有哪些未读」。"
       "返回精简字段（uid/发件人/主题/日期/标签/摘要片段），不返回正文。",
       {"limit": _I("最多取几封，默认 20，上限 50"),
        "unseen_only": _B("只看未读，默认 false"),
        "query": _S("按关键词过滤（发件人/主题/正文）")}),
    _t("mail_read", "读某一封邮件的完整正文。先用 mail_list 拿到 uid。",
       {"uid": _S("邮件 uid，来自 mail_list"), "mark_seen": _B("是否标记已读，默认 true")},
       ["uid"]),
    _t("mail_search", "在邮件里搜关键词（搜本机已缓存的正文，离线也能搜）。",
       {"query": _S("要搜的词"), "limit": _I("最多返回几条")}, ["query"]),
    _t("mail_unread_count", "未读邮件数量。用于「我现在有多少封未读」。"),
    _t("mail_diagnose", "邮件通道自检：账号、服务器、能不能连上。"
       "发信/收信失败时先调它，别瞎猜原因。"),
    # ---- 工作台写入（全部过待审队列）----
    _t("today_add", "往「今日」加一条待办。会进入待审队列，用户确认后才真正写入。",
       {"text": _S("待办内容"), "day": _S("日期 YYYY-MM-DD，留空=今天"),
        "project_id": _I("归属项目 id，0=不归属")}, ["text"]),
    _t("today_list", "看「今日」的待办清单。"),
    _t("today_toggle", "勾掉或取消勾掉一条待办（需要 id，来自 today_list）。",
       {"item_id": _I("待办 id"), "done": _B("true=完成")}, ["item_id"]),
    _t("today_del", "删掉一条待办（需要 id）。会进待审队列。", {"item_id": _I("待办 id")},
       ["item_id"]),
    _t("inbox_add", "往「随手记」丢一条。等价于快速捕捉，不需要再整理。",
       {"text": _S("内容")}, ["text"]),
    _t("kb_save", "存一条资料到知识库。用于「把这个存起来」「归档这份内容」。",
       {"title": _S("标题"), "body": _S("正文"), "tags": _S("逗号分隔的标签")},
       ["title"]),
    _t("kb_search", "搜知识库。回答问题前先搜一下，别凭空编。",
       {"query": _S("关键词，留空=列出最近"), "limit": _I("条数")}),
    _t("calendar_add", "加一条日程。",
       {"day": _S("日期 YYYY-MM-DD"), "title": _S("标题"),
        "start": _S("开始 HH:MM"), "end": _S("结束 HH:MM"), "note": _S("备注")},
       ["day", "title"]),
    _t("project_save", "新建或更新一个项目。",
       {"name": _S("项目名"), "status": _S("状态，如 进行中/已完成"),
        "next_step": _S("下一步")}, ["name"]),
    # ---- 诊断 ----
    _t("wb_status", "工作台整体状态：索引了多少文件、各模块有多少条数据。"),
    _t("wb_diagnostics", "一次性体检：工作台通不通、邮件配没配、有哪些打印机和连接器。"
       "任何操作失败时先调它。"),
]

BY_NAME = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------- 分发

def _call_tool(name, args):
    fn = {
        "mail_list": t_mail_list, "mail_read": t_mail_read,
        "mail_search": t_mail_search, "mail_unread_count": t_mail_unread_count,
        "mail_diag": t_mail_diag,
        "today_list": t_today_list, "today_add": t_today_add,
        "today_toggle": t_today_toggle, "today_del": t_today_del,
        "inbox_add": t_inbox_add, "kb_save": t_kb_save, "kb_search": t_kb_search,
        "calendar_add": t_calendar_add, "project_save": t_project_save,
        "wb_status": t_wb_status, "wb_diagnostics": t_wb_diagnostics,
    }.get(name)
    if not fn:
        return {"ok": False, "error": "没有这个工具：%s" % name}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {"ok": False, "error": "参数不对：%s" % e,
                "hint": "参数名必须和 schema 完全一致（区分大小写）"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    # 通知（无 id）不回结果
    is_note = "id" not in msg

    if method == "initialize":
        out = {"protocolVersion": PROTO, "capabilities": {"tools": {}},
               "serverInfo": SERVER_INFO}
    elif method in ("notifications/initialized", "initialized"):
        return
    elif method == "ping":
        out = {}
    elif method == "tools/list":
        out = {"tools": TOOLS}
    elif method == "tools/call":
        res = _call_tool(params.get("name"), params.get("arguments"))
        out = {"content": [{"type": "text",
                            "text": json.dumps(res, ensure_ascii=False, indent=1)}],
               "isError": not res.get("ok", True)}
    elif method in ("resources/list", "prompts/list"):
        out = {"resources": []} if method.startswith("res") else {"prompts": []}
    else:
        if is_note:
            return
        _send({"jsonrpc": "2.0", "id": mid,
               "error": {"code": -32601, "message": "no such method: %s" % method}})
        return

    if is_note:
        return
    _send({"jsonrpc": "2.0", "id": mid, "result": out})


def main():
    _log("start base=%s tools=%d" % (BASE, len(TOOLS)))
    while True:
        try:
            msg = _read()
        except KeyboardInterrupt:
            break
        if msg is None:
            break
        if not msg:
            continue
        try:
            handle(msg)
        except Exception as e:  # noqa: BLE001
            _log("handler crash: %r" % e)
            if "id" in msg:
                _send({"jsonrpc": "2.0", "id": msg["id"],
                       "error": {"code": -32603, "message": str(e)}})


def selftest():
    """自检：协议握手 + 工具清单 + 一个真实工具调用（服务没起也不该崩）。"""
    ok = 0
    bad = 0

    def ck(name, cond, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s  <<< %s" % (name, extra))

    ck("协议版本常量", PROTO == "2024-11-05", PROTO)
    ck("serverInfo 有 name/version",
       bool(SERVER_INFO.get("name")) and bool(SERVER_INFO.get("version")))
    ck("工具数量 >= 16", len(TOOLS) >= 16, str(len(TOOLS)))
    names = [t["name"] for t in TOOLS]
    ck("工具名不重复", len(names) == len(set(names)),
       str([n for n in names if names.count(n) > 1]))
    ck("每个工具有 description",
       all(t.get("description") for t in TOOLS),
       str([t["name"] for t in TOOLS if not t.get("description")]))
    ck("每个工具有 inputSchema.type=object",
       all(t["inputSchema"].get("type") == "object" for t in TOOLS))
    ck("required 里的字段都在 properties 里",
       all(all(r in t["inputSchema"]["properties"] for r in t["inputSchema"]["required"])
           for t in TOOLS),
       str([(t["name"], r) for t in TOOLS
            for r in t["inputSchema"]["required"]
            if r not in t["inputSchema"]["properties"]]))
    ck("有邮件类工具", sum(1 for n in names if n.startswith("mail_")) >= 5)
    ck("有工作台写入类工具", sum(1 for n in names if n.startswith("today_")) >= 3)
    ck("有诊断工具", "wb_diagnostics" in names and "wb_status" in names)
    ck("**刻意不提供**任意 HTTP 转发工具",
       not any(("proxy" in n or "fetch" in n or "request" in n) for n in names))
    ck("**刻意不提供**直接发信工具（发信要走人工确认）",
       not any(n in ("mail_send", "mail_compose", "send_mail") for n in names))

    # 分发层
    m = {}
    orig = globals()["_send"]
    globals()["_send"] = lambda o: m.update(o)
    try:
        handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        ck("initialize 返回 protocolVersion",
           m.get("result", {}).get("protocolVersion") == PROTO, str(m)[:160])
        m.clear()
        handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        ck("tools/list 返回全部工具",
           len(m.get("result", {}).get("tools", [])) == len(TOOLS))
        m.clear()
        handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "mail_read", "arguments": {}}})
        txt = (m.get("result", {}).get("content") or [{}])[0].get("text", "")
        ck("缺必填参数时给中文错误而不是崩",
           "uid" in txt and '"ok": false' in txt.replace("False", "false"), txt[:200])
        m.clear()
        handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "不存在的工具", "arguments": {}}})
        ck("未知工具返回错误而不是崩",
           "isError" in m.get("result", {}), str(m)[:160])
        m.clear()
        handle({"jsonrpc": "2.0", "id": 5, "method": "没有这个方法"})
        ck("未知方法回 JSON-RPC error",
           m.get("error", {}).get("code") == -32601, str(m)[:160])
        m.clear()
        handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        ck("通知（无 id）不回复", m == {}, str(m)[:120])
    finally:
        globals()["_send"] = orig

    # 真实调用。服务可能起着也可能没起（自检不该依赖工作台在跑），
    # 所以两种结局都算过：**关键是不能抛异常、且失败时给出可行动的中文**。
    r = _call_tool("wb_status", {})
    if r.get("ok"):
        ck("服务在跑时 wb_status 拿到真实数据", "files" in r, str(r)[:160])
    else:
        ck("服务不可用时返回可行动的中文提示（不抛异常）",
           isinstance(r, dict) and "error" in r and "start.bat" in str(r.get("error")),
           str(r)[:200])
    r2 = _call_tool("mail_list", {"limit": 3})
    ck("mail_list 在任何情况下都返回 dict",
       isinstance(r2, dict) and ("emails" in r2 or "error" in r2), str(r2)[:160])
    # 参数类型错误必须给中文提示，不能漏 traceback 给 agent 看
    r3 = _call_tool("today_toggle", {"item_id": "不是数字"})
    ck("参数类型不对时给中文提示（而不是 Python 的 TypeError）",
       r3.get("ok") is False and "error" in r3, str(r3)[:160])
    r4 = _call_tool("today_add", {})
    ck("缺必填参数时给中文提示",
       r4.get("ok") is False and "text" in str(r4.get("error")), str(r4)[:160])

    print("\n=== MCP 服务器自检：%d PASS / %d FAIL ===" % (ok, bad))
    print("SMOKE_OK" if not bad else "SMOKE_FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
