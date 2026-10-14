# -*- coding: utf-8 -*-
"""推送脚本：git 协议被网络挡掉时的正规退路。

## 为什么需要它

现象：`git push -u origin main` 报
`fatal: unable to access '...': Empty reply from server`
（代理/网络把 git 的传输层挡了），但 `gh api` 走 HTTPS API 完全正常
（gh 已认证，token scopes 里有 repo）。

所以加这个退路：用 GitHub Git Data API 直接推
（create blob → create tree → create commit → update ref），完全不碰 git 传输层。

## 用之前必须知道的三条边界

1. **只推「本地领先的提交」**，不处理历史重写。要 force 得自己改代码。
2. **必须 fast-forward**：动手前比 sha，本地不是远程的子孙就退出。
   `update ref` 用 `force=false`，推不动就报错，**绝不覆盖别人的提交**。
3. **推完本地 HEAD 与远程 sha 不同**（commit 由 GitHub 签发，sha 不等于本地的）。
   下次 push 前先 `git fetch`。

## 踩过的坑（都是"报错信息完全指不到真正原因"的）

- **`--format=%s` 在 Windows 上返回空串**：`%s` 被 cmd 当变量展开掉了。
  改用 `--pretty=format:%(subject)`（cmd 不认这种写法）。
- **仓库路径不能硬编码 `dirname(脚本所在目录)`**：这个脚本开发时在仓库外一层，
  提交后又拷进仓库根，两种位置差一层。硬编码父目录会在仓库内运行时得到
  `workbench/workbench/`（不存在），于是每个 git 命令都报
  `fatal: cannot change to '...'`，输出全空 —— 表现成「分支不对」这种莫名其妙的错。
  现在按「有没有 .git」自动判断。

实测：git 协议不通时用它成功推上 7 个文件（含 5 个 PNG 封面），
事后用 `contents` API 逐个核对文件大小全部正确。
"""
import base64
import json
import os
import subprocess
import sys

REPO = "ZhangZhangooo/open-workbench"
BRANCH = "main"

HERE = os.path.dirname(os.path.abspath(__file__))
# 按「有没有 .git」判断仓库根：脚本在仓库内或在仓库外一层都能跑
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
    # ⚠️ 取 commit message 别走 `--pretty=format:`，两个写法都是坑：
    #    - `%s`：Windows 上 git 是 .cmd 包装器，参数经 cmd 展开 → 取到空串
    #    - `%(subject)`：不是 git 合法占位符（subject 就是 %s），git 原样吐字面量
    #    （后者已导致远端落过 3 条 message 为 "%(subject)" 的脏提交）
    #    改用 `cat-file commit` 直读对象：message 在第一个空行之后，全程不含 %。
    _, raw, _ = git("cat-file", "commit", "HEAD")
    msg = raw.split("\n\n", 1)[1].strip() if "\n\n" in raw else ""
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        print("当前分支不是 %s，是 %r —— 不处理" % (BRANCH, branch))
        return 1

    remote = gh(["repos/%s/commits/%s" % (REPO, BRANCH)])
    remote_sha = remote["sha"]
    print("仓库   : %s" % WB)
    print("远程 %s = %s" % (BRANCH, remote_sha[:8]))
    print("本地 %s = %s" % (BRANCH, head[:8]))

    if remote_sha == head:
        print("\n已经一致，无需推送")
        return 0

    # 快进检查
    rc, _, _ = git("merge-base", "--is-ancestor", remote_sha, head)
    if rc != 0:
        # ⚠️ 这里会出现一种**假分叉**：之前用本脚本推过一次，commit 由 GitHub 签发，
        #    sha 跟本地不一样，本地又没有它 → merge-base 判定"不相关"。
        #    但两边的**文件内容其实完全一样**（同一份改动被签了两次）。
        #    判据：本地 HEAD 的树与远程 HEAD 的树一致 ⇒ 内容等价，直接 exit 0，
        #    否则真分叉，退出让人处理（不硬推）。
        _, ltree, _ = git("rev-parse", "HEAD^{tree}")
        rtree = gh(["repos/%s/git/commits/%s" % (REPO, remote_sha)])["tree"]["sha"]
        if ltree and ltree == rtree:
            print("\n内容已一致（本地 %s 的树 == 远程的树 %s）" % (ltree[:8], rtree[:8]))
            print("只是 commit sha 不同（API 推的由 GitHub 签发）。无需再推。")
            print("想消掉这个差异：等 git 协议恢复后跑 `git fetch`，"
                  "或直接 `git reset --hard origin/main`（前提是本地没别的提交要留）。")
            return 0
        print("\n真分叉：本地树 %s != 远程树 %s" % ((ltree or "?")[:8], rtree[:8]))
        print("不能快进，需要人工处理（git fetch + rebase，或重置）。")
        return 1

    rc0 = gh(["repos/%s/git/commits/%s" % (REPO, remote_sha)])
    base_tree = rc0["tree"]["sha"]
    print("base tree = %s" % base_tree[:8])

    _, files, _ = git("diff", "--name-only", remote_sha, head)
    files = [f for f in files.splitlines() if f.strip()]
    print("待推 %d 个文件" % len(files))

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
        # .sh / .bat 在 Windows 上没有执行位，靠扩展名强制 100755
        mode = "100755" if f.endswith((".sh", ".bat")) else "100644"
        entries.append({"path": f, "mode": mode, "type": "blob", "sha": b["sha"]})
        print("  blob %s  %8d B  %s" % (b["sha"][:8], len(data), f))

    t = gh(["repos/%s/git/trees" % REPO],
           input_json=json.dumps({"base_tree": base_tree, "tree": entries}))
    print("新 tree = %s" % t["sha"][:8])

    c = gh(["repos/%s/git/commits" % REPO],
           input_json=json.dumps({
               "message": (msg or "(no subject)") +
                           "\n\n(pushed via GitHub API: git transport was blocked)",
               "tree": t["sha"],
               "parents": [remote_sha],
           }))
    print("新 commit = %s" % c["sha"][:8])

    gh(["repos/%s/git/refs/heads/%s" % (REPO, BRANCH), "-X", "PATCH"],
       input_json=json.dumps({"sha": c["sha"], "force": False}))
    print("\n推送完成：%s -> %s" % (remote_sha[:8], c["sha"][:8]))

    rc2, _, err2 = git("update-ref", "refs/remotes/origin/" + BRANCH, c["sha"])
    if rc2 != 0:
        print("  (本地 ref 没更新，不影响远程：%s)" % (err2 or "")[:120])
    print("（本地 HEAD 与远程 sha 不同是正常的：API 推的 commit 由 GitHub 签发。"
          "下次 push 前先 git fetch。）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:  # noqa: BLE001
        print("失败：%s" % ex)
        sys.exit(1)
