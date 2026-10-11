# -*- coding: utf-8 -*-
"""git 协议被网络挡掉时的正规退路：用 GitHub API 直接推。

⚠️ 只在 `git push` 失败（代理/网络）且 `gh` 可用时用，别当默认路径。
   它绕过 git 的传输层，所以**只推「本地领先的提交」，不处理历史重写**。

做法（GitHub Git Data API）：
  1. `git create blob`  每个文件一个 blob
  2. `git create tree`  基于远程 tree，只写改动的条目
  3. `git create commit` 挂到远程 HEAD 上
  4. `git update ref`    快进 refs/heads/main

⚠️ 必须用 fast-forward，且不能有别人推过 —— 动手前先比 sha。
"""
import base64
import json
import os
import subprocess
import sys

REPO = "ZhangZhangooo/open-workbench"
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, "workbench")


def gh(args, input_json=None):
    cmd = ["gh", "api"] + args
    if input_json is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=input_json, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "gh 失败")[:400])
    return json.loads(r.stdout) if (r.stdout or "").strip() else {}


def git(*a):
    r = subprocess.run(["git", "-C", WB] + list(a), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def main():
    verbose = "--check" not in sys.argv

    # --- 1. 本地状态 ---
    _, head, _ = git("rev-parse", "HEAD")
    _, msg, _ = git("log", "-1", "--format=%s")
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        print("当前分支不是 %s，是 %s —— 不处理" % (BRANCH, branch))
        return 1

    # --- 2. 远程状态 ---
    remote = gh(["repos/%s/commits/%s" % (REPO, BRANCH)])
    remote_sha = remote["sha"]
    print("远程 %s = %s" % (BRANCH, remote_sha[:8]))
    print("本地 %s = %s" % (BRANCH, head[:8]))

    if remote_sha == head:
        print("\n已经一致，无需推送")
        return 0

    # --- 3. 本地领先的提交必须是远程的子孙（否则是历史分叉，不能快进）---
    # ⚠️ `git merge-base --is-ancestor` 成功时 stdout/stderr 都是空的，
    #    所以只能看返回码，不能拿输出内容判断（早先写成 `if anc != ""` 是错的）。
    rc, _, _ = git("merge-base", "--is-ancestor", remote_sha, head)
    if rc != 0:
        _, mb, _ = git("merge-base", remote_sha, head)
        if not mb:
            print("\n本地没有远程那个提交 —— 历史分叉了，别用 API 硬推，"
                  "需要先处理（git pull --rebase 或人工）")
            return 1
        print("注意：%s 不是 %s 的祖先，分叉过，"
              "请先人工确认" % (head[:8], remote_sha[:8]))
        return 1

    # --- 4. 远程的 base tree ---
    rc = gh(["repos/%s/git/commits/%s" % (REPO, remote_sha)])
    base_tree = rc["tree"]["sha"]
    print("base tree = %s" % base_tree[:8])

    # --- 5. 收集改动文件 ---
    _, files, _ = git("diff", "--name-only", remote_sha, head)
    files = [f for f in files.splitlines() if f.strip()]
    # 分隔的文件名（空行）git diff 不会给，但保险起见滤一遍
    print("待推 %d 个文件" % len(files))

    # --- 6. 逐个建 blob ---
    entries = []
    for f in files:
        fp = os.path.join(WB, f)
        if not os.path.isfile(fp):
            print("  跳过（本地不存在）%s" % f)
            continue
        with open(fp, "rb") as fh:
            data = fh.read()
        b = gh(["repos/%s/git/blobs" % REPO],
               input_json=json.dumps({
                   "content": base64.b64encode(data).decode("ascii"),
                   "encoding": "base64",
               }))
        mode = "100755" if os.access(fp, os.X_OK) and os.path.splitext(f)[1] in (
            ".sh", ".bat", ".py") and not f.endswith(".bat") else "100644"
        if f.endswith(".bat") or f.endswith(".sh"):
            mode = "100755"
        entries.append({"path": f, "mode": mode, "type": "blob", "sha": b["sha"]})
        if verbose:
            print("  blob %s  %8d B  %s" % (b["sha"][:8], len(data), f))

    # --- 7. 建 tree（base_tree 之上只写改动的） ---
    t = gh(["repos/%s/git/trees" % REPO],
           input_json=json.dumps({"base_tree": base_tree, "tree": entries}))
    print("新 tree = %s" % t["sha"][:8])

    # --- 8. 建 commit ---
    c = gh(["repos/%s/git/commits" % REPO],
           input_json=json.dumps({
               "message": msg + "\n\n(pushed via GitHub API: git transport was blocked)",
               "tree": t["sha"],
               "parents": [remote_sha],
           }))
    print("新 commit = %s" % c["sha"][:8])

    # --- 9. 快进 ref（force=false，推不动就报错而不是覆盖别人的提交）---
    gh(["repos/%s/git/refs/heads/%s" % (REPO, BRANCH), "-X", "PATCH"],
       input_json=json.dumps({"sha": c["sha"], "force": False}))
    print("\n✅ 推送完成：%s -> %s" % (remote_sha[:8], c["sha"][:8]))

    # --- 10. 本地也要跟上，否则下次 git push 还会失败 ---
    # ⚠️ update-ref 成功时 stdout 是空的（不是 None），早先写成
    #    (r.stdout or "").strip() 之后再去切片是可以的，
    #    但下面这行早先误写成取 git 输出再 [8] —— git 失败时返回字符串，
    #    成功时返回 None，None 不可切片 → 'NoneType' object is not subscriptable。
    #    这里分别处理，别混。
    rc2, out2, err2 = git("update-ref", "refs/remotes/origin/" + BRANCH, c["sha"])
    if rc2 != 0:
        print("  (本地 ref 更新失败，不影响远程：%s)" % (err2 or out2)[:120])
    rc3, out3, _ = git("rev-parse", "origin/" + BRANCH)
    if out3:
        print("本地 origin/%s = %s" % (BRANCH, out3[:8]))
    print("\n（本地 HEAD 与远程 sha 不同是正常的：API 推的 commit 由 GitHub 生成，"
          "sha 不等于本地的。下次 push 前先 `git fetch`。）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:  # noqa: BLE001
        print("失败：%s" % ex)
        sys.exit(1)
