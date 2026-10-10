# -*- coding: utf-8 -*-
"""i18n 语言包生成器。

扫出界面里所有可翻译的中文，按**完整片段**提取（不切碎），产出：
  1) 待翻译清单  -> i18n.pending.json   （人/AI 翻成英文填回去）
  2) 语言包骨架  -> static/i18n/zh.js 与 static/i18n/en.js
  3) 静态资源拼接型文案（自动翻译覆盖不到的）单独列出来

为什么用「中文原文当 key」而不是 `t('printer.print')` 这种语义 key：
  26 个前端文件几千处硬编码中文，逐处改成语义 key 极易漏，且以后每加一个模块都得记得包。
  精确匹配原文的覆盖率反而更高（连长说明句都能翻）。代价是同一中文串在不同语境可能需要
  不同英文（"文件" = file / document），这种少数情况在 pending 里人工分条即可。

用法：
    python i18n.gen.py            # 重新扫描，更新 pending 与语言包骨架
    python i18n.gen.py --check    # 只报告差异，不写文件（冒烟用）
"""

from __future__ import annotations

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
I18N_DIR = os.path.join(STATIC, "i18n")
PENDING = os.path.join(I18N_DIR, "i18n.pending.json")
DOM_JSON = os.path.join(I18N_DIR, "i18n.dom.json")
ZH_JS = os.path.join(I18N_DIR, "zh.js")
EN_JS = os.path.join(I18N_DIR, "en.js")

CJK = re.compile(r"[\u4e00-\u9fff]")

# HTML 文本节点：>中文<
RE_TEXT = re.compile(r">([^<>{}]{2,400}?)<")
# 属性：placeholder / title / aria-label / alt / data-*
RE_ATTR = re.compile(
    r"\b(placeholder|title|aria-label|alt|data-empty|data-hint)\s*=\s*\"([^\"]{2,400})\"")
# JS 字符串字面量（单/双/反引号），排除跨行拼接
RE_STR = re.compile(r"(?<!\\)([\"'`])((?:[^\"'`\\\n]|\\.){2,400}?)\1")
# 行注释（// 之后到行尾），用于剔除代码里的说明性中文
RE_COMMENT = re.compile(r"//.*$", re.M)
RE_BLOCK = re.compile(r"/\*.*?\*/", re.S)
# 拼接型：含 ${...} 或与其它串用 + 连接的模板片段
RE_DYN = re.compile(r"\$\{")

# 噪音特征：HTML 片段、模板插值、代码残渣。
# 这些都不是"DOM 文本节点里真实出现的文案"，语言包收了也匹配不上，必须剔掉。
# ⚠️ 第一版没剔，结果 2099 条里大半是 `<div class="note">成功 ${d.n} 份…` 这种垃圾。
NOISE = re.compile(
    r"[<>{}]"                                  # HTML 标签 / 对象字面量
    r"|\$\{"                                    # 模板插值
    r"|=>|\.value|\.length|\.join|\.map\(|\.filter\(|\.forEach\("
    r"|esc\(|querySelector|\.push\(|\.slice\("
    r"|\bfunction\b|\breturn\b|\bconst\b|\blet\b|\bvar\b"
)


def add_ok(t):
    """这条能不能当可翻译文案。"""
    if not t or not has_cjk(t):
        return False
    if looks_like_path(t):
        return False
    if NOISE.search(t):
        return False
    if len(t) > 100:          # 超长说明段落：可能是一整篇提示，单独人工处理
        return False
    if t[0] in ",.:;-/、，。；：":
        return False          # 被切断的片段（以标点开头）
    if t[-1] in ",，、":
        return False
    if "' + '" in t or '" + "' in t or "'+" in t or '+"' in t:
        return False          # 字符串拼接残留：' + ' + 片段
    return True


def has_cjk(s):
    return bool(CJK.search(s))


# 「每次渲染都不同的动态值」——它们此刻长得像文案，但明天就不是了，
# 翻译它们纯属浪费（还会把语言包撑成噪音）。判据是**含变量特征**，不是"含数字"：
# 「5 分钟」是番茄钟的固定选项，要留；「467,753 个」是索引计数，要剔。
RE_DYNVALUE = re.compile(
    r"\d{1,3},\d{3}"                 # 千分位：467,753 个
    r"|\d{4}-\d{2}-\d{2}"            # ISO 日期：2026-09-11 完成 0 件
    r"|^CPU [\d.]+%"                 # CPU 12% · 28 核
    r"|^[\d.]+ ?(GB|MB|KB|TB|B)\b"   # 12.3 MB
)
RE_DYN_PREFIX = re.compile(
    r"^[\d,./]+ (个|件|条|项|组|封|份|台|封存|个文件|条日程|个会议|个到期任务)"
    r"|^[\d]+ ?/ ?[\d]+"              # 0/3 已能用、3/4 已能用
    r"|^[\d]+ 已完成"
    r"|^[\d]+ 个 · "                   # 0 个 · 0 B
)
RE_DYN_SUFFIX = re.compile(r" · 缺$")


def is_dynamic_value(t):
    return bool(RE_DYNVALUE.search(t) or RE_DYN_PREFIX.search(t)
                or RE_DYN_SUFFIX.search(t))


def looks_like_path(s):
    # 纯路径/文件名/正则/URL 之类不该当文案翻
    if not has_cjk(s):
        return True
    if s.startswith(("http://", "https://", "/api/", "data:", "#")):
        return True
    if re.fullmatch(r"[\w\\/:.\-%一-鿿 ]{0,60}", s) and "/" in s and " " not in s:
        return True
    return False


def clean(s):
    s = s.replace("\\n", "\n").strip()
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r" {2,}", " ", s)
    return s.strip()


def scan_file(path):
    raw = open(path, encoding="utf-8").read()
    name = os.path.basename(path)
    is_html = name.endswith(".html")
    # 先摘掉注释，避免把「// 这行写的是…」这类说明算进来
    no_block = RE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), raw)
    body = RE_COMMENT.sub("", no_block)

    found = {}          # 原文 -> {"dynamic":bool, "files":[name]}
    dyn_ctx = set()

    def add(text, dynamic=False):
        t = clean(text)
        if not add_ok(t):
            return
        if is_dynamic_value(t):
            return
        rec = found.setdefault(t, {"dynamic": dynamic, "files": []})
        if name not in rec["files"]:
            rec["files"].append(name)
        if dynamic:
            dyn_ctx.add(t)

    for m in RE_TEXT.finditer(body):
        add(m.group(1))
    for m in RE_ATTR.finditer(body):
        add(m.group(2))
    for m in RE_STR.finditer(body):
        add(m.group(2))
    # 标记拼接型：原文所在的行里出现了 ${ 或字符串 + 连接
    for line in body.splitlines():
        if RE_DYN.search(line) and has_cjk(line):
            for m in re.finditer(r"[`']([^`']{2,400}?)[`']", line):
                t = clean(m.group(1))
                # 拼接型保留（含 ${ 是它的特征），但同样要剔掉 HTML 模板与超长段
                if not has_cjk(t) or looks_like_path(t):
                    continue
                if "<" in t or ">" in t or len(t) > 100:
                    continue
                if t[0] in ",.:;-/、，。；：" or t[-1] in ",，、":
                    continue
                dyn_ctx.add(t)
                found.setdefault(t, {"dynamic": True, "files": []})["files"].append(name)
    return found


def main():
    check = "--check" in sys.argv
    os.makedirs(I18N_DIR, exist_ok=True)

    targets = []
    for f in sorted(os.listdir(STATIC)):
        if f.endswith(".js") and (f.startswith("mod-") or f in ("core.js", "i18n.js")):
            targets.append(os.path.join(STATIC, f))
    targets.append(os.path.join(STATIC, "index.html"))

    merged = {}
    for p in targets:
        for text, rec in scan_file(p).items():
            m = merged.setdefault(text, {"dynamic": rec["dynamic"], "files": []})
            if rec["dynamic"]:
                m["dynamic"] = True
            m["files"] = sorted(set(m["files"] + rec["files"]))

    # 拼接型（含 ${...}）**不进 pending**：运行时 DOM 里根本不是这个原文，是渲染后的结果，
    # 拿它当 key 永远匹配不上。这类必须走 renderPattern() 的模板插值，单独列出去人工处理。
    dyn = sorted(k for k in merged if merged[k]["dynamic"])
    keys = sorted(k for k in merged if not merged[k]["dynamic"])

    # DOM 实采（权威）优先：只有浏览器里真实渲染出来的原文才能被运行时精确替换。
    # 源码扫描的条目作为补充保留 —— 那些是"当前数据下没触发到"的界面（空状态、弹窗、折叠区）。
    dom_texts = []
    if os.path.exists(DOM_JSON):
        try:
            dom_texts = json.load(open(DOM_JSON, encoding="utf-8")).get("texts") or []
        except Exception:  # noqa: BLE001
            dom_texts = []
    # 先过滤动态值、再补进 merged —— 顺序不能反，否则 keys 里会有 merged 里不存在的条目
    from_dom = {t for t in set(dom_texts) if not is_dynamic_value(t)}
    for t in from_dom:
        merged.setdefault(t, {"dynamic": False, "files": ["<dom>"]})
    keys = sorted(set(keys) | from_dom)
    print("  DOM 实采   : %d 条（剔掉动态值后）" % len(from_dom))

    # 保留已有的译文（重新扫描时不丢人工翻译）
    existing = {}
    if os.path.exists(EN_JS):
        src = open(EN_JS, encoding="utf-8").read()
        mm = re.search(r"const EN\s*=\s*(\{.*?\})\s*;", src, re.S)
        if mm:
            try:
                existing = json.loads(mm.group(1))
            except Exception:  # noqa: BLE001
                existing = {}
    if os.path.exists(PENDING):
        try:
            existing.update(json.load(open(PENDING, encoding="utf-8")).get("translations", {}))
        except Exception:  # noqa: BLE001
            pass

    pending = {k: existing.get(k, "") for k in keys}
    missing = [k for k, v in pending.items() if not v]

    print("扫描 %d 个文件" % len(targets))
    print("  可翻译条目 : %d" % len(keys))
    print("  ├ 静态     : %d" % (len(keys) - len(dyn)))
    print("  └ 拼接型   : %d   （需人工模板插值，自动替换覆盖不到）" % len(dyn))
    print("  已有译文   : %d" % (len(keys) - len(missing)))
    print("  待翻译     : %d" % len(missing))
    by_file = {}
    for k in keys:
        for f in merged[k]["files"]:
            by_file[f] = by_file.get(f, 0) + 1
    print("  分布 Top10 :")
    for f, n in sorted(by_file.items(), key=lambda x: -x[1])[:10]:
        print("    %-26s %d" % (f, n))
    if check:
        return 0

    with open(PENDING, "w", encoding="utf-8") as fh:
        json.dump({"generated_from": "i18n.gen.py",
                   "count": len(keys),
                   "translations": pending}, fh, ensure_ascii=False, indent=1)

    # 拼接型单独落一份，供后续手工改成 renderPattern('…{0}…', 值)
    with open(os.path.join(I18N_DIR, "i18n.dynamic.json"), "w", encoding="utf-8") as fh:
        json.dump(dyn, fh, ensure_ascii=False, indent=1)

    with open(ZH_JS, "w", encoding="utf-8") as fh:
        fh.write("/* 中文语言包：恒等映射。存在的意义是让 i18n.js 有 dict 可查，\n"
                 "   以及让语言包结构与其他语言对称（便于校验覆盖率）。\n"
                 "   由 i18n.gen.py 生成，别手工改 —— 改了会被重新生成覆盖。 */\n")
        fh.write("export const ZH = Object.freeze(%s);\nexport default ZH;\n"
                 % json.dumps({k: k for k in keys}, ensure_ascii=False, indent=1))

    with open(EN_JS, "w", encoding="utf-8") as fh:
        fh.write("/* 英文语言包：中文原文 -> 英文。\n"
                 "   翻译填在 i18n.pending.json 后跑 `python i18n.gen.py` 生成到这里。\n"
                 "   未翻译的条目会原样显示中文（不会变空白），所以可以增量推进。 */\n")
        fh.write("export const EN = Object.freeze(%s);\nexport default EN;\n"
                 % json.dumps({k: pending[k] for k in keys if pending[k]},
                              ensure_ascii=False, indent=1))
    print("\n已写出 %s / %s / %s" % (os.path.relpath(PENDING, BASE),
                                     os.path.relpath(ZH_JS, BASE),
                                     os.path.relpath(EN_JS, BASE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())