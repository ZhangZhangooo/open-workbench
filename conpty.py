"""Windows 伪控制台（ConPTY）交互终端会话 —— 零第三方依赖，纯 ctypes。

只在 Windows 10 1809+ 可用。提供的接口让 server.py 像驱动一个真终端一样：
start_session() 起一个 powershell，write_input() 喂按键，read_available() 取输出，
resize() 改窗口大小。读线程把 PTY 管道的输出字节攒进缓冲区，UTF-8 解码后给前端。

如果不支持（老 Windows / 非 Windows），start_session 返回 (False, 原因)，
is_active() 恒为 False，前端据此回退到原来的非交互「运行一条命令」模式。
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
import threading
import time

try:
    import ctypes.wintypes as wt
except Exception:  # noqa: BLE001
    wt = None

AVAILABLE = False
_REASON = ""

if wt is not None:
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        HANDLE = wt.HANDLE
        DWORD = wt.DWORD
        BOOL = wt.BOOL
        SIZE_T = ctypes.c_size_t
        LPVOID = ctypes.c_void_p
        WCHAR = ctypes.c_wchar

        class COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class STARTUPINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cb", DWORD),
                ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR),
                ("dwX", DWORD), ("dwY", DWORD),
                ("dwXSize", DWORD), ("dwYSize", DWORD),
                ("dwXCountChars", DWORD), ("dwYCountChars", DWORD),
                ("dwFillAttribute", DWORD), ("dwFlags", DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE),
                ("lpAttributeList", LPVOID),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", HANDLE), ("hThread", HANDLE),
                ("dwProcessId", DWORD), ("dwThreadId", DWORD),
            ]

        HPCON = ctypes.c_void_p
        SECURITY_ATTRIBUTES = ctypes.c_void_p  # 传 NULL 即可

        k32.CreatePipe.argtypes = [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE),
                                    SECURITY_ATTRIBUTES, DWORD]
        k32.CreatePipe.restype = BOOL

        k32.CreatePseudoConsole.argtypes = [COORD, HANDLE, HANDLE, DWORD,
                                            ctypes.POINTER(HPCON)]
        k32.CreatePseudoConsole.restype = ctypes.c_long  # HRESULT

        k32.ResizePseudoConsole.argtypes = [HPCON, COORD]
        k32.ResizePseudoConsole.restype = ctypes.c_long

        k32.ClosePseudoConsole.argtypes = [HPCON]
        k32.ClosePseudoConsole.restype = None

        k32.CloseHandle.argtypes = [HANDLE]
        k32.CloseHandle.restype = BOOL

        k32.InitializeProcThreadAttributeList.argtypes = [
            LPVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)]
        k32.InitializeProcThreadAttributeList.restype = BOOL

        k32.UpdateProcThreadAttribute.argtypes = [
            LPVOID, DWORD, ctypes.c_size_t, LPVOID, SIZE_T, LPVOID, LPVOID]
        k32.UpdateProcThreadAttribute.restype = BOOL

        k32.CreateProcessW.argtypes = [
            wt.LPCWSTR, wt.LPWSTR, LPVOID, LPVOID, BOOL, DWORD,
            LPVOID, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
            ctypes.POINTER(PROCESS_INFORMATION)]
        k32.CreateProcessW.restype = BOOL

        k32.TerminateProcess.argtypes = [HANDLE, ctypes.c_uint]
        k32.TerminateProcess.restype = BOOL

        PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = ctypes.c_size_t(0x00020016)
        EXTENDED_STARTUPINFO_PRESENT = 0x00080000
        STARTF_USESTDHANDLES = 0x00000100

        AVAILABLE = True
    except Exception as e:  # noqa: BLE001
        _REASON = f"ConPTY 初始化失败：{e}"
else:
    _REASON = "非 Windows 平台，没有 ConPTY"


# ---------------- 单例会话 ----------------

_state = {
    "hpc": None,          # HPCON
    "proc": None,         # PROCESS_INFORMATION
    "in_fd": None,        # 写端 fd（喂按键）
    "out_fd": None,       # 读端 fd（取输出）
    "buf": bytearray(),   # 输出缓冲
    "lock": threading.Lock(),
    "alive": False,
    "thread": None,
}


def _reader_loop(out_fd: int):
    """读 PTY 输出管道，攒进缓冲。管道关闭/进程退出即结束。"""
    while True:
        try:
            chunk = os.read(out_fd, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            break
        with _state["lock"]:
            _state["buf"].extend(chunk)
    _state["alive"] = False


def start_session(cols: int = 120, rows: int = 30, shell: str = "powershell.exe") -> tuple[bool, str]:
    if not AVAILABLE:
        return False, _REASON or "本机不支持 ConPTY（需 Windows 10 1809+）"
    if _state["alive"]:
        return True, ""

    hInR = HANDLE(); hInW = HANDLE()
    hOutR = HANDLE(); hOutW = HANDLE()
    if not k32.CreatePipe(ctypes.byref(hInR), ctypes.byref(hInW), None, 0):
        return False, "CreatePipe 失败"
    if not k32.CreatePipe(ctypes.byref(hOutR), ctypes.byref(hOutW), None, 0):
        return False, "CreatePipe 失败"

    hpc = HPCON()
    hr = k32.CreatePseudoConsole(COORD(cols, rows), hInR, hOutW, 0, ctypes.byref(hpc))
    if hr != 0:
        return False, f"CreatePseudoConsole 失败（HRESULT {hr}）"

    # 把属性列表建好，指向伪控制台
    size = SIZE_T(0)
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attr_buf = (ctypes.c_byte * size.value)()
    attr_list = ctypes.cast(attr_buf, LPVOID)
    if not k32.InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(size)):
        return False, "InitializeProcThreadAttributeList 失败"
    if not k32.UpdateProcThreadAttribute(
            attr_list, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            hpc, ctypes.sizeof(HPCON), None, None):
        return False, "UpdateProcThreadAttribute 失败"

    si = STARTUPINFOEXW()
    si.cb = ctypes.sizeof(STARTUPINFOEXW)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput = hInW
    si.hStdOutput = hOutR
    si.hStdError = hOutR
    si.lpAttributeList = attr_list

    pi = PROCESS_INFORMATION()
    cmd = f'{shell} -NoProfile -NoExit'
    ok = k32.CreateProcessW(
        None, cmd, None, None, False,
        EXTENDED_STARTUPINFO_PRESENT, None, None,
        ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        return False, f"CreateProcessW 失败（last_error {err}）"

    # conpty 接管了 hInR / hOutW，关掉我们这边的副本；
    # 留 hInW（写按键）和 hOutR（读输出）
    k32.CloseHandle(hInR)
    k32.CloseHandle(hOutW)

    _state["hpc"] = hpc
    _state["proc"] = pi
    _state["in_fd"] = msvcrt.open_osfhandle(int(hInW.value), os.O_WRONLY | os.O_BINARY)
    _state["out_fd"] = msvcrt.open_osfhandle(int(hOutR.value), os.O_RDONLY | os.O_BINARY)
    _state["alive"] = True
    with _state["lock"]:
        _state["buf"] = bytearray()
    _state["thread"] = threading.Thread(target=_reader_loop, args=(_state["out_fd"],), daemon=True)
    _state["thread"].start()
    return True, ""


def write_input(data: str) -> tuple[bool, str]:
    if not _state["alive"] or _state["in_fd"] is None:
        return False, "终端没在运行"
    try:
        os.write(_state["in_fd"], data.encode("utf-8", "replace"))
        return True, ""
    except OSError as e:
        return False, str(e)


def read_available() -> bytes:
    """取走并清空自上次调用以来累积的输出字节。"""
    with _state["lock"]:
        b = bytes(_state["buf"])
        _state["buf"] = bytearray()
    return b


def resize(cols: int, rows: int) -> bool:
    if not _state["alive"] or not _state["hpc"]:
        return False
    try:
        k32.ResizePseudoConsole(_state["hpc"], COORD(cols, rows))
        return True
    except Exception:  # noqa: BLE001
        return False


def is_active() -> bool:
    return bool(_state["alive"])


def close_session() -> None:
    if _state["proc"]:
        try:
            k32.TerminateProcess(_state["proc"].hProcess, 0)
        except Exception:  # noqa: BLE001
            pass
    if _state["hpc"]:
        try:
            k32.ClosePseudoConsole(_state["hpc"])
        except Exception:  # noqa: BLE001
            pass
    _state["alive"] = False
