"""企业微信（WeCom）回调消息加解密 —— 纯 Python 标准库实现，零第三方依赖。

对齐官方规范《加解密方案说明》：
https://developer.work.weixin.qq.com/document/path/90930
（与微信公众号同一套 WXBizMsgCrypt，企业微信沿用了它。）

规范要点，代码里逐条对上：
  1. EncodingAESKey 是 43 个字符的 base64（末尾不带 '='），补一个才够 32 字节；
  2. 算法是 AES-256-CBC，IV 取密钥的前 16 字节；
  3. 明文布局：16 字节随机数 | 4 字节网络序(大端)长度 | msg | receive_id(corpid)；
  4. 填充用 PKCS7，但**块长是 32 不是 16**（这条最容易踩坑）；
  5. 签名 = sha1( 排序后拼接(token, timestamp, nonce, encrypt) )；
  6. URL 校验那一步，echostr 是明文，直接拿去参与签名，不解密。

为什么自己写 AES 而不装 pycryptodome：本项目硬性约束「零第三方依赖」，
装包会破坏「clone 下来就能跑」这个前提。所以这里用纯 Python 实现 AES
（S-box 用有限域求逆当场生成，避免手抄 256 个字节抄错），
再用 FIPS-197 / NIST SP 800-38A 的官方向量自证正确 —— 见 selftest()。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import struct
import time
import xml.etree.ElementTree as ET

# ============================================================================
# 一、AES 内核（纯 Python，AES-256）
# ============================================================================


def _rotl8(b: int, n: int) -> int:
    return ((b << n) | (b >> (8 - n))) & 0xFF


def _build_sbox() -> list[int]:
    """生成 AES 的 S-box。

    用经典的「GF(2^8) 求逆 + 仿射变换」快速算法，省得手抄 256 个字节抄错。
    p 按 ×3 迭代扫过 1..255（这是 GF(2^8) 的一个生成元），
    q 用平方链算出 p 的乘法逆元，最后套仿射变换。
    """
    sbox = [0] * 256
    p = q = 1
    while True:
        # p = p * 3 = p ^ (p << 1)，越界就异或 0x1B
        p ^= ((p << 1) & 0xFF) ^ (0x1B if (p & 0x80) else 0)
        p &= 0xFF
        # q = q * q（在 GF(2^8) 里做平方，等价于连续三次 <<）
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        q &= 0xFF
        x = q ^ _rotl8(q, 1) ^ _rotl8(q, 2) ^ _rotl8(q, 3) ^ _rotl8(q, 4) ^ 0x63
        sbox[p] = x & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


SBOX = _build_sbox()

_INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    _INV_SBOX[_v] = _i
INV_SBOX = _INV_SBOX

# 轮常量，索引 1 起（i//nk 从 1 开始用）
_RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    """GF(2^8) 乘法（AES 用的本原多项式 0x11B）。"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p & 0xFF


def _expand_key(key: bytes) -> tuple[list[list[int]], int]:
    """密钥扩展。返回 (轮密钥字数组 w, 轮数 nr)。"""
    nk = len(key) // 4                 # AES-256 -> 8
    nr = nk + 6                        # AES-256 -> 14
    w = [[key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]] for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]                      # RotWord
            t = [SBOX[b] for b in t]               # SubWord
            t[0] ^= _RCON[i // nk]
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]               # AES-256 独有的额外 SubWord
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _add_round_key(s: list[list[int]], w: list[list[int]], rnd: int) -> None:
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[rnd * 4 + c][r]


def _sub_bytes(s: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            s[r][c] = SBOX[s[r][c]]


def _inv_sub_bytes(s: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            s[r][c] = INV_SBOX[s[r][c]]


def _shift_rows(s: list[list[int]]) -> None:
    for r in range(1, 4):
        s[r] = s[r][r:] + s[r][:r]


def _inv_shift_rows(s: list[list[int]]) -> None:
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]


def _mix_columns(s: list[list[int]]) -> None:
    for c in range(4):
        a = [s[r][c] for r in range(4)]
        s[0][c] = _gmul(a[0], 2) ^ _gmul(a[1], 3) ^ a[2] ^ a[3]
        s[1][c] = a[0] ^ _gmul(a[1], 2) ^ _gmul(a[2], 3) ^ a[3]
        s[2][c] = a[0] ^ a[1] ^ _gmul(a[2], 2) ^ _gmul(a[3], 3)
        s[3][c] = _gmul(a[0], 3) ^ a[1] ^ a[2] ^ _gmul(a[3], 2)


def _inv_mix_columns(s: list[list[int]]) -> None:
    for c in range(4):
        a = [s[r][c] for r in range(4)]
        s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
        s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
        s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
        s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)


def aes_encrypt_block(block: bytes, key: bytes) -> bytes:
    """AES 加密单个 16 字节分组（ECB 语义，CBC 内部也用它）。"""
    if len(block) != 16:
        raise ValueError("AES 分组必须是 16 字节")
    w, nr = _expand_key(key)
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]   # 列主序
    _add_round_key(s, w, 0)
    for rnd in range(1, nr):
        _sub_bytes(s)
        _shift_rows(s)
        _mix_columns(s)
        _add_round_key(s, w, rnd)
    _sub_bytes(s)
    _shift_rows(s)
    _add_round_key(s, w, nr)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes_decrypt_block(block: bytes, key: bytes) -> bytes:
    """AES 解密单个 16 字节分组。"""
    if len(block) != 16:
        raise ValueError("AES 分组必须是 16 字节")
    w, nr = _expand_key(key)
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    _add_round_key(s, w, nr)
    for rnd in range(nr - 1, 0, -1):
        _inv_shift_rows(s)
        _inv_sub_bytes(s)
        _add_round_key(s, w, rnd)
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    _inv_sub_bytes(s)
    _add_round_key(s, w, 0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(data) % 16:
        raise ValueError("CBC 要求输入 16 字节对齐")
    w, nr = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = aes_encrypt_block(blk, key)
        out += prev
    return bytes(out)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(data) % 16:
        raise ValueError("CBC 要求输入 16 字节对齐")
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(aes_decrypt_block(blk, key), prev))
        prev = blk
    return bytes(out)


# ============================================================================
# 二、PKCS7 填充（块长 32）
# ============================================================================


def pkcs7_pad(data: bytes, block: int = 32) -> bytes:
    n = block - (len(data) % block)
    if n == 0:
        n = block
    return data + bytes([n]) * n


def pkcs7_unpad(data: bytes, block: int = 32) -> bytes:
    if not data:
        raise ValueError("解密结果为空")
    n = data[-1]
    if n < 1 or n > block or n > len(data):
        raise ValueError(f"PKCS7 填充字节非法：{n}")
    if data[-n:] != bytes([n]) * n:
        raise ValueError("PKCS7 填充内容不一致")
    return data[:-n]


# ============================================================================
# 三、企业微信协议层
# ============================================================================


def parse_aes_key(encoding_aes_key: str) -> bytes:
    """EncodingAESKey -> 32 字节密钥。43 个字符，自带补一个 '='。"""
    k = (encoding_aes_key or "").strip()
    if len(k) != 43:
        raise ValueError("EncodingAESKey 必须是 43 个字符（企业微信后台生成的那串）")
    try:
        raw = base64.b64decode(k + "=")
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"EncodingAESKey 不是合法 base64：{e}") from e
    if len(raw) != 32:
        raise ValueError(f"EncodingAESKey 解出来 {len(raw)} 字节，应该是 32")
    return raw


def compute_signature(token: str, timestamp, nonce, encrypt: str) -> str:
    """sha1( 排序拼接(token, timestamp, nonce, encrypt) )。

    官方 demo 就是把四个值当字符串排序再拼，别自作聪明按数字排序。
    """
    parts = sorted([str(token or ""), str(timestamp or ""), str(nonce or ""), str(encrypt or "")])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def random_aes_key() -> str:
    """随机生成一个合法的 43 字符 EncodingAESKey（前端「随机生成」按钮用）。"""
    raw = os.urandom(32)
    return base64.b64encode(raw).decode("ascii").rstrip("=")[:43]


def random_nonce() -> str:
    return str(int.from_bytes(os.urandom(4), "big"))


def parse_xml(text: str) -> dict:
    """把企业微信的 XML 拉平成 dict。

    ElementTree 会把 <![CDATA[...]]> 当普通文本，正好省事。
    遇到畸形 XML 再用正则兜一层，不至于整条消息丢掉。
    """
    out: dict = {}
    if not text:
        return out
    try:
        root = ET.fromstring(text.strip())
        for child in root:
            out[child.tag] = (child.text or "").strip()
        if out:
            return out
    except ET.ParseError:
        pass
    for m in re.finditer(r"<(\w+)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</\1>", text, re.S):
        out[m.group(1)] = m.group(2).strip()
    return out


class WeComCrypto:
    """一个企业微信自建应用的加解密上下文。

    token / encoding_aes_key 来自企业微信后台「接收消息」配置；
    receive_id 就是企业的 CorpID，用于校验消息确实是发给自己的。
    """

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str = ""):
        self.token = (token or "").strip()
        self.encoding_aes_key = (encoding_aes_key or "").strip()
        self.receive_id = (receive_id or "").strip()
        if not self.token:
            raise ValueError("没填 Token")
        self.key = parse_aes_key(self.encoding_aes_key)
        self.iv = self.key[:16]

    # ---- 签名 ----

    def signature(self, timestamp, nonce, encrypt: str) -> str:
        return compute_signature(self.token, timestamp, nonce, encrypt)

    def check(self, msg_signature: str, timestamp, nonce, encrypt: str) -> bool:
        return hmac.compare_digest(self.signature(timestamp, nonce, encrypt),
                                   str(msg_signature or ""))

    def verify_url(self, msg_signature: str, timestamp, nonce, echostr: str) -> bool:
        """URL 验证。注意 echostr 是明文，原文参与签名即可。"""
        return self.check(msg_signature, timestamp, nonce, echostr)

    # ---- 解密 ----

    def decrypt(self, encrypt_b64: str) -> tuple[str, str]:
        """解出 (msg, receive_id)。"""
        try:
            raw = base64.b64decode(encrypt_b64)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"密文不是合法 base64：{e}") from e
        plain = pkcs7_unpad(aes_cbc_decrypt(self.key, self.iv, raw), 32)
        if len(plain) < 20:
            raise ValueError("解密后长度不足 20 字节，密钥大概率不对")
        content = plain[16:]                                  # 掐掉 16 字节随机数
        msg_len = struct.unpack("!I", content[:4])[0]         # 大端长度
        if msg_len < 0 or 4 + msg_len > len(content):
            raise ValueError(f"长度字段不合法：{msg_len}")
        msg = content[4:4 + msg_len].decode("utf-8", "replace")
        rid = content[4 + msg_len:].decode("utf-8", "replace")
        if self.receive_id and rid and rid != self.receive_id:
            raise ValueError(f"receiveid 不匹配（收到 {rid!r}，预期 {self.receive_id!r}）")
        return msg, rid

    def decrypt_message(self, msg_signature: str, timestamp, nonce,
                        encrypt_b64: str) -> dict:
        """签名 + 解密一条回调消息。返回 {ok, msg, fields, error}。"""
        if not self.check(msg_signature, timestamp, nonce, encrypt_b64):
            return {"ok": False, "error": "签名校验失败（Token 对不上或请求被篡改）"}
        try:
            msg, rid = self.decrypt(encrypt_b64)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"解密失败：{e}"}
        return {
            "ok": True,
            "msg": msg,
            "receive_id": rid,
            "fields": parse_xml(msg),
        }

    # ---- 加密 ----

    def encrypt(self, msg: str, timestamp=None, nonce: str = "") -> dict:
        """加密一条要回复的消息，返回可直接写回 HTTP 的 XML 及签名信息。"""
        ts = str(timestamp if timestamp is not None else int(time.time()))
        nc = str(nonce or random_nonce())
        body = msg.encode("utf-8")
        plain = os.urandom(16) + struct.pack("!I", len(body)) + body + self.receive_id.encode("utf-8")
        cipher = aes_cbc_encrypt(self.key, self.iv, pkcs7_pad(plain, 32))
        enc = base64.b64encode(cipher).decode("ascii")
        sig = self.signature(ts, nc, enc)
        return {
            "ok": True,
            "encrypt": enc,
            "signature": sig,
            "timestamp": ts,
            "nonce": nc,
            "xml": build_reply_xml(enc, sig, ts, nc),
        }


def build_reply_xml(encrypt: str, signature: str, timestamp, nonce) -> str:
    """企业微信要求被动回复的报文格式。"""
    return (
        "<xml>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )


# ============================================================================
# 四、自检：拿官方向量证明这套 AES 是对的
# ============================================================================


def selftest() -> dict:
    """跑一遍已知答案的向量，确认纯 Python AES 实现没写歪。

    包含：
      * FIPS-197 Appendix C.3 的 AES-256 单分组向量
      * NIST SP 800-38A 的 AES-256-CBC 向量
      * 企业微信协议自身的加密/解密往返
      * 签名正负例、XML 解析
    """
    checks: list[dict] = []

    def chk(name: str, got, want) -> None:
        checks.append({"name": name, "ok": got == want, "got": str(got)[:120],
                       "want": str(want)[:120]})

    # --- 1. FIPS-197 C.3 AES-256 ---
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
    chk("FIPS-197 C.3 AES-256 加密", aes_encrypt_block(pt, key).hex(), ct.hex())
    chk("FIPS-197 C.3 AES-256 解密", aes_decrypt_block(ct, key).hex(), pt.hex())

    # --- 2. NIST SP 800-38A F.2.5/6 AES-256-CBC 首块 ---
    k2 = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv2 = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    p2 = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    c2 = bytes.fromhex("f58c4c04d6e5f1ba779eabfb5f7bfbd6")
    chk("NIST SP800-38A AES-256-CBC 加密", aes_cbc_encrypt(k2, iv2, p2).hex(), c2.hex())
    chk("NIST SP800-38A AES-256-CBC 解密", aes_cbc_decrypt(k2, iv2, c2).hex(), p2.hex())

    # --- 3. 多块 CBC 往返（跨块链接别断）---
    long_pt = os.urandom(32 * 5)
    chk("多块 CBC 往返", aes_cbc_decrypt(k2, iv2, aes_cbc_encrypt(k2, iv2, long_pt)), long_pt)

    # --- 4. PKCS7 ---
    chk("PKCS7 补齐到 32 的整数倍", len(pkcs7_pad(b"abc", 32)) % 32, 0)
    chk("PKCS7 恰好在块边界补满一块", len(pkcs7_pad(b"x" * 32, 32)), 64)
    chk("PKCS7 去填充还原", pkcs7_unpad(pkcs7_pad(b"hello world", 32), 32), b"hello world")

    # --- 5. 企业微信协议往返 ---
    aes_key = random_aes_key()
    c = WeComCrypto("tok123", aes_key, "ww_corp_test")
    env = c.encrypt("<xml><Content><![CDATA[你好 工作台]]></Content></xml>", 1700000000, "9527")
    r = c.decrypt_message(env["signature"], 1700000000, "9527", env["encrypt"])
    chk("协议层加密->解签->解密", r.get("ok"), True)
    chk("协议层内容一致", (r.get("fields") or {}).get("Content"), "你好 工作台")
    chk("协议层 receive_id 回填", r.get("receive_id"), "ww_corp_test")

    # --- 6. 签名正负例 ---
    chk("签名可复现", c.signature(1, 2, "abc"), compute_signature("tok123", 1, 2, "abc"))
    chk("签名错 token 不通过", c.check("deadbeef", 1700000000, "9527", env["encrypt"]), False)
    chk("URL 校验通过", c.verify_url(c.signature(1, 2, "echo"), 1, 2, "echo"), True)

    # --- 7. 篡改密文必须被发现（CBC 无认证，靠签名兜）---
    tampered = env["encrypt"][:-4] + "AAAA"
    chk("篡改密文被签名拦下", c.decrypt_message(env["signature"], 1700000000, "9527", tampered)["ok"], False)

    # --- 8. XML 解析 ---
    x = ("<xml><ToUserName><![CDATA[ww1]]></ToUserName>"
         "<FromUserName><![CDATA[Zhangsan]]></FromUserName>"
         "<CreateTime>1348831860</CreateTime>"
         "<MsgType><![CDATA[text]]></MsgType>"
         "<Content><![CDATA[帮我记一下 交电费]]></Content>"
         "<MsgId>1234567890123456</MsgId><AgentID>1000002</AgentID></xml>")
    f = parse_xml(x)
    chk("XML 取 MsgType", f.get("MsgType"), "text")
    chk("XML 取中文 Content", f.get("Content"), "帮我记一下 交电费")
    chk("XML 取 FromUserName", f.get("FromUserName"), "Zhangsan")

    ok_all = all(c0["ok"] for c0 in checks)
    return {"ok": ok_all, "passed": sum(1 for c0 in checks if c0["ok"]),
            "total": len(checks), "checks": checks}


if __name__ == "__main__":
    res = selftest()
    for c0 in res["checks"]:
        print(("PASS " if c0["ok"] else "FAIL ") + c0["name"] +
              ("" if c0["ok"] else f"  got={c0['got']} want={c0['want']}"))
    print(f"\n{res['passed']}/{res['total']} -> {'OK' if res['ok'] else 'BROKEN'}")
    raise SystemExit(0 if res["ok"] else 1)
