"""工作台服务守护进程：拉起 server.py，崩了就立刻重启，保证页面一直打得开。

用法：
    python guard.py [端口]      # 默认 8777
后台常驻即可。想停就结束这个进程（它会顺手杀掉子进程 server.py）。

为什么需要它：之前工作台"突然啥都没了"，根因是服务进程被环境回收 /
睡眠 / 关终端干掉，而不是代码崩。这个守护进程只负责一件事——让 server.py
始终活着；它自己崩了也没关系，重新跑一次就行。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = sys.argv[1] if len(sys.argv) > 1 else "8777"

# 日志写到 data/guard.log，便于排查守护进程本身有没有问题
LOG = os.path.join(BASE, "data", "guard.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line, end="")


def main() -> None:
    log(f"守护启动，端口 {PORT}，目标 {os.path.join(BASE, 'server.py')}")
    restarts = 0
    while True:
        try:
            proc = subprocess.Popen(
                [sys.executable, os.path.join(BASE, "server.py"), PORT],
                cwd=BASE,
            )
        except Exception as e:  # noqa: BLE001
            log(f"启动失败：{e}")
            time.sleep(3)
            continue

        log(f"server.py 已拉起 (pid={proc.pid})")
        rc = proc.wait()
        restarts += 1
        log(f"server.py 退出 code={rc}，第 {restarts} 次重启（3 秒后）")
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("守护被手动结束")
