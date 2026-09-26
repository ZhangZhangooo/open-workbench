"""邮件：直连 IMAP / SMTP，不依赖任何邮件客户端。

网易邮箱大师没有开放 API，但它本质上就是 IMAP/SMTP 客户端，
所以这里直接走标准协议 —— 标准库实现，零依赖。

网易邮箱需要在网页版设置里开启 IMAP/SMTP 服务，并生成「授权码」，
这里的 password 填授权码，不是登录密码。

踩过的坑：
- 网易 IMAP 要求客户端先发 ID 命令声明身份，否则 SELECT 阶段会被拒，
  表现为 "SEARCH illegal in state AUTH" 这种看起来莫名其妙的状态错误
- SEARCH 返回空结果时 data[0] 是 None，不能直接 .split()
"""

from __future__ import annotations

import base64
import email
import imaplib
import re
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

TIMEOUT = 20

# imaplib 默认不认识 ID 命令（RFC 2971），网易系邮箱没它会拒 SELECT
if "ID" not in imaplib.Commands:
    imaplib.Commands["ID"] = ("AUTH", "SELECTED")

ID_ARGS = (
    '("name" "WorkBench" "version" "1.0" "vendor" "workbench" '
    '"contact" "local")'
)

PRESETS = {
    "163": ("imap.163.com", 993, "smtp.163.com", 465),
    "126": ("imap.126.com", 993, "smtp.126.com", 465),
    "yeah": ("imap.yeah.net", 993, "smtp.yeah.net", 465),
    "qq": ("imap.qq.com", 993, "smtp.qq.com", 465),
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "outlook": ("outlook.office365.com", 993, "smtp.office365.com", 587),
}

_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)')


def dec(s) -> str:
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:  # noqa: BLE001
        return str(s)


def _mutf7(s: str) -> str:
    """解 modified UTF-7（&UXZO1mWHTvZZOQ- → 已发送）。

    Python 内置的 utf-7 编解码器跟 IMAP 用的不是一回事，所以自己来。
    """
    def repl(m):
        inner = m.group(1)
        if not inner:
            return "&"
        pad = "=" * (-len(inner) % 4)
        try:
            return base64.b64decode(inner.replace(",", "/") + pad).decode("utf-16-be")
        except Exception:  # noqa: BLE001
            return m.group(0)

    return re.sub(r"&([A-Za-z0-9+,]*)-?", repl, s)


def _folder_name(raw: bytes) -> str:
    """从 LIST 的一行里取出文件夹名。"""
    m = _LIST_RE.match(raw)
    if not m:
        return _mutf7(raw.decode("utf-8", "replace"))
    name = m.group("name").strip().strip(b'"')
    return _mutf7(name.decode("utf-8", "replace"))


class MailClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _need(self) -> str | None:
        if not self.cfg.get("user") or not self.cfg.get("password"):
            return "还没填邮箱账号和授权码"
        if not self.cfg.get("imap_host"):
            return "还没填 IMAP 服务器地址"
        return None

    def _imap(self):
        return imaplib.IMAP4_SSL(
            self.cfg["imap_host"], int(self.cfg.get("imap_port") or 993), timeout=TIMEOUT
        )

    def _say_id(self, c) -> str:
        """发 ID 声明。服务器不认就算了，不让它挡路。"""
        try:
            typ, dat = c._simple_command("ID", ID_ARGS)
            return f"{typ} {dat[0].decode('utf-8', 'replace')[:80]}" if dat else str(typ)
        except Exception as e:  # noqa: BLE001
            return f"跳过（{type(e).__name__}）"

    def _folders(self, c) -> list[str]:
        try:
            typ, dat = c.list()
            return [_folder_name(x) for x in (dat or []) if isinstance(x, bytes)]
        except Exception:  # noqa: BLE001
            return []

    def _open_inbox(self, c, folders: list[str] | None = None) -> tuple[bool, str, list[str]]:
        """选中收件箱。INBOX 不行就挨个试 LIST 出来的文件夹。"""
        if folders is None:
            folders = self._folders(c)

        for name in ["INBOX"] + folders:
            try:
                typ, dat = c.select('"%s"' % name.replace('"', ""))
                if typ == "OK":
                    n = (dat[0].decode() if dat and dat[0] else "?")
                    return True, f"已选中 {name}（{n} 封）", folders
            except Exception:  # noqa: BLE001
                continue
        return False, "所有文件夹都选不中（通常是授权码不对，或没开 IMAP 服务）", folders

    def list(self, limit: int = 30, unseen_only: bool = False, q: str = "") -> dict:
        err = self._need()
        if err:
            return {"ok": False, "error": err}
        try:
            c = self._imap()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"连不上 IMAP：{type(e).__name__}: {e}"}
        try:
            c.login(self.cfg["user"], self.cfg["password"])
            self._say_id(c)

            ok, detail, _ = self._open_inbox(c)
            if not ok:
                return {"ok": False, "error": detail}
            if getattr(c, "state", "") != "SELECTED":
                return {"ok": False, "error": "没进到收件箱（IMAP 状态仍是 " + str(getattr(c, "state", "?")) + "）"}

            q = (q or "").strip()
            if q:
                safe = q.replace("\\", "\\\\").replace('"', '\\"')
                crit = f'(OR SUBJECT "{safe}" FROM "{safe}")'
            else:
                crit = "UNSEEN" if unseen_only else "ALL"

            # 用 UID 而不是序号：序号只在本次会话有效，下次打开就可能对不上号
            typ, data = c.uid("SEARCH", None, crit)
            ids = (data[0] or b"").split()[::-1][:limit]

            out = []
            for i in ids:
                try:
                    typ, d = c.uid(
                        "FETCH", i,
                        "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])",
                    )
                except Exception:  # noqa: BLE001
                    continue
                if not d or not d[0] or not isinstance(d[0], tuple):
                    continue
                m = email.message_from_bytes(d[0][1])
                out.append({
                    "uid": i.decode(),
                    "subject": dec(m["Subject"]),
                    "from": dec(m["From"]),
                    "date": self._when(m["Date"]),
                })
            return {"ok": True, "rows": out}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            try:
                c.logout()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _when(v) -> str:
        try:
            return parsedate_to_datetime(v).strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _html_to_text(s: str) -> str:
        """HTML 邮件转纯文本。不做渲染，够读就行。"""
        s = re.sub(r"(?is)<(script|style|head).*?</\1>", "", s)
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)>", "\n", s)
        s = re.sub(r"(?i)<[^>]+>", "", s)
        s = unescape(s)
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"(?m)^[ \t]+", "", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return "\n".join(x.rstrip() for x in s.split("\n")).strip()

    @staticmethod
    def _extract(msg) -> tuple[str, list[str], bool]:
        """取正文（纯文本优先，没有就剥 HTML）+ 附件名列表 + 是否由 HTML 转来。"""
        plain = html_src = ""
        atts: list[str] = []

        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "").lower()
            fn = part.get_filename()

            if fn or "attachment" in disp:
                atts.append(dec(fn or part.get_param("name") or "附件"))
                continue

            raw = part.get_payload(decode=True)
            if not raw:
                continue
            cs = part.get_content_charset() or "utf-8"
            try:
                txt = raw.decode(cs, "replace")
            except (LookupError, TypeError):
                txt = raw.decode("utf-8", "replace")

            if ctype == "text/plain" and not plain:
                plain = txt
            elif ctype == "text/html" and not html_src:
                html_src = txt

        if plain.strip():
            return plain.strip(), atts, False
        return MailClient._html_to_text(html_src), atts, bool(html_src)

    def read(self, uid: str, mark_seen: bool = True) -> dict:
        """读一封邮件的全文。"""
        err = self._need()
        if err:
            return {"ok": False, "error": err}
        try:
            c = self._imap()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"连不上 IMAP：{type(e).__name__}: {e}"}
        try:
            c.login(self.cfg["user"], self.cfg["password"])
            self._say_id(c)
            ok, detail, _ = self._open_inbox(c)
            if not ok:
                return {"ok": False, "error": detail}

            typ, d = c.uid("FETCH", uid.encode(), "(RFC822)")
            if not d or not d[0] or not isinstance(d[0], tuple):
                return {"ok": False, "error": "这封邮件取不到（可能已被删除）"}

            msg = email.message_from_bytes(d[0][1])
            body, atts, from_html = self._extract(msg)
            if len(body) > 20000:
                body = body[:20000] + "\n\n…（太长，已截断）"

            if mark_seen:
                try:
                    c.uid("STORE", uid.encode(), "+FLAGS", "\\Seen")
                except Exception:  # noqa: BLE001
                    pass

            return {
                "ok": True,
                "uid": uid,
                "subject": dec(msg["Subject"]),
                "from": dec(msg["From"]),
                "reply_to": self.reply_to(dec(msg["From"])),
                "to": dec(msg["To"]),
                "date": self._when(msg["Date"]),
                "body": body,
                "from_html": from_html,
                "attachments": atts,
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            try:
                c.logout()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def reply_to(from_header: str) -> str:
        """从 "Name <a@b.c>" 里抠出地址，用于回复时填收件人。"""
        try:
            pairs = getaddresses([from_header or ""])
        except Exception:  # noqa: BLE001
            return ""
        for _, addr in pairs:
            if addr and "@" in addr:
                return addr
        return ""

    def diagnose(self) -> dict:
        """一步一步试，把卡在哪一步说清楚 —— 邮箱配置问题只能这样定位。"""
        steps: list[dict] = []

        def add(name, ok, detail=""):
            steps.append({"name": name, "ok": ok, "detail": str(detail)})

        err = self._need()
        if err:
            add("检查配置", False, err)
            return {"ok": False, "error": err, "steps": steps}

        host = self.cfg["imap_host"]
        port = int(self.cfg.get("imap_port") or 993)
        try:
            c = self._imap()
            add(f"连接 {host}:{port}", True, "SSL 握手成功")
        except Exception as e:  # noqa: BLE001
            add(f"连接 {host}:{port}", False, f"{type(e).__name__}: {e}")
            return {"ok": False, "error": f"连不上 {host}：{e}", "steps": steps}

        try:
            c.login(self.cfg["user"], self.cfg["password"])
            add("登录", True, self.cfg["user"])
        except Exception as e:  # noqa: BLE001
            add("登录", False, f"{e}（密码栏要填授权码，不是登录密码；并确认网页版已开启 IMAP）")
            try:
                c.logout()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": f"登录失败：{e}", "steps": steps}

        add("声明客户端 ID", True, self._say_id(c))

        folders = self._folders(c)
        add("列出文件夹", True, f"{len(folders)} 个：" + "、".join(folders[:6]))

        ok, detail, folders = self._open_inbox(c, folders)
        add("进入收件箱", ok, detail)
        if not ok:
            try:
                c.logout()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": detail, "steps": steps, "folders": folders}

        try:
            typ, data = c.uid("SEARCH", None, "ALL")
            ids = (data[0] or b"").split()
            add("搜索邮件", True, f"共 {len(ids)} 封")
        except Exception as e:  # noqa: BLE001
            add("搜索邮件", False, f"{type(e).__name__}: {e}")
            try:
                c.logout()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": f"搜索失败：{e}", "steps": steps, "folders": folders}

        try:
            c.logout()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "steps": steps, "folders": folders, "count": len(ids)}

    def send(self, to: str, subject: str, body: str) -> dict:
        err = self._need()
        if err:
            return {"ok": False, "error": err}
        msg = EmailMessage()
        msg["From"] = self.cfg["user"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        port = int(self.cfg.get("smtp_port") or 465)
        try:
            if port == 587:
                s = smtplib.SMTP(self.cfg["smtp_host"], port, timeout=TIMEOUT)
                s.starttls()
            else:
                s = smtplib.SMTP_SSL(self.cfg["smtp_host"], port, timeout=TIMEOUT)
            s.login(self.cfg["user"], self.cfg["password"])
            s.send_message(msg)
            s.quit()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
