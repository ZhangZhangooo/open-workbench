"""外部集成：WPS 打开文档、OpenClaw 跑任务、LLM 一次性补全。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

NODE = r"C:\Program Files\nodejs\node.exe"


def _openclaw_mjs() -> str:
    """定位 openclaw 的 .mjs 入口（Windows npm 装法：node + openclaw.mjs）。

    不同机器 npm 前缀不一样：默认 %APPDATA%\\npm、自定义 ~/.npm-global、
    brew 的 /usr/local|/opt/homebrew。挨个试，找到即返回；都找不到返回默认 Windows 路径兜底。
    """
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    candidates = []
    if appdata:
        candidates.append(os.path.join(appdata, "npm", "node_modules", "openclaw", "openclaw.mjs"))
    candidates += [
        os.path.join(home, ".npm-global", "lib", "node_modules", "openclaw", "openclaw.mjs"),
        "/usr/local/lib/node_modules/openclaw/openclaw.mjs",
        "/opt/homebrew/lib/node_modules/openclaw/openclaw.mjs",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    # 兜底：原 Windows 默认路径（即便不存在也返回，保持旧行为）
    if appdata:
        return os.path.join(appdata, "npm", "node_modules", "openclaw", "openclaw.mjs")
    return "/npm/node_modules/openclaw/openclaw.mjs"


_wps_cache: dict[str, str | None] = {}


def find_wps(app: str = "et") -> str | None:
    """找本机 WPS 的 wps.exe（文字）/ et.exe（表格）/ wpp.exe（演示）。"""
    if app in _wps_cache:
        return _wps_cache[app]

    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kingsoft", "WPS Office")
    if not os.path.isdir(base):
        _wps_cache[app] = None
        return None

    def key(s: str):
        parts = []
        for x in s.split("."):
            parts.append(int(x) if x.isdigit() else 0)
        return parts

    for v in sorted(os.listdir(base), key=key, reverse=True):
        p = os.path.join(base, v, "office6", app + ".exe")
        if os.path.isfile(p):
            _wps_cache[app] = p
            return p
    _wps_cache[app] = None
    return None


def open_with_wps(path: str, app: str = "et") -> dict:
    exe = find_wps(app)
    if not exe:
        return {"ok": False, "error": "没找到 WPS，可能装在别的路径下"}
    if not os.path.isfile(path):
        return {"ok": False, "error": "文件不存在"}
    try:
        subprocess.Popen([exe, path])
        return {"ok": True, "exe": exe}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _deep_text(obj, depth: int = 0) -> str:
    """兜底：在任意嵌套结构里找第一个像正文的字符串。

    openclaw 的 --json 结构版本间会变，结构化提取失败时靠这个保底，
    避免把整包 JSON 当成回复丢给用户。
    """
    if depth > 6:
        return ""
    keys = ("text", "reply", "content", "message", "output", "body")

    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and len(v.strip()) > 1:
                return v.strip()
        for v in obj.values():
            if isinstance(v, (dict, list)):
                t = _deep_text(v, depth + 1)
                if t:
                    return t
    elif isinstance(obj, list):
        for v in obj:
            t = _deep_text(v, depth + 1)
            if t:
                return t
    return ""


# gpt-oss 偶尔把 reasoning 拼进正文，典型特征是冒出这种英文元叙述
_REASONING_LEAK = re.compile(
    r"(?:The user (?:asked|wants|says|requested|is asking)|"
    r"User (?:asked|wants|says)|Let me (?:think|analyze|check)|I need to )",
    re.I,
)


def _strip_reasoning(t: str) -> str:
    """正文里混进模型思考时，只保留思考之前那部分。

    只认第一次出现，且前一个字符不能是英文字母（否则它本来就在英文句子里）。
    宁可漏切也不误切 —— 真漏了用户还能展开原始输出看全文。
    """
    m = _REASONING_LEAK.search(t)
    if not m:
        return t
    i = m.start()
    if i == 0:
        return t
    prev = t[i - 1]
    if prev.isascii() and prev.isalpha():
        return t
    return t[:i].rstrip() or t


def _openclaw_parse(data: dict) -> tuple[str, dict]:
    """从 openclaw agent --json 的回包里取正文 + 元信息。

    真实结构：{ runId, status, summary,
                result: { payloads: [{ text, mediaUrl }], meta: { durationMs, agentMeta: {...} } } }
    """
    res = data.get("result") if isinstance(data, dict) else None
    texts: list[str] = []
    meta: dict = {}

    if isinstance(res, dict):
        ps = res.get("payloads")
        if isinstance(ps, list):
            for p in ps:
                if isinstance(p, dict):
                    t = p.get("text")
                    if isinstance(t, str) and t.strip():
                        texts.append(_strip_reasoning(t.strip()))

        m = res.get("meta")
        if isinstance(m, dict):
            am = m.get("agentMeta") if isinstance(m.get("agentMeta"), dict) else {}
            usage = am.get("usage") if isinstance(am.get("usage"), dict) else {}
            meta = {
                "duration_ms": m.get("durationMs"),
                "provider": am.get("provider") or "",
                "model": am.get("model") or "",
                "session": am.get("sessionFile") or "",
                "tokens": usage.get("total"),
                "cost_usd": am.get("costUsd"),
                "status": data.get("status") or "",
            }

    reply = "\n\n".join(texts).strip()
    if not reply:
        reply = _deep_text(data)
    return reply, meta


def _exec(cmd: list[str], timeout: int) -> dict:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            shell=_needs_shell(cmd),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"超过 {timeout} 秒没跑完", "raw": "", "code": -1}
    except FileNotFoundError:
        return {"ok": False, "error": "没找到 openclaw 或 node", "raw": "", "code": -1}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": "", "code": -1}

    out = (p.stdout or "").strip()
    data = None
    i = out.find("{")
    if i >= 0:
        try:
            data = json.loads(out[i:])
        except json.JSONDecodeError:
            pass

    reply = ""
    meta: dict = {}
    err = None
    if isinstance(data, dict):
        e = data.get("error")
        if isinstance(e, dict):
            err = e.get("message")
        elif isinstance(e, str):
            err = e
        reply, meta = _openclaw_parse(data)
        if not reply:
            for k in ("reply", "text", "content", "message", "summary"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    reply = v.strip()
                    break

    if not reply:
        # 实在取不到就给纯文本输出，绝不把整包 JSON 当回复
        reply = (err and f"OpenClaw 报错：{err}") or (out[:1500] if not out.startswith("{") else "（OpenClaw 没返回正文，看原始输出）")

    return {
        "ok": p.returncode == 0 and not err,
        "reply": reply,
        "error": err,
        "meta": meta,
        "raw": out[:20000],
        "code": p.returncode,
    }


def _openclaw_bin_candidates() -> list[str]:
    """常见安装位置里的 openclaw CLI 可执行文件（绝对路径），覆盖多种装法。"""
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".local", "bin", "openclaw"),        # 官方安装脚本（mac/linux）
        os.path.join(home, ".openclaw", "bin", "openclaw"),      # 官方脚本另一落点
        os.path.join(home, ".npm-global", "bin", "openclaw"),    # npm 自定义前缀
        "/opt/homebrew/bin/openclaw",                            # Homebrew（Apple Silicon）
        "/usr/local/bin/openclaw",                               # 系统 / Homebrew（Intel）
        "/usr/bin/openclaw",
    ]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cands.append(os.path.join(appdata, "npm", "openclaw.cmd"))   # Windows npm 全局
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        cands.append(os.path.join(localappdata, "openclaw", "openclaw.cmd"))
    return cands


def resolve_node() -> bool:
    """node 是否可用：先看 PATH，再看写死的 Windows 默认路径。"""
    return shutil.which("node") is not None or os.path.isfile(NODE)


def resolve_openclaw_cmd() -> list[str] | None:
    """返回能实际跑 openclaw 的命令列表；找不到返回 None。

    优先级：
      ① PATH 上的 openclaw（最通用：官方脚本 / brew / npm 全局都靠它）
      ② 上面列的常见安装目录里的绝对路径（不依赖 server 进程的 PATH）
      ③ Windows npm 装法：node + openclaw.mjs
    /api/claw/info 的「已就位」和真正跑任务都用同一个判定，避免一个说有、一个说没有。
    """
    w = shutil.which("openclaw")
    if w:
        return [w]
    for c in _openclaw_bin_candidates():
        if os.path.isfile(c):
            return [c]
    node = shutil.which("node") or (NODE if os.path.isfile(NODE) else None)
    mjs = _openclaw_mjs()
    if node and os.path.isfile(mjs):
        return [node, mjs]
    return None


def _needs_shell(cmd: list[str]) -> bool:
    """Windows 上 npm 装的是 openclaw.cmd/.ps1 这类 shim，直接当可执行跑会 FileNotFound，
    需要走 cmd.exe / powershell。unix 上不会出现这些后缀，保持 shell=False。"""
    return bool(cmd) and cmd[0].lower().endswith((".cmd", ".bat", ".ps1"))


def _openclaw_base() -> list[str]:
    return resolve_openclaw_cmd() or ["openclaw"]


_claw_cache: dict[str, tuple[float, dict]] = {}


def openclaw_cmd(args: list[str], timeout: int = 60, cache_ttl: int = 0) -> dict:
    """跑任意只读 openclaw 子命令，返回 {ok, raw, json}。

    cache_ttl > 0 时按命令缓存（这些命令都要几秒，别每次点都跑）。
    只给只读命令用 —— 写操作一律走 openclaw_run 或不开后门。
    """
    key = " ".join(args)
    if cache_ttl > 0:
        hit = _claw_cache.get(key)
        if hit and time.time() - hit[0] < cache_ttl:
            return {**hit[1], "cached": True}

    try:
        p = subprocess.run(_openclaw_base() + args, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           shell=_needs_shell(_openclaw_base() + args))
        raw = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"超过 {timeout} 秒没返回", "raw": "", "json": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": "", "json": None}

    parsed = None
    i = raw.find("{")
    if i >= 0:
        try:
            parsed = json.loads(raw[i:])
        except json.JSONDecodeError:
            parsed = None

    res = {
        "ok": p.returncode == 0,
        "raw": raw[:20000],
        "json": parsed,
        "error": None if p.returncode == 0 else (raw or err)[:800],
    }
    if cache_ttl > 0:
        _claw_cache[key] = (time.time(), res)
    return res


def openclaw_agents() -> dict:
    """openclaw agents list —— 纯文本，格式固定：
    Agents:
    - main (default)
      Identity: ...
      Workspace: ...
      Model: ollama/xxx
    """
    r = openclaw_cmd(["agents", "list"], timeout=60, cache_ttl=300)
    agents = []
    cur = None
    for line in (r.get("raw") or "").splitlines():
        m = re.match(r"^-\s+(\S+)\s*(\(default\))?", line)
        if m:
            cur = {"id": m.group(1), "default": bool(m.group(2)), "model": "", "workspace": ""}
            agents.append(cur)
            continue
        if cur is not None:
            m2 = re.match(r"^\s+(Identity|Workspace|Model|Routing):\s*(.+)$", line)
            if m2:
                k, v = m2.group(1), m2.group(2).strip()
                if k == "Model":
                    cur["model"] = v
                elif k == "Workspace":
                    cur["workspace"] = v
    return {"ok": r.get("ok", False), "agents": agents,
            "error": r.get("error"), "cached": r.get("cached", False),
            "raw": r.get("raw", "")}


def openclaw_skills() -> dict:
    """openclaw skills list --json"""
    r = openclaw_cmd(["skills", "list", "--json"], timeout=60, cache_ttl=300)
    j = r.get("json") or {}
    raw = j.get("skills") if isinstance(j, dict) else None
    rows = []
    if isinstance(raw, list):
        for s in raw:
            if not isinstance(s, dict):
                continue
            miss = s.get("missing") or {}
            rows.append({
                "name": s.get("name") or "",
                "desc": s.get("description") or "",
                "source": s.get("source") or "",
                "eligible": bool(s.get("eligible")),
                "disabled": bool(s.get("disabled")),
                "missing_bins": (miss.get("bins") or []) if isinstance(miss, dict) else [],
            })
    return {"ok": r.get("ok", False), "rows": rows, "error": r.get("error"),
            "cached": r.get("cached", False), "dir": j.get("managedSkillsDir", "") if isinstance(j, dict) else ""}


def openclaw_skill_install(name: str, timeout: int = 180) -> dict:
    """装一个 ClawHub / OpenClaw 技能：openclaw skills install <name>。

    本机没装 openclaw 就如实报错，不假装成功；装完返回原始输出，
    前端自己判断成没成功（多数情况下 eligible 会变 true）。
    命令语法不是 100% 确定（openclaw 版本间可能变），所以整段 raw 都回传，
    失败了好让前端把报错直接摊给用户看。
    """
    if not name or not name.strip():
        return {"ok": False, "error": "没指定技能名"}
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-/]+", name):
        return {"ok": False, "error": "技能名不合法"}
    res = _exec(_openclaw_base() + ["skills", "install", name], timeout)
    return {
        "ok": bool(res.get("ok")),
        "raw": res.get("raw", ""),
        "error": res.get("error") or None,
        "code": res.get("code"),
    }


def workbuddy_skills(max_depth: int = 4) -> dict:
    """扫本机 WorkBuddy 技能目录，解析每个 SKILL.md 的 frontmatter。

    两类来源：
      ~/.workbuddy/skills/                用户自己装的
      ~/.workbuddy/connectors/skills/     连接器带的（可能嵌套两层）
    """
    home = os.path.expanduser("~")
    roots = [
        ("用户技能", os.path.join(home, ".workbuddy", "skills")),
        ("连接器技能", os.path.join(home, ".workbuddy", "connectors", "skills")),
    ]
    rows = []
    for label, root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > max_depth:
                dirnames[:] = []
                continue
            if "SKILL.md" not in filenames:
                continue
            fp = os.path.join(dirpath, "SKILL.md")
            try:
                text = open(fp, encoding="utf-8", errors="replace").read(4000)
            except OSError:
                continue
            name, desc = _frontmatter(text)
            if not name:
                name = os.path.basename(dirpath)
            rows.append({
                "name": name,
                "desc": desc,
                "src": label,
                "path": fp,
                "dir": os.path.basename(dirpath),
            })
    rows.sort(key=lambda r: (r["src"], r["name"].lower()))
    return {"ok": True, "rows": rows, "count": len(rows)}


def _frontmatter(text: str) -> tuple[str, str]:
    """抠 SKILL.md 头部 --- 之间的 name / description。"""
    name = ""
    desc = ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", ""
    buf: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        buf.append(ln)
    key = None
    for ln in buf:
        if not ln.strip():
            continue
        if ln[:1] in (" ", "\t") and key:
            # 缩进续行，接在上一个字段后面
            if key == "description":
                desc += " " + ln.strip()
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if key == "name":
                name = val
            elif key == "description":
                desc = val
    return name, desc.strip()[:400]


def openclaw_health() -> dict:
    """健康检查：不跑 doctor（它会改东西），只做本地只读判定。"""
    import socket
    cmd = resolve_openclaw_cmd()
    ver = openclaw_cmd(["--version"], timeout=30, cache_ttl=600)
    gw = False
    try:
        with socket.create_connection(("127.0.0.1", 18789), timeout=1.5):
            gw = True
    except OSError:
        gw = False
    return {
        "ok": True,
        "cli_exists": cmd is not None,
        "cli_path": cmd[0] if cmd else "",
        "node": resolve_node(),
        "version": (ver.get("raw") or "").strip()[:80],
        "gateway_port": 18789,
        "gateway_up": gw,
    }


def openclaw_automations() -> dict:
    """openclaw automations list（cron 的别名，走 Gateway）。
    某些环境下会去碰系统计划任务，失败就如实返回，不重试。"""
    r = openclaw_cmd(["automations", "list"], timeout=60, cache_ttl=120)
    return {"ok": r.get("ok", False), "raw": r.get("raw", "")[:6000],
            "error": r.get("error"), "cached": r.get("cached", False)}


# OpenClaw 每次任务都携带的「神经操作手册」：让它知道怎么直接读写工作台。
# 全确认模式：所有写操作进待审队列，用户在工作台确认后才执行。
_NEURO_MANUAL = """[工作台神经桥——你正运行在用户的本地数字工作台里，可以直接读写它]
你有一个受信本地桥，用来把结果写进工作台（不是只回文字）：
  POST http://127.0.0.1:8777/api/bridge/submit
  请求体 JSON：{"action": "<动作>", "payload": {<参数>}}
可用动作与 payload：
  - "today/add":       {"day":"YYYY-MM-DD","text":"待办内容","project_id":0}
  - "today/toggle":    {"id": 数字,"done":1}
  - "today/del":       {"id": 数字}
  - "kb/save":         {"title":"标题","body":"正文","tags":"逗号分隔标签"}
  - "kb/del":          {"id": 数字}
  - "projects/save":   {"name":"项目名","status":"进行中","next_step":"下一步"}
  - "projects/del":    {"id": 数字}
  - "cal/add":         {"day":"YYYY-MM-DD","start":"14:00","end":"15:00","title":"标题","note":""}
  - "cal/del":         {"id": 数字}
  - "meeting/add":     {"day":"YYYY-MM-DD","start":"14:00","end":"15:00","title":"标题","location":"地点(可选)","link":"线上入会链接/会议号(可选)","attendees":"参会人(可选)","note":"备注(可选)","remind_before":10}
  - "meeting/del":     {"id": 数字}
  - "reminders/add":   {"at": 秒级时间戳,"text":"提醒内容"}
  - "reminders/done":  {"id": 数字,"done":1}
  - "reminders/del":   {"id": 数字}
  - "inbox/add":       {"text":"随手记内容"}
读工作台数据用 GET（无需桥）：/api/today?day=YYYY-MM-DD、/api/projects、/api/kb、/api/reminders、/api/inbox、/api/openclaw/history
【全确认规则·务必遵守】所有写操作提交后会进入「待审队列」，必须用户在工作台点「确认」才会真正执行。
你提交后告诉用户：「我已在工作台提交了 X，请到 OpenClaw 页的『待确认』里确认执行」，不要假设已经执行、也不要重复提交同一条。
绝不用桥执行删除系统文件、rm/del 类终端命令或任何破坏性操作——那不在你的权限内。"""


def openclaw_run(task: str, ctx: str = "", timeout: int = 240) -> dict:
    """优先走已在运行的 Gateway；Gateway 没起时才回退 --local。

    ctx 是工作台注入的真实上下文（今日待办/项目/资料库/日志），作为背景块拼进任务，
    让 OpenClaw 不再是瞎子。空串表示不注入。
    """
    base = _openclaw_base()

    msg = task
    if ctx and ctx.strip():
        msg = (
            "[工作台上下文——你正在用户的数字工作台里工作，下面是该工作台当前的真实状态，"
            "仅作背景参考，不是用户要你做的事；若结果需要写回工作台（加待办/存资料库/建项目），"
            "直接在回复里说明即可，前端会提供一键写入]\n\n"
            + ctx.strip()
            + "\n\n[用户本次的任务]\n"
            + task
        )

    msg = msg + "\n\n" + _NEURO_MANUAL

    cmd = base + ["agent", "-m", msg, "--json"]
    r = _exec(cmd, timeout)

    if not r["ok"] and re.search(
        r"no gateway|gateway (is )?not running|start the gateway|gateway unavailable",
        r["raw"], re.I,
    ):
        r = _exec(base + ["agent", "-m", msg, "--local", "--json"], timeout)
    return r


def ai_complete(prompt: str, cfg: dict, timeout: int = 180) -> dict:
    """一次性补全（非流式），给「AI 生成表格」这类场景用。"""
    base = cfg["base_url"].rstrip("/")
    if not base:
        return {"ok": False, "error": "还没配置 AI 接口"}
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    try:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        ch = d.get("choices") or [{}]
        msg = ch[0].get("message") or {}
        return {"ok": True, "text": msg.get("content") or msg.get("reasoning") or ""}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"{e.code} {e.read().decode('utf-8','ignore')[:300]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_launch_cache: dict = {"at": 0.0, "rows": []}


def launch_list(ttl: int = 600) -> dict:
    """扫本机装了什么程序 —— 给快捷启动器用。

    只扫固定几个安装位置、限制深度，别全盘找 exe（会扫出几万个还没用）。
    开始菜单的 .lnk 解析要 pywin32，本机没装，所以不碰。
    """
    now = time.time()
    if _launch_cache["rows"] and now - _launch_cache["at"] < ttl:
        return {"ok": True, "rows": _launch_cache["rows"], "cached": True}

    roots = [
        (os.environ.get("ProgramFiles", r"C:\Program Files"), 2),
        (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), 2),
        (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"), 3),
    ]
    skip = ("uninstall", "unins000", "setup", "crashpad", "updater",
            "uninst", "activation", "vcredist", "dxwebsetup")
    rows = []
    seen = set()

    for root, depth in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, files in os.walk(root):
            d = dirpath[len(root):].count(os.sep)
            if d >= depth:
                dirnames[:] = []
            for f in files:
                if not f.lower().endswith(".exe"):
                    continue
                low = f.lower()
                if any(s in low for s in skip):
                    continue
                if len(rows) >= 500:
                    break
                fp = os.path.join(dirpath, f)
                key = low
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "name": f[:-4],
                    "path": fp,
                    "dir": os.path.basename(dirpath),
                })
            if len(rows) >= 500:
                break
        if len(rows) >= 500:
            break

    rows.sort(key=lambda r: r["name"].lower())
    _launch_cache["at"] = now
    _launch_cache["rows"] = rows
    return {"ok": True, "rows": rows, "cached": False}


def nl_to_query(q: str, cfg: dict) -> dict:
    """把大白话翻成检索条件。只让模型输出 JSON，不给它自由发挥的余地。

    返回 {kw, ext, path, min_size_mb, days} —— 拿不到就退化成整句当关键词。
    """
    prompt = (
        "你是文件检索助手。把用户的描述翻译成检索条件，只输出 JSON，不要别的文字。\n"
        '格式：{"kw":"文件名关键词","ext":"扩展名不带点或空","path":"路径片段或空",'
        '"min_size_mb":数字或0,"days":最近几天或0}\n\n'
        "例子：\n"
        "用户：上周下的那个安装包\n"
        '输出：{"kw":"","ext":"exe","path":"","min_size_mb":10,"days":7}\n'
        "用户：D盘里特别大的视频\n"
        '输出：{"kw":"","ext":"mp4","path":"D:\\\\","min_size_mb":500,"days":0}\n'
        "用户：voxelcraft 的 html 文件\n"
        '输出：{"kw":"voxelcraft","ext":"html","path":"","min_size_mb":0,"days":0}\n\n'
        f"用户：{q}\n输出："
    )
    r = ai_complete(prompt, cfg, timeout=90)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "kw": q, "ext": "",
                "path": "", "min_size_mb": 0, "days": 0}

    text = (r.get("text") or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"ok": True, "kw": q, "ext": "", "path": "", "min_size_mb": 0,
                "days": 0, "note": "模型没给结构化结果，按整句搜"}

    def num(v, d=0):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return d

    try:
        o = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"ok": True, "kw": q, "ext": "", "path": "", "min_size_mb": 0,
                "days": 0, "note": "模型输出不是合法 JSON，按整句搜"}

    return {
        "ok": True,
        "kw": str(o.get("kw") or "")[:80],
        "ext": str(o.get("ext") or "").strip().lstrip(".")[:16],
        "path": str(o.get("path") or "")[:200],
        "min_size_mb": num(o.get("min_size_mb"), 0),
        "days": num(o.get("days"), 0),
        "raw": text[:400],
    }


def extract_json_array(text: str):
    """从模型输出里抠出第一段 JSON 数组。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


# ---------- 连接器：把工作台推到外部（微信等）----------
# 这是「务实扩展」的第一个样板：工作台不再只是本地孤岛，能接外部通道。
# 新增通道 = 在 connector_push 里加一个 case，前端连接器面板自然支持。

def pushplus_send(token: str, title: str, content: str, topic: str = "") -> dict:
    """PushPlus 单向推送：工作台 -> 微信（服务号）。一个 token 即用，不碰逆向协议。

    文档 https://www.pushplus.plus/doc/ 。成功 {ok:True}，失败带 error。
    """
    if not token or not token.strip():
        return {"ok": False, "error": "没填 PushPlus token"}
    body = {
        "token": token.strip(),
        "title": (title or "工作台")[:80],
        "content": (content or "").replace("\n", "<br>"),
        "template": "html",
    }
    if topic:
        body["topic"] = topic[:40]
    try:
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            o = json.loads(r.read().decode("utf-8", "ignore"))
        if o.get("code") == 200:
            return {"ok": True, "msg": o.get("msg", "已发送")}
        return {"ok": False, "error": o.get("msg") or f"code={o.get('code')}"}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return {"ok": False, "error": f"{e.code} {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def serverchan_send(token: str, title: str, content: str) -> dict:
    """Server 酱（sc.ftqq.com / sctapi.ftqq.com）单向推送，token 即 sendkey。"""
    if not token or not token.strip():
        return {"ok": False, "error": "没填 Server 酱 token"}
    try:
        url = f"https://sctapi.ftqq.com/{token.strip()}.send"
        data = urllib.parse.urlencode(
            {"title": title or "工作台", "desp": content or ""}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            o = json.loads(r.read().decode("utf-8", "ignore"))
        if o.get("code") == 0:
            return {"ok": True, "msg": o.get("message", "已发送")}
        return {"ok": False, "error": o.get("message") or f"code={o.get('code')}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def connector_push(connector: dict, title: str, content: str) -> dict:
    """按连接器类型分发推送。新增类型在这里加 case 即可。"""
    ctype = (connector.get("type") or "").lower()
    token = connector.get("token") or ""
    if ctype in ("pushplus", "push", "pushplus+", "wechat"):
        return pushplus_send(token, title, content, connector.get("topic", ""))
    if ctype in ("serverchan", "sc", "server酱"):
        return serverchan_send(token, title, content)
    return {"ok": False, "error": f"不支持的连接器类型：{ctype}"}
