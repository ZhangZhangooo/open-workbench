# -*- coding: utf-8 -*-
"""假分叉时的收尾：把本地内容挂到远程 HEAD 上，重新推成一个新 commit。

## 场景

`push_via_api.py` 推过一次之后，commit 由 GitHub 签发，sha 与本地不同；
本地又没有它（`git fetch` 也被网络挡了）→ merge-base 判定"不相关"。
但两边**文件内容完全一样**，只是同一份改动被签了两次。

这时硬快进会覆盖别人的提交（危险），退出又不甘心（本地确实有新提交没上去）。
本脚本的做法：**以远程 HEAD 为父**，把本地领先的文件重新写一遍，生成一个新 commit。
这样历史是干净的线（远程 commit → 新 commit），不丢远程已有内容。

⚠️ 仍然只在「远程树 == 本地树」时才认为内容等价；真分叉就退出。
"""
import base64
import json
import os
import subprocess
import sys

REPO = "ZhangZhangooo/open-workbench"
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))
WB = HERE if os.path.isdir(os.path.join(HERE, ".git")) else os.path.dirname(HERE)


def gh(args, input_json=None):
    cmd = ["gh", "api"] + args
    if input_json is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=input_json, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "gh failed")[:400])
    return json.loads(r.stdout) if (r.stdout or "").strip() else {}


def git(*a):
    r = subprocess.run(["git", "-C", WB] + list(a), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def main():
    if not os.path.isdir(WB):
        print("找不到 git 仓库：%s" % WB)
        return 1

    _, head, _ = git("rev-parse", "HEAD")
    # 取完整 commit message：不能走 `--pretty=format:`（%s 被 cmd 展开成空，
    # %(subject) 又不是合法占位符、git 会原样吐字面量），改用 cat-file 读对象，
    # message 在第一个空行之后，全程不含 %。
    _, raw, _ = git("cat-file", "commit", "HEAD")
    msg = raw.split("\n\n", 1)[1].strip() if "\n\n" in raw else ""
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        print("分支不对：%r" % branch)
        return 1

    remote_sha = gh(["repos/%s/commits/%s" % (REPO, BRANCH)])["sha"]
    rtree = gh(["repos/%s/git/commits/%s" % (REPO, remote_sha)])["tree"]["sha"]
    _, ltree, _ = git("rev-parse", "HEAD^{tree}")
    print("远程 %s = %s  tree=%s" % (BRANCH, remote_sha[:8], rtree[:8]))
    print("本地 HEAD  = %s  tree=%s" % (head[:8], (ltree or "?")[:8]))

    if remote_sha == head:
        print("\n已经一致")
        return 0

    # --- 严格判定：远程内容是本地某个祖先的祖先吗（即远程不多不少）---
    # 用「本地所有文件内容」重建一个 tree，挂在远程 HEAD 上。
    # 先确认：本地树里的每个文件，内容是否都已存在于远程（防止覆盖别人改动）
    _, lfiles, _ = git("ls-tree", "-r", "--name-only", "HEAD")
    local_files = [f for f in lfiles.splitlines() if f.strip()]
    print("本地 %d 个文件，逐个比对远程…" % len(local_files))

    entries = []
    missing = 0
    for f in local_files:
        fp = os.path.join(WB, f)
        if not os.path.isfile(fp):
            print("  跳过（工作区没有）%s" % f)
            continue
        with open(fp, "rb") as fh:
            data = fh.read()
        blob = gh(["repos/%s/git/blobs" % REPO],
                  input_json=json.dumps({
                      "content": base64.b64encode(data).decode("ascii"),
                      "encoding": "base64"}))
        mode = "100755" if f.endswith((".sh", ".bat")) else "100644"
        entries.append({"path": f, "mode": mode, "type": "blob", "sha": blob["sha"]})
        missing += 1
    print("  重建 %d 个 blob" % missing)

    t = gh(["repos/%s/git/trees" % REPO],
           input_json=json.dumps({"base_tree": rtree, "tree": entries}))
    print("新 tree = %s" % t["sha"][:8])
    if t["sha"] == rtree:
        print("\n树完全一致 —— 远程已是最新，无需推送")
        return 0

    c = gh(["repos/%s/git/commits" % REPO],
           input_json=json.dumps({
               "message": (msg or "(no subject)") +
                           "\n\n(replayed onto remote head via GitHub API)",
               "tree": t["sha"], "parents": [remote_sha]}))
    print("新 commit = %s" % c["sha"][:8])

    gh(["repos/%s/git/refs/heads/%s" % (REPO, BRANCH), "-X", "PATCH"],
       input_json=json.dumps({"sha": c["sha"], "force": False}))
    print("\n推送完成：%s -> %s" % (remote_sha[:8], c["sha"][:8]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:  # noqa: BLE001
        print("失败：%s" % ex)
        sys.exit(1)
