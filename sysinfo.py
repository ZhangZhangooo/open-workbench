"""系统信息：内存、磁盘、CPU、进程。零依赖，ctypes + tasklist。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
import time


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


def _ull(ft: FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def mem() -> dict:
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return {
        "total": st.ullTotalPhys,
        "avail": st.ullAvailPhys,
        "used": st.ullTotalPhys - st.ullAvailPhys,
        "load": st.dwMemoryLoad,
    }


def disks(roots: list[str]) -> list[dict]:
    free = ctypes.c_ulonglong()
    total = ctypes.c_ulonglong()
    tfree = ctypes.c_ulonglong()
    out = []
    for r in roots:
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(r), ctypes.byref(free), ctypes.byref(total), ctypes.byref(tfree)
        )
        if ok and total.value:
            out.append({
                "root": r,
                "total": total.value,
                "free": free.value,
                "used": total.value - free.value,
            })
    return out


def cpu(sample: float = 0.35) -> int:
    idle, kern, user = FILETIME(), FILETIME(), FILETIME()

    def read():
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)
        )
        return _ull(idle), _ull(kern), _ull(user)

    i0, k0, u0 = read()
    time.sleep(sample)
    i1, k1, u1 = read()
    total = (k1 - k0) + (u1 - u0)
    if total <= 0:
        return 0
    return max(0, min(100, int((total - (i1 - i0)) * 100 / total)))


def procs(top: int = 40) -> list[dict]:
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15, errors="replace",
        )
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for line in r.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 5:
            continue
        raw = parts[4].replace(",", "").replace(".", "").replace(" K", "").strip()
        try:
            kb = int(raw)
        except ValueError:
            continue
        rows.append({"name": parts[0], "pid": parts[1], "mem": kb * 1024})
    rows.sort(key=lambda x: x["mem"], reverse=True)
    return rows[:top]
