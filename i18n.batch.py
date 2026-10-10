# -*- coding: utf-8 -*-
"""翻译批次工具 —— 把 i18n.pending.json 切成小批给翻译用，再把译文并回去。

为什么需要：2099 条一次性塞不进上下文，必须分批；而每批手工复制粘贴 JSON
很容易出错（引号、换行、逗号）。这里用 TSV 中转，翻译完导回来由脚本写 JSON。

用法：
    python i18n.batch.py stats                 # 看进度
    python i18n.batch.py next 250             # 取下一批待翻译（自动跳过已翻的）
    python i18n.batch.py import batch.tsv     # 并回译文（第一列原文，第二列英文）
    python i18n.batch.py show core            # 看某个前缀的条目（调试用）
"""

from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PENDING = os.path.join(BASE, "static", "i18n", "i18n.pending.json")


def load():
    if not os.path.exists(PENDING):
        raise SystemExit("找不到 " + PENDING + "，先跑 python i18n.gen.py")
    return json.load(open(PENDING, encoding="utf-8"))


def save(d):
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def stats(d):
    t = d.get("translations", {})
    done = [k for k, v in t.items() if v]
    todo = [k for k, v in t.items() if not v]
    dyn = set(d.get("dynamic", []))
    print("总计 %d   已译 %d   待译 %d   (%.1f%%)"
          % (len(t), len(done), len(todo), 100.0 * len(done) / max(1, len(t))))
    if done:
        print("最近 5 条已译：")
        for k in done[-5:]:
            print("   %s -> %s" % (k[:40], t[k][:50]))
    if todo:
        print("下一条待译：%s" % todo[0][:60])
    return 0


def next_batch(d, n, out=None):
    t = d.get("translations", {})
    todo = [k for k, v in t.items() if not v]
    batch = todo[:n]
    # TSV：第一列原文（保持原样），第二列留空给译文
    text = "".join(k.replace("\t", " ") + "\t\n" for k in batch)
    if out:
        # 让 Python 自己写文件：经 PowerShell 重定向会被写成 UTF-16，读回来像二进制
        open(out, "w", encoding="utf-8").write(text)
        print("已导出 %d 条 -> %s" % (len(batch), out))
    else:
        sys.stdout.write(text)
    return 0


def import_tsv(d, path):
    t = d.get("translations", {})
    n = 0
    skipped = 0
    with open(path, encoding="utf-8-sig") as f:
        for ln in f:
            ln = ln.rstrip("\n").rstrip("\r")
            if ln.startswith("﻿"):        # 手写/编辑器存的文件可能带 BOM
                ln = ln[1:]
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) < 2:
                skipped += 1
                continue
            zh = parts[0].rstrip()
            en = parts[1].strip()
            if not en:
                skipped += 1
                continue
            if zh in t:
                t[zh] = en
                n += 1
            else:
                skipped += 1
    save(d)
    print("导入译文 %d 条，跳过 %d 条（原文对不上或译文为空）" % (n, skipped))
    return 0


def show(d, prefix):
    t = d.get("translations", {})
    for k, v in t.items():
        if k.startswith(prefix):
            print("%s\t%s" % (k, v))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    d = load()
    if cmd == "stats":
        return stats(d)
    if cmd == "next":
        return next_batch(d, int(sys.argv[2]) if len(sys.argv) > 2 else 200,
                          sys.argv[3] if len(sys.argv) > 3 else None)
    if cmd == "import":
        return import_tsv(d, sys.argv[2])
    if cmd == "show":
        return show(d, sys.argv[2] if len(sys.argv) > 2 else "")
    print("未知命令：" + cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())