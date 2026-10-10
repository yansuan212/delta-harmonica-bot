# -*- coding: utf-8 -*-
"""
输入通道诊断工具
用途：判断自动演奏为什么在游戏里没反应
检查项：1) 本程序权限  2) 游戏进程权限(UIPI)  3) 焦点窗口  4) SendInput 是否系统级可用
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20

VK = {"Z": 0x5A, "X": 0x58, "C": 0x43, "V": 0x56,
      "B": 0x42, "N": 0x4E, "M": 0x4D, ",": 0xBC}
SCAN = {"Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F,
        "B": 0x30, "N": 0x31, "M": 0x32, ",": 0x33}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamH", wintypes.WORD), ("wParamL", wintypes.WORD))


class _U(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _U))


def _extra():
    return ctypes.pointer(ctypes.c_ulong(0))


def send(*inp):
    arr = (INPUT * len(inp))(*inp)
    return user32.SendInput(len(inp), arr, ctypes.sizeof(INPUT))


def kb_scan(code, up=False):
    f = 0x0008 | (0x0002 if up else 0)
    return INPUT(type=1, ki=KEYBDINPUT(0, code, f, 0, _extra()))


def kb_vk(code, up=False):
    f = 0x0002 if up else 0
    return INPUT(type=1, ki=KEYBDINPUT(code, 0, f, 0, _extra()))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def enum_windows():
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    out = []

    def cb(hwnd, _l):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((hwnd, buf.value, pid.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def exe_name(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "<无法访问>"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.split("\\")[-1]
        return "<?>"
    finally:
        kernel32.CloseHandle(h)


def is_elevated(pid):
    """返回 True/False/None(无法判断)。OpenProcess 被拒通常意味着对方进程权限更高"""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            elev = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(elev),
                                              ctypes.sizeof(elev), ctypes.byref(size))
            return bool(elev.value) if ok else None
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(h)


def foreground():
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return hwnd, buf.value


def main():
    print("=" * 62)
    print("输入通道诊断")
    print("=" * 62)

    admin = is_admin()
    print(f"\n[1] 本程序权限: {'管理员 ✓' if admin else '标准用户 ✗'}")

    print("\n[2] 可见窗口列表（找你的游戏，看它是否提权）")
    print(f"    {'窗口标题':<38} {'进程':<22} {'PID':<7} 权限")
    print("    " + "-" * 76)
    for hwnd, title, pid in enum_windows():
        name = exe_name(pid)
        el = is_elevated(pid)
        tag = {True: "管理员(高)", False: "标准", None: "权限更高/无法查询"}[el]
        flag = "  <<< 可能就是这个" if el and el is True else ""
        print(f"    {title[:36]:<38} {name[:20]:<22} {pid:<7} {tag}{flag}")

    hwnd, title = foreground()
    print(f"\n[3] 当前前台窗口: 「{title}」")

    print("\n[4] SendInput 通道自检（发送一个无害的按键松开事件）")
    r1 = send(kb_scan(SCAN["Z"], up=True))
    r2 = send(kb_vk(VK["Z"], up=True))
    print(f"    扫描码方式返回 {r1}    虚拟键码方式返回 {r2}   (1=成功)")

    print("\n" + "=" * 62)
    print("下一步测试：")
    print("  1. 打开记事本，用鼠标点进编辑区")
    print("  2. 回到这个窗口按回车，3 秒后会往记事本发送按键")
    print("  3. 看记事本里是否出现文字 —— 出现说明 SendInput 正常，")
    print("     问题在游戏侧；不出现说明系统层面就被拦了")
    print("=" * 62)
    input("\n按回车开始记事本测试（或 Ctrl+C 跳过）... ")

    for i in range(3, 0, -1):
        print(f"  {i} 秒后发送，请立刻点进记事本...", flush=True)
        time.sleep(1)

    for ch, vk in [("S", 0x53), ("E", 0x45), ("N", 0x4E), ("D", 0x44)]:
        send(kb_vk(vk))
        time.sleep(0.05)
        send(kb_vk(vk, up=True))
        time.sleep(0.05)
    print("\n已发送。请检查记事本里是否出现 'SEND'。")
    print("  - 出现了 → SendInput 正常，游戏不接收合成输入（多半是反作弊/底层输入）")
    print("  - 没出现 → 系统层面被拦截，检查是否有安全软件拦截，或本程序权限不足")


if __name__ == "__main__":
    main()
