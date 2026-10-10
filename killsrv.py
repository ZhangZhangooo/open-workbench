# -*- coding: utf-8 -*-
"""清掉所有 workbench 相关的 server.py / guard.py 进程。

为什么需要它（不是"taskkill 端口"能解决的）：
  * Windows 的 SO_REUSEADDR 允许两个进程同时绑 8777，新实例不报错但请求仍被旧实例应答，
    症状是"改了配置像没改"。
  * **guard.py 不监听端口**，所以只按 netstat 杀是杀不到它的 —— 双击两次启动脚本后，
    上一只 guard 还在，就会把旧版本重新拉起来（踩过：Downloads 里那份旧 guard 一直
    保活着 2026-10-08 的代码，害得新功能看不到）。
  * 也不能 `taskkill /IM python.exe` —— 会把 OpenClaw Gateway 一起杀掉。

所以这里按 **命令行**匹配：既要含 server.py/guard.py，又要是 workbench 目录的。
用法：python killsrv.py [--dry]     --dry 只列不杀
"""

from __future__ import annotations

import subprocess
import sys

PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match '(server|guard)\.py' -and
    $_.CommandLine -match 'workbench|open-workbench'
  } |
  ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }
"""


def targets():
    out = []
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                           capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        return out
    for line in (p.stdout or b"").decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        pid, _, cmd = line.partition("\t")
        if pid.strip().isdigit():
            out.append((int(pid.strip()), cmd.strip()))
    return out


def main():
    dry = "--dry" in sys.argv
    me = None
    try:
        import ctypes
        me = ctypes.windll.kernel32.GetCurrentProcessId()
    except Exception:  # noqa: BLE001
        pass
    found = targets()
    if not found:
        print("[ok] 没有残留的 workbench 进程")
        return 0
    killed = 0
    for pid, cmd in found:
        if me and pid == me:
            continue
        short = cmd if len(cmd) < 96 else cmd[:93] + "..."
        if dry:
            print("  [dry] %d  %s" % (pid, short))
            continue
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            print("  killed %d  %s" % (pid, short))
            killed += 1
        except Exception as exc:  # noqa: BLE001
            print("  [warn] %d 杀不掉：%s" % (pid, exc))
    print("[done] 共处理 %d 个（杀掉 %d 个）" % (len(found), killed))
    return 0


if __name__ == "__main__":
    sys.exit(main())