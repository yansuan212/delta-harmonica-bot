# -*- coding: utf-8 -*-
"""
口琴小游戏 · 自动演奏器 (Windows)

键位映射：Z X C V B N M ,  = do re mi fa sol la si do'（从低到高）
音高修饰：按住鼠标左键=降八度   中键=升半音   右键=升八度   松开=原音

实现要点：
1. 用 SendInput 发送扫描码按键（比虚拟键码更兼容游戏）
2. 每个音符 = 「鼠标修饰键按住 + 键盘按住 → 保持 → 全部松开」
3. 播放放在子线程，主线程跑 GUI，支持随时停止/暂停
4. 全局热键（GetAsyncKeyState 轮询）：ESC 停止 / F5 暂停 / F6 重播 / F7 开始停止
5. 循环模式：不循环 / 单曲循环 / 顺序循环 / 随机循环，可设循环间隔
"""
import ctypes
import time
import threading
import random
import re
import sys
import os
import json
import shutil
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


# ============ 程序目录 ============
def app_dir():
    """取「程序所在目录」，兼容源码运行与 PyInstaller 打包两种情况。

    打包成 exe 后 __file__ 会指向 PyInstaller 的临时解包目录，若拿它当数据目录，
    用户改的曲库 / 绑的热键会写进临时目录，程序一关就丢。所以冻结状态改用
    sys.executable（即 exe 自身的路径），数据文件就落在 exe 旁边。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ============ Windows 输入模拟 ============
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040

VK_ESCAPE, VK_F5, VK_F6 = 0x1B, 0x74, 0x75


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


class _INPUTunion(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTunion))


def _extra():
    return ctypes.pointer(ctypes.c_ulong(0))


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    return ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def kb(scan, up=False):
    """键盘按下/松开（扫描码方式）"""
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, _extra()))


def mouse_event(flag):
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flag, 0, _extra()))


def key_state(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def foreground_title():
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def ensure_admin():
    """非管理员时用 UAC 提权重启自身。游戏若以管理员运行，本程序必须同为管理员，
    否则 Windows 的 UIPI 会直接丢弃我们发出的所有输入"""
    if is_admin():
        return True
    params = " ".join(f'"{a}"' for a in sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    return rc <= 32                      # 返回值 >32 表示成功启动了提权进程


# ============ 键位与音高映射 ============
# 扫描码 Set1
SCAN = {"Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F,
        "B": 0x30, "N": 0x31, "M": 0x32, ",": 0x33}
VK = {"Z": 0x5A, "X": 0x58, "C": 0x43, "V": 0x56,
      "B": 0x42, "N": 0x4E, "M": 0x4D, ",": 0xBC}
KEY_ORDER = ["Z", "X", "C", "V", "B", "N", "M", ","]

SEND_MODE = "scan"          # scan=扫描码（兼容多数游戏）  vk=虚拟键码


def kb_vk(code, up=False):
    """虚拟键码方式（部分游戏只认这个）"""
    flags = KEYEVENTF_KEYUP if up else 0
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(code, 0, flags, 0, _extra()))


def key_press(k, up=False):
    return kb(SCAN[k], up) if SEND_MODE == "scan" else kb_vk(VK[k], up)

# 自然音 pitch class -> 键序号（Z..M），第 8 键 "," 单独处理为高音 do
NATURAL_PC = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}
MOD_MOUSE = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
             "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
             "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)}

SEMI_OF = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_to_midi(name):
    """音名 -> MIDI 音高，如 C4->60, F#5->66, Bb4->70"""
    m = re.match(r"^([A-G])([#b]?)(-?\d)$", name.strip())
    if not m:
        raise ValueError(f"音名格式错误: {name}")
    base = SEMI_OF[m.group(1)]
    acc = {"": 0, "#": 1, "b": -1}[m.group(2)]
    return (int(m.group(3)) + 1) * 12 + base + acc


def map_note(midi):
    """MIDI 音高 -> (键名, 鼠标修饰列表)
    无修饰时 Z..M 覆盖 C4~B4，"," 为 C5；超出则叠加八度/半音修饰"""
    pc, octv = midi % 12, midi // 12 - 1
    sharp = pc not in NATURAL_PC
    key_idx = NATURAL_PC[pc - 1] if sharp else NATURAL_PC[pc]
    mods = ["middle"] if sharp else []

    if octv == 4:                                   # C4~B4：本音区
        pass
    elif octv == 3:                                 # C3~B3：左键降八度
        mods.append("left")
    elif octv == 5:
        if pc == 0 and not sharp:
            key_idx = 7                             # C5 正好用 "," 键
        else:
            mods.append("right")                    # C#5~B5：右键升八度
    elif octv == 6 and pc == 0:
        key_idx, _ = 7, mods.append("right")        # C6 = "," + 右键
    elif octv >= 6:
        mods.append("right")
    elif octv < 3:
        mods.append("left")
    return KEY_ORDER[key_idx], mods


# ============ 曲库 ============
# 真正使用的曲库在本文件同目录的 songs.json（首次运行自动生成）。
# 下面这些是内置初始曲目；之后增删曲目直接改 songs.json，或在界面上点「新增/编辑」。
BUILTIN_SONGS = {
    "欢乐颂 (贝多芬)": dict(bpm=110, notes=[
        ("E4", 1), ("E4", 1), ("F4", 1), ("G4", 1), ("G4", 1), ("F4", 1), ("E4", 1), ("D4", 1),
        ("C4", 1), ("C4", 1), ("D4", 1), ("E4", 1), ("E4", 1.5), ("D4", .5), ("D4", 2),
        ("E4", 1), ("E4", 1), ("F4", 1), ("G4", 1), ("G4", 1), ("F4", 1), ("E4", 1), ("D4", 1),
        ("C4", 1), ("C4", 1), ("D4", 1), ("E4", 1), ("D4", 1.5), ("C4", .5), ("C4", 2),
    ]),
    "小星星": dict(bpm=100, notes=[
        ("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2),
        ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2),
        ("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2),
        ("G4", 1), ("G4", 1), ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 2),
        ("C4", 1), ("C4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("A4", 1), ("G4", 2),
        ("F4", 1), ("F4", 1), ("E4", 1), ("E4", 1), ("D4", 1), ("D4", 1), ("C4", 2),
    ]),
    "生日快乐": dict(bpm=104, notes=[
        ("G4", .75), ("G4", .25), ("A4", 1), ("G4", 1), ("C5", 1), ("B4", 2),
        ("G4", .75), ("G4", .25), ("A4", 1), ("G4", 1), ("D5", 1), ("C5", 2),
        ("G4", .75), ("G4", .25), ("G5", 1), ("E5", 1), ("C5", 1), ("B4", 1), ("A4", 2),
        ("F5", .75), ("F5", .25), ("E5", 1), ("C5", 1), ("D5", 1), ("C5", 3),
    ]),
    "卡农 (帕海贝尔)": dict(bpm=96, notes=[
        ("F#5", 1), ("E5", 1), ("D5", 1), ("C#5", 1), ("B4", 1), ("A4", 1), ("B4", 1), ("C#5", 1),
        ("D5", 1), ("F#5", 1), ("A5", 1), ("G5", 1), ("F#5", 1), ("D5", 1), ("F#5", 1), ("E5", 1),
        ("D5", 1), ("B4", 1), ("G4", 1), ("A4", 1), ("B4", 1), ("C#5", 1), ("D5", 2),
        ("D5", 1), ("C#5", 1), ("B4", 1), ("A4", 1), ("G4", 1), ("F#4", 1), ("G4", 1), ("A4", 1),
        ("B4", 1), ("C#5", 1), ("D5", 1), ("E5", 1), ("F#5", 2),
    ]),
    "天空之城 (久石让)": dict(bpm=88, notes=[
        ("A4", 1), ("B4", 1), ("C5", 1.5), ("B4", .5), ("C5", 1), ("E5", 1), ("B4", 2),
        ("A4", 1), ("E4", 1), ("A4", 1.5), ("B4", .5), ("C5", 1), ("B4", 1), ("A4", 2),
        ("C5", 1), ("E5", 1), ("A5", 1.5), ("G5", .5), ("E5", 1), ("C5", 1), ("B4", 2),
        ("A4", 1), ("B4", 1), ("C5", 1.5), ("B4", .5), ("C5", 1), ("E5", 1), ("B4", 2),
    ]),
    "致爱丽丝 (贝多芬)": dict(bpm=92, notes=[
        ("E5", .5), ("D#5", .5), ("E5", .5), ("D#5", .5), ("E5", .5), ("B4", .5), ("D5", .5), ("C5", .5),
        ("A4", 1.5), ("R", .5), ("C4", .5), ("E4", .5), ("A4", .5), ("B4", 1.5), ("R", .5),
        ("E4", .5), ("G#4", .5), ("B4", .5), ("C5", 1.5), ("R", .5), ("E4", .5),
        ("E5", .5), ("D#5", .5), ("E5", .5), ("D#5", .5), ("E5", .5), ("B4", .5), ("D5", .5), ("C5", .5),
        ("A4", 1.5), ("R", .5), ("C4", .5), ("E4", .5), ("A4", .5), ("B4", 1.5), ("R", .5),
        ("E4", .5), ("C5", .5), ("B4", .5), ("A4", 2),
    ]),
}


# ============ 简谱解析 ============
# 1~7 音级，0 休止
#   高八度：5'  5*  ^5（可叠加，如 5'' 高两个八度）
#   低八度：5,  v5  （可叠加）
#   升降号：#5 升半音，b5 降半音
#   减时线：_5 或 5_ 为八分音符，__5 为十六分
#   增时线：5- 加一拍，5-- 加两拍（中间可空格：5 - -）
#   附点：  5. 时值 ×1.5
#   小节线 | 、空格、换行、歌词汉字一律忽略
MAJOR_STEPS = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_name(midi):
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


# 括号八度语义：默认 ()=低八度、[]=高八度；{ } 与 【 】默认无效。
# 各曲目若有自己的标注（以图片标注为准），用 octave_map 覆盖，例如：
#   《国际歌》 "【】 高音"      -> 默认即可（【】在默认映射里是 0，需显式给 +1）
#   《得吃》   "【】 降调 {} 升调" -> {"(": -1, "[": 1, "【": -1, "】": -1,
#                                     "{": 1, "}": 1, "（": -1, "）": -1}
DEFAULT_OCTAVE_MAP = {
    "(": -1, ")": -1, "（": -1, "）": -1,
    "[": +1, "]": +1,
    "【": 0, "】": 0,
    "{": 0, "}": 0,
    "｛": 0, "｝": 0,
}

# 成对括号：闭合符号（右括号）只负责"结束"该括号作用域，不重复计一次八度
_CLOSERS = set(")]}】｝）")
_OPENERS = set("([{【｛（")


def parse_jianpu(text, tonic="C4", octave_map=None):
    """简谱文本 -> [["音名", 拍数], ...]，休止符记 "R"
    tonic 指定「1 = 哪个音」，如 1=C4 则 1→C4、5→G4

    时值记号（兼容 jianpu.space 的写法）：
      5      四分音符 = 1 拍
      5_     八分 = 1/2 拍        5=   十六分 = 1/4 拍
      5-     横杠每根 +1 拍（5-- = 3 拍，5--- = 4 拍）
      -_ -=  延音组，+1/2、+1/4 拍，追加到前一个音上
      5.     附点，时值 ×1.5

    八度记号：
      ( ) 低八度   [ ] 高八度   { } / 【 】 由 octave_map 决定（默认不影响）
      **括号是"作用域"语义**：( 1 2 3 ) 表示括号里所有音整体降八度，
      { 6 5 3 5 3 } 同理，直到对应的右括号才结束。
      5'  高八度点   5,  低八度点   ^5/*5 前缀升八度   v5 前缀降八度
      # 只作用于紧跟其后的那一个音，不延续到后面的音

    octave_map: 括号 -> 八度偏移的映射，缺省用 DEFAULT_OCTAVE_MAP。
                左括号开始作用域、右括号结束，可嵌套。
    """
    omap = DEFAULT_OCTAVE_MAP if octave_map is None else octave_map
    base = note_to_midi(tonic)
    notes, i, n = [], 0, len(text)
    pre_oct, under, acc = 0, 0, 0
    scope = 0                                       # 括号作用域累计的八度偏移
    brackets = []                                   # 未闭合括号的偏移栈
    dotted = False                                  # 附点只对紧跟在后的一个音生效
    while i < n:
        ch = text[i]
        if ch == "*" or ch in " \t\r\n|":
            i += 1
            continue
        if ch in _CLOSERS:                          # 右括号：结束作用域
            scope -= brackets.pop() if brackets else 0
            i += 1
            continue
        if ch in _OPENERS:                          # 左括号：开始作用域
            delta = omap.get(ch, 0)
            brackets.append(delta)
            scope += delta
            i += 1
            continue
        if ch in "*^":                              # 前缀升八度
            pre_oct += 1; i += 1; continue
        if ch in "vV":                              # 前缀降八度
            pre_oct -= 1; i += 1; continue
        if ch == "_":                               # 前缀减时线
            under += 1; i += 1; continue
        if ch == "#":
            acc += 1; i += 1; continue
        if ch in "bB" and i + 1 < n and text[i + 1].isdigit():
            acc -= 1; i += 1; continue
        if ch in ".。·":                            # 附点：作用于上一个音
            if notes and not dotted:
                notes[-1][1] = round(notes[-1][1] * 1.5, 4)
                dotted = True
            i += 1; continue
        if ch in "-－—~":                           # 增时 / 延音：追加给上一个音
            add, j = 1.0, i + 1
            if j < n and text[j] == "_":
                add, j = 0.5, j + 1
            elif j < n and text[j] == "=":
                add, j = 0.25, j + 1
            if notes:
                notes[-1][1] = round(notes[-1][1] + add, 4)
            i = j; continue
        if ch in "01234567":
            deg = int(ch)
            j = i + 1
            if j < n and text[j] == "=" and j + 1 < n and text[j + 1] in "ABCDEFGabcdefg":
                j += 1                              # 1=C / 1=F# 调号声明，整段跳过
                while j < n and (text[j].isalnum() or text[j] in "#b"):
                    j += 1
                i = j
                pre_oct, under, acc = 0, 0, 0
                continue
            octv = pre_oct + scope
            while j < n and text[j] in "'’´`":      # 高八度点
                octv += 1; j += 1
            while j < n and text[j] in ",，":        # 低八度点
                octv -= 1; j += 1
            u = under
            while j < n and text[j] in "_=":         # 减时线：_ 八分、= 十六分
                u += 1 if text[j] == "_" else 2
                j += 1
            dur = 1.0 / (2.0 ** u)
            if deg == 0:
                notes.append(["R", round(dur, 4)])
            else:
                midi = base + MAJOR_STEPS[deg] + 12 * octv + acc
                notes.append([midi_to_name(midi), round(dur, 4)])
            i = j
            pre_oct, under, acc, dotted = 0, 0, 0, False
            continue
        i += 1                                      # 歌词等其它字符忽略
    return notes


def encode_dur(dur):
    """把拍数编码成简谱时值记号，**保证能被 parse_jianpu 原样读回**。

    记号规则（必须和 parse_jianpu 的读取顺序严格对应）：
        数字后面先跟若干 `_`（每根减半，故 n 根 = 1/2ⁿ 拍），
        再跟 `.`（附点 ×1.5，作用于当前音），
        最后跟增时线：`-` 加 1 拍，`-_` 加 0.5 拍。
    顺序不能颠倒 —— 写成 `._` 的话解析器会把 `.` 先消费掉，
    那个 `_` 就变成下一个音的前缀，时值全乱（旧版就是这个 bug）。

    返回 (记号, 实际拍数)；无法精确表示时返回最接近的 1/4 拍网格值。
    """
    dur = round(float(dur), 6)
    best = None
    for u in range(0, 5):                            # "_" 的根数 -> 1/2^u 拍
        head = 1.0 / (2 ** u)
        for dot in (0, 1):
            h = head * (1.5 if dot else 1.0)
            extra = round((dur - h) * 2) / 2.0        # 只能是 0.5 的整数倍
            if extra < 0 or abs((dur - h) * 2 - round((dur - h) * 2)) > 1e-6:
                continue
            k = int(round(extra / 0.5))
            cand = "_" * u + "." * dot + "-" * (k // 2) + ("-_" if k % 2 else "")
            if best is None or len(cand) < len(best[0]):
                best = (cand, h + k * 0.5)
    if best is not None:
        return best
    approx = round(dur * 4) / 4.0                     # 三元连音之类：退回 1/4 拍网格
    if abs(approx - dur) < 1e-9:
        return ("", dur)
    return encode_dur(approx) if approx > 0 else ("", dur)


# ============ 外部曲库 songs.json ============
SONGS_FILE = os.path.join(app_dir(), "songs.json")


def _song_from_item(item):
    """把 JSON 里的一条记录规范化成 {bpm, notes, jianpu, tonic, category}
    可选字段 octave_map：该曲目自己的括号八度语义（以谱面标注为准）
    可选字段 category  ：曲库分类（自由文本，为空表示"未分类"）"""
    bpm = float(item.get("bpm", 100))
    category = str(item.get("category") or "").strip()
    if item.get("jianpu"):
        tonic = item.get("tonic", "C4")
        omap = item.get("octave_map")
        if omap:                                    # JSON 键是字符串，值转 int
            omap = {k: int(v) for k, v in omap.items()}
        return dict(bpm=bpm, notes=parse_jianpu(item["jianpu"], tonic, omap),
                    jianpu=item["jianpu"], tonic=tonic, octave_map=omap,
                    category=category)
    notes = [[str(nm), float(d)] for nm, d in item.get("notes", [])]
    return dict(bpm=bpm, notes=notes, jianpu=None, tonic=None, octave_map=None,
                category=category)


def save_songs(songs=None):
    """把当前曲库写回 songs.json。手写序列化是为了让一个音符占一行，方便直接编辑

    写之前先把原文件另存一份 songs.json.bak —— 万一改错了、或者曲库被别的东西
    覆盖过，还能从 .bak 里捞回来。
    """
    songs = SONGS if songs is None else songs
    if os.path.exists(SONGS_FILE):                   # 备份上一版，防误覆盖
        try:
            shutil.copy2(SONGS_FILE, SONGS_FILE + ".bak")
        except Exception as e:
            print(f"[警告] 备份 songs.json 失败：{e}")
    blocks = []
    for name, s in songs.items():
        head = [f'  {json.dumps(name, ensure_ascii=False)}: {{',
                f'    "bpm": {s["bpm"]:g},']
        if s.get("category"):                        # 分类：方便界面上按类筛选
            head.append(f'    "category": {json.dumps(s["category"], ensure_ascii=False)},')
        if s.get("jianpu"):                          # 有简谱就存简谱，方便直接改
            head.append(f'    "tonic": {json.dumps(s.get("tonic", "C4"), ensure_ascii=False)},')
            if s.get("octave_map"):                  # 谱面有特殊括号标注时一并存下
                head.append('    "octave_map": ' + json.dumps(s["octave_map"], ensure_ascii=False) + ',')
            head.append('    "jianpu": ' + json.dumps(s["jianpu"], ensure_ascii=False))
        else:
            head.append('    "notes": [')
            head.append(",\n".join(f'      [{json.dumps(nm, ensure_ascii=False)}, {dur:g}]'
                                   for nm, dur in s["notes"]))
            head.append('    ]')
        blocks.append("\n".join(head) + "\n  }")
    text = "{\n" + ",\n".join(blocks) + "\n}\n"
    with open(SONGS_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def load_songs():
    """读 songs.json；文件不存在就先用内置曲目生成一份"""
    if not os.path.exists(SONGS_FILE):
        save_songs(BUILTIN_SONGS)
        return {k: dict(v, jianpu=None, tonic=None, octave_map=None, category="") for k, v in BUILTIN_SONGS.items()}
    try:
        with open(SONGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[警告] songs.json 读取失败（{e}），改用内置曲库")
        return {k: dict(v, jianpu=None, tonic=None, octave_map=None, category="") for k, v in BUILTIN_SONGS.items()}
    songs = {}
    for name, item in data.items():
        try:
            songs[name] = _song_from_item(item)
        except Exception as e:
            print(f"[警告] 跳过曲目《{name}》：{e}")
    if not songs:
        songs = {k: dict(v, jianpu=None, tonic=None, octave_map=None, category="") for k, v in BUILTIN_SONGS.items()}
    return songs


def reload_songs():
    """重新加载曲库（改完 songs.json 后调用即可）"""
    SONGS.clear()
    SONGS.update(load_songs())
    return SONGS


def song_category(song):
    """取一首曲子的分类，空值统一显示为「未分类」"""
    return (song or {}).get("category") or UNCATEGORIZED


def all_categories(songs=None):
    """返回 [(分类名, 曲目数), ...]
    排序：先按 CATEGORY_PRESETS 的顺序，再排自定义分类（字典序），未分类永远在最后。
    """
    songs = SONGS if songs is None else songs
    counts = {}
    for s in songs.values():
        c = song_category(s)
        counts[c] = counts.get(c, 0) + 1
    order = {c: i for i, c in enumerate(CATEGORY_PRESETS)}
    others = sorted(c for c in counts
                    if c not in order and c != UNCATEGORIZED)
    names = [c for c in CATEGORY_PRESETS if c in counts] + others
    if UNCATEGORIZED in counts:
        names.append(UNCATEGORIZED)
    return [(c, counts[c]) for c in names]


def songs_in_category(cat=None, songs=None):
    """按分类过滤曲名列表；cat 为空 / 等于 ALL_CATEGORIES 时返回全部。
    同一分类内按字典序排，保证列表稳定、好找。
    """
    songs = SONGS if songs is None else songs
    if not cat or cat == ALL_CATEGORIES:
        return list(songs)
    return sorted(n for n, s in songs.items() if song_category(s) == cat)


def rename_category(old, new, songs=None):
    """把某个分类整体改名（批量更新该分类下所有曲目）；new 为空则清空成未分类。
    返回被改动的曲目数。
    """
    songs = SONGS if songs is None else songs
    new = (new or "").strip()
    if new == UNCATEGORIZED:
        new = ""
    n = 0
    for s in songs.values():
        if song_category(s) == old:
            s["category"] = new
            n += 1
    return n


SONGS = {}
reload_songs()


# ============ 播放器 ============
class Player(threading.Thread):
    def __init__(self, song_name, bpm_scale, on_status, on_done):
        super().__init__(daemon=True)
        self.name = song_name                  # 循环时要知道当前播的是哪首
        self.song = SONGS[song_name]
        self.bpm = self.song["bpm"] * bpm_scale
        self.beat = 60.0 / self.bpm
        self.on_status = on_status
        self.on_done = on_done
        self.stop_ev = threading.Event()
        self.pause_ev = threading.Event()
        self.finished = False                  # True = 自然播完（False = 被中途停止）

    def release_all(self):
        """紧急松开所有键，避免卡键"""
        for k in KEY_ORDER:
            _send(key_press(k, up=True))
        for down, up in MOD_MOUSE.values():
            _send(mouse_event(up))

    def wait(self, sec):
        """可中断的等待"""
        end = time.time() + sec
        while not self.stop_ev.is_set():
            if time.time() >= end:
                return
            time.sleep(min(0.01, max(0, end - time.time())))

    def run(self):
        try:
            notes = self.song["notes"]
            total = len(notes)
            for i, (name, dur) in enumerate(notes):
                if self.stop_ev.is_set():
                    break
                while self.pause_ev.is_set() and not self.stop_ev.is_set():
                    time.sleep(0.05)
                secs = dur * self.beat
                if name == "R":                       # 休止符
                    self.on_status(f"休止   {i+1}/{total}")
                    self.wait(secs)
                    continue

                midi = note_to_midi(name)
                key, mods = map_note(midi)
                self.on_status(f"{name}  →  按键 {key}" + (f" + {'+'.join(mods)}" if mods else "")
                               + f"   {i+1}/{total}")

                for m in mods:                        # 先按住音高修饰键
                    _send(mouse_event(MOD_MOUSE[m][0]))
                _send(key_press(key))                 # 再按下琴键
                self.wait(max(0.05, secs * 0.92))     # 保持（留一点吐音间隙）
                _send(key_press(key, up=True))
                for m in mods:
                    _send(mouse_event(MOD_MOUSE[m][1]))
                self.wait(max(0.02, secs * 0.08))     # 音符间断开
            else:
                self.finished = True                  # for 走完（没 break）= 自然播完
        finally:
            self.release_all()
            self.on_done(self.finished)


# ============ 配置与全局热键 ============
CONFIG_FILE = os.path.join(app_dir(), "config.json")

DEFAULT_CONFIG = {
    "hotkeys": {"start_stop": "F7", "stop": "Escape", "pause": "F5", "replay": "F6"},
    "send_mode": "scan",
    "speed": 1.0,
    "countdown": 3,
    "loop_mode": "off",      # off=不循环 / one=单曲循环 / all=顺序循环 / shuffle=随机循环
    "loop_gap": 1.0,         # 两遍之间的间隔（秒）
}

# 播放模式：(值, 界面文字)
LOOP_MODES = [("off", "不循环"), ("one", "单曲循环"),
              ("all", "顺序循环"), ("shuffle", "随机循环")]

# 热键名 -> 说明（界面顺序）
HOTKEY_LABELS = [("start_stop", "开始 / 停止"), ("stop", "停止"),
                 ("pause", "暂停 / 继续"), ("replay", "从头重播")]

# ---- 曲库分类 ----
# 分类是自由文本，这里只提供一组建议值（界面上可下拉选、也能自己填新的）
CATEGORY_PRESETS = ["华语流行", "摇滚", "民谣", "动漫", "欧美",
                    "纯音乐", "影视游戏", "经典红歌", "儿歌", "网络热歌"]
UNCATEGORIZED = "未分类"        # 没有 category 字段的曲目，界面上归到这一类
ALL_CATEGORIES = "全部"          # 筛选下拉里的"不筛选"选项

SPECIAL_VK = {"Escape": 0x1B, "Tab": 0x09, "Caps_Lock": 0x14, "Space": 0x20,
              "Return": 0x0D, "BackSpace": 0x08, "Insert": 0x2D, "Delete": 0x2E,
              "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22,
              "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
              "Shift_L": 0xA0, "Shift_R": 0xA1, "Control_L": 0xA2,
              "Control_R": 0xA3, "Alt_L": 0xA4, "Alt_R": 0xA5}
PUNCT_VK = {"-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA,
            "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0}


def name_to_vk(name):
    """按键名（tkinter keysym） -> 虚拟键码"""
    n = (name or "").strip()
    if n in SPECIAL_VK:
        return SPECIAL_VK[n]
    m = re.fullmatch(r"[Ff](\d{1,2})", n)
    if m and 1 <= int(m.group(1)) <= 24:
        return 0x6F + int(m.group(1))          # F1 = 0x70
    if len(n) == 1:
        c = n.upper()
        if c.isalnum():
            return ord(c)
        if c in PUNCT_VK:
            return PUNCT_VK[c]
    raise ValueError(f"不支持的按键：{name}")


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))        # 深拷贝默认值
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k == "hotkeys" and isinstance(v, dict):
                    cfg["hotkeys"].update(v)
                elif k in cfg:
                    cfg[k] = v
        except Exception as e:
            print(f"[警告] config.json 读取失败（{e}），使用默认配置")
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = load_config()


class HotkeyListener(threading.Thread):
    """全局热键监听
    用 GetAsyncKeyState 轮询，不依赖窗口焦点——游戏在前台时同样生效。
    边沿触发：只在「松开 -> 按下」的瞬间执行一次，按住不会连续触发。"""

    def __init__(self, cfg, dispatch, interval=0.01):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.dispatch = dispatch
        self.interval = interval
        self.down = set()
        self.enabled = True                 # 重新绑定按键时临时关闭
        self.stop_ev = threading.Event()
        self.last_fire = None

    def bindings(self):
        out = {}
        for action, name in self.cfg["hotkeys"].items():
            try:
                out[action] = name_to_vk(name)
            except ValueError as e:
                print(f"[警告] 热键 {action}: {e}")
        return out

    def run(self):
        first = True
        while not self.stop_ev.is_set():
            if not self.enabled:
                self.down.clear()           # 关闭期间的状态不残留
            else:
                for action, vk in self.bindings().items():
                    pressed = key_state(vk)
                    if pressed and vk not in self.down:
                        self.down.add(vk)
                        if first:           # 程序启动时就按着的键不触发
                            continue
                        self.last_fire = (action, time.time())
                        try:
                            self.dispatch(action)
                        except Exception as e:
                            print(f"[错误] 热键 {action} 回调异常：{e}")
                    elif not pressed and vk in self.down:
                        self.down.discard(vk)
            first = False
            time.sleep(self.interval)


# ============ 曲目编辑器 ============
JIANPU_HELP = ("简谱写法：1-7 为音级，0 为休止\n"
               "  5'  5*  ^5   → 高八度（可叠加 5''）\n"
               "  5,  v5       → 低八度（可叠加，注意点号只表示附点）\n"
               "  #5 / b5      → 升 / 降半音\n"
               "  _5 或 5_     → 八分音符，__5 十六分\n"
               "  5-  5- -     → 增时线，每根加一拍\n"
               "  5.           → 附点，时值 ×1.5\n"
               "  | 空格 换行 歌词 → 自动忽略")


class SongEditor(tk.Toplevel):
    """新增 / 编辑曲目，结果直接写进 songs.json"""

    def __init__(self, master, name=None, on_saved=None):
        super().__init__(master)
        self.orig_name = name
        self.on_saved = on_saved
        self.title("新增曲目" if name is None else f"编辑《{name}》")
        self.geometry("660x600")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        pad = dict(padx=14, pady=4)
        top = tk.Frame(self)
        top.pack(fill="x", pady=(12, 0))
        tk.Label(top, text="曲名", font=("Microsoft YaHei", 10)).grid(row=0, column=0, sticky="w")
        self.v_name = tk.StringVar(value=name or "")
        tk.Entry(top, textvariable=self.v_name, width=20,
                 font=("Microsoft YaHei", 10)).grid(row=0, column=1, sticky="w")

        tk.Label(top, text="速度 BPM", font=("Microsoft YaHei", 10)).grid(row=0, column=2,
                                                                          sticky="w", padx=(16, 0))
        self.v_bpm = tk.StringVar(value="100")
        tk.Entry(top, textvariable=self.v_bpm, width=7,
                 font=("Microsoft YaHei", 10)).grid(row=0, column=3, sticky="w")

        tk.Label(top, text="调（1 = ）", font=("Microsoft YaHei", 10)).grid(row=0, column=4,
                                                                           sticky="w", padx=(16, 0))
        self.v_tonic = tk.StringVar(value="C4")
        tk.Entry(top, textvariable=self.v_tonic, width=7,
                 font=("Microsoft YaHei", 10)).grid(row=0, column=5, sticky="w")

        # ---- 分类：可下拉选已有分类，也能直接敲一个新分类 ----
        tk.Label(top, text="分类", font=("Microsoft YaHei", 10)).grid(row=1, column=0,
                                                                     sticky="w", pady=(8, 0))
        self.v_category = tk.StringVar(value="")
        cats = [c for c, _ in all_categories()] or list(CATEGORY_PRESETS)
        ttk.Combobox(top, textvariable=self.v_category, width=18,
                        values=cats, font=("Microsoft YaHei", 10)).grid(
            row=1, column=1, sticky="w", pady=(8, 0), columnspan=2)
        tk.Label(top, text="（留空 = 未分类；可下拉选，也可自己输一个新的）",
                 font=("Microsoft YaHei", 9), fg="#888").grid(
            row=1, column=3, sticky="w", padx=(10, 0), pady=(8, 0), columnspan=3)

        tk.Label(self, text="简谱（可直接粘贴，格式见下方说明）",
                 font=("Microsoft YaHei", 10)).pack(anchor="w", **pad)
        self.txt = tk.Text(self, height=14, font=("Consolas", 12), wrap="word")
        self.txt.pack(fill="both", expand=True, padx=14)

        tk.Label(self, text=JIANPU_HELP, font=("Consolas", 9), fg="#666",
                 justify="left").pack(anchor="w", padx=14, pady=(6, 0))

        self.info = tk.StringVar(value="")
        tk.Label(self, textvariable=self.info, font=("Microsoft YaHei", 9),
                 fg="#1D4ED8").pack(anchor="w", padx=14, pady=(6, 0))

        btns = tk.Frame(self)
        btns.pack(pady=10)
        tk.Button(btns, text="试解析", width=8, font=("Microsoft YaHei", 10),
                  command=self.check).pack(side="left", padx=4)
        tk.Button(btns, text="保存", width=8, font=("Microsoft YaHei", 10),
                  command=self.save).pack(side="left", padx=4)
        tk.Button(btns, text="取消", width=8, font=("Microsoft YaHei", 10),
                  command=self.destroy).pack(side="left", padx=4)

        if name:                                     # 编辑已有曲目时回填
            s = SONGS.get(name, {})
            self.v_bpm.set(str(s.get("bpm", 100)))
            self.v_tonic.set(s.get("tonic", "C4"))
            self.v_category.set(s.get("category") or "")
            self.txt.insert("1.0", s.get("jianpu") or self._to_jianpu(s.get("notes", [])))

    @staticmethod
    def _dur_suffix(dur):
        """拍数 -> 简谱时值记号。直接复用全局的 encode_dur（保证可原样读回）"""
        return encode_dur(dur)[0]

    @classmethod
    def _to_jianpu(cls, notes):
        """没有简谱原文时（内置曲目），按 1=C4 反推一份可编辑的简谱"""
        inv = {st: d for d, st in MAJOR_STEPS.items()}
        out = []
        for nm, dur in notes:
            if nm == "R":
                out.append("0" + cls._dur_suffix(dur))
                continue
            octv, pc = divmod(note_to_midi(nm) - 60, 12)
            if pc in inv:
                s = str(inv[pc])
            else:
                s = "#" + str(inv[(pc - 1) % 12])     # 黑键用升号近似
            s += "'" * octv if octv > 0 else "," * (-octv)
            out.append(s + cls._dur_suffix(dur))
        return " ".join(out)

    def check(self):
        jp = self.txt.get("1.0", "end").strip()
        if not jp:
            messagebox.showinfo("提示", "先写点简谱再试解析")
            return
        try:
            notes = parse_jianpu(jp, self.v_tonic.get().strip() or "C4")
        except Exception as e:
            messagebox.showerror("解析失败", str(e))
            return
        if not notes:
            messagebox.showerror("解析失败", "没识别出任何音符")
            return
        pitches = [note_to_midi(n) for n, _ in notes if n != "R"]
        lo, hi = (midi_to_name(min(pitches)), midi_to_name(max(pitches))) if pitches else ("-", "-")
        secs = sum(d for _, d in notes) * 60.0 / float(self.v_bpm.get() or 100)
        self.info.set(f"共 {len(notes)} 个音符，音域 {lo} ~ {hi}，"
                      f"总时长约 {int(secs // 60)}:{int(secs % 60):02d}")

    def save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showinfo("提示", "曲名不能为空")
            return
        jp = self.txt.get("1.0", "end").strip()
        if not jp:
            messagebox.showinfo("提示", "简谱不能为空")
            return
        try:
            bpm = float(self.v_bpm.get())
            tonic = self.v_tonic.get().strip() or "C4"
            note_to_midi(tonic)                       # 校验调号写法
            notes = parse_jianpu(jp, tonic)
        except Exception as e:
            messagebox.showerror("内容有误", str(e))
            return
        if not notes:
            messagebox.showerror("内容有误", "没识别出任何音符")
            return
        try:
            if self.orig_name and self.orig_name != name:
                SONGS.pop(self.orig_name, None)
            SONGS[name] = dict(bpm=bpm, notes=notes, jianpu=jp, tonic=tonic,
                               category=(self.v_category.get() or "").strip())
            save_songs()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        if self.on_saved:
            self.on_saved(name)
        self.destroy()


# ============ GUI ============
class App:
    def __init__(self, root):
        self.root = root
        self.player = None
        self.loop_round = 0        # 当前是第几遍（循环模式用）
        self.seq = 0               # 播放令牌：自增即可作废待启动的下一遍
        self.closing = False
        root.title("口琴小游戏 · 自动演奏器")
        root.geometry("600x820")
        root.resizable(False, True)          # 曲库会越来越长，允许纵向拉高
        root.minsize(600, 700)

        self.cat_filter = tk.StringVar(value=ALL_CATEGORIES)   # 当前筛选的分类
        self._shown = []                     # 列表里当前显示（筛选后）的曲名，顺序与 Listbox 一致

        tk.Label(root, text="口琴自动演奏器", font=("Microsoft YaHei", 14, "bold")).pack(pady=(14, 2))
        tk.Label(root, text="Z X C V B N M ,  = do re mi fa sol la si do′",
                 font=("Microsoft YaHei", 10), fg="#555").pack()
        tk.Label(root, text="左键=降八度    中键=升半音    右键=升八度",
                 font=("Microsoft YaHei", 9), fg="#777").pack(pady=(0, 8))

        box = tk.Frame(root)
        box.pack(fill="x", padx=20)

        # ---- 曲目表头：左边的"选择曲目"+ 右边的分类筛选 ----
        hdr = tk.Frame(box)
        hdr.pack(fill="x")
        tk.Label(hdr, text="选择曲目", font=("Microsoft YaHei", 10)).pack(side="left")
        tk.Button(hdr, text="管理分类", width=8, font=("Microsoft YaHei", 9),
                  command=self.manage_categories).pack(side="right")
        self.cat_box = ttk.Combobox(hdr, textvariable=self.cat_filter, width=12,
                                    state="readonly", font=("Microsoft YaHei", 9),
                                    values=[ALL_CATEGORIES])
        self.cat_box.pack(side="right", padx=(0, 6))
        self.cat_box.bind("<<ComboboxSelected>>", lambda *_: self.refresh_list())
        tk.Label(hdr, text="分类", font=("Microsoft YaHei", 9)).pack(side="right", padx=(0, 4))
        self.cat_count = tk.Label(hdr, text="", font=("Microsoft YaHei", 9), fg="#888")
        self.cat_count.pack(side="right", padx=(0, 10))

        lbf = tk.Frame(box)
        lbf.pack(fill="x", pady=(4, 6))
        self.listbox = tk.Listbox(lbf, height=9, font=("Microsoft YaHei", 10))
        sb = tk.Scrollbar(lbf, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="x", expand=True)
        sb.pack(side="left", fill="y")
        self.refresh_list()

        lib = tk.Frame(box)
        lib.pack(fill="x", pady=(0, 10))
        tk.Button(lib, text="＋ 新增", width=8, font=("Microsoft YaHei", 9),
                  command=lambda: self.edit_song(None)).pack(side="left")
        tk.Button(lib, text="编辑", width=6, font=("Microsoft YaHei", 9),
                  command=self.edit_selected).pack(side="left", padx=4)
        tk.Button(lib, text="删除", width=6, font=("Microsoft YaHei", 9),
                  command=self.delete_selected).pack(side="left")
        tk.Button(lib, text="重载曲库", width=8, font=("Microsoft YaHei", 9),
                  command=self.reload_library).pack(side="left", padx=4)
        tk.Button(lib, text="打开 songs.json", width=14, font=("Microsoft YaHei", 9),
                  command=self.open_library).pack(side="left")

        tk.Label(box, text="演奏速度", font=("Microsoft YaHei", 10)).pack(anchor="w")
        self.speed = tk.DoubleVar(value=float(CONFIG.get("speed", 1.0)))
        ttk.Scale(box, from_=0.6, to=1.6, variable=self.speed,
                  orient="horizontal").pack(fill="x")
        self.speed_label = tk.Label(box, text="1.00x", font=("Microsoft YaHei", 9), fg="#666")
        self.speed_label.pack(anchor="w")
        self.speed.trace_add("write", lambda *_: (
            self.speed_label.config(text=f"{self.speed.get():.2f}x"), self.save_settings()))

        tk.Label(box, text="发送方式", font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(10, 0))
        self.mode = tk.StringVar(value=CONFIG.get("send_mode", "scan"))
        frm = tk.Frame(box)
        frm.pack(anchor="w")
        tk.Radiobutton(frm, text="扫描码（推荐，兼容多数游戏）", variable=self.mode,
                       value="scan", font=("Microsoft YaHei", 9),
                       command=self.save_settings).pack(side="left")
        tk.Radiobutton(frm, text="虚拟键码", variable=self.mode, value="vk",
                       font=("Microsoft YaHei", 9),
                       command=self.save_settings).pack(side="left", padx=(12, 0))

        # ---- 循环播放 ----
        tk.Label(box, text="循环模式", font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(10, 0))
        lf = tk.Frame(box)
        lf.pack(anchor="w")
        self.loop_mode = tk.StringVar(value=CONFIG.get("loop_mode", "off"))
        # 播放线程里也要知道当前模式，但 Tk 变量不能跨线程读 —— 用普通属性做镜像
        self._loop_mode = self.loop_mode.get()
        self.loop_mode.trace_add("write",
                                 lambda *_: setattr(self, "_loop_mode", self.loop_mode.get()))
        for val, lab in LOOP_MODES:
            tk.Radiobutton(lf, text=lab, variable=self.loop_mode, value=val,
                           font=("Microsoft YaHei", 9),
                           command=self.save_settings).pack(side="left", padx=(0, 10))

        rowg = tk.Frame(box)
        rowg.pack(anchor="w", pady=(2, 0))
        tk.Label(rowg, text="两遍之间的间隔（秒）", font=("Microsoft YaHei", 9)).pack(side="left")
        self.gap_var = tk.DoubleVar(value=float(CONFIG.get("loop_gap", 1.0)))
        tk.Spinbox(rowg, from_=0, to=30, increment=0.5, width=4, format="%.1f",
                   font=("Microsoft YaHei", 9), textvariable=self.gap_var,
                   command=self.save_settings).pack(side="left", padx=6)
        self.gap_var.trace_add("write", lambda *_: self.save_settings())

        # ---- 全局热键 ----
        tk.Label(box, text="全局热键（游戏在前台时同样生效，点按键可改）",
                 font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(10, 0))
        hk = tk.Frame(box)
        hk.pack(fill="x", pady=(4, 0))
        self.hk_vars = {}
        for i, (action, label) in enumerate(HOTKEY_LABELS):
            r, c = divmod(i, 2)
            tk.Label(hk, text=label, font=("Microsoft YaHei", 9), width=12,
                     anchor="w").grid(row=r, column=c * 2, sticky="w", pady=2)
            v = tk.StringVar(value=CONFIG["hotkeys"].get(action, ""))
            self.hk_vars[action] = v
            tk.Button(hk, textvariable=v, width=9, font=("Microsoft YaHei", 9),
                      command=lambda a=action: self.rebind(a)
                      ).grid(row=r, column=c * 2 + 1, sticky="w", padx=4)

        row2 = tk.Frame(box)
        row2.pack(anchor="w", pady=(8, 0))
        tk.Label(row2, text="开始倒计时（秒）", font=("Microsoft YaHei", 9)).pack(side="left")
        self.cd_var = tk.IntVar(value=int(CONFIG.get("countdown", 3)))
        tk.Spinbox(row2, from_=0, to=10, width=4, font=("Microsoft YaHei", 9),
                   textvariable=self.cd_var, command=self.save_settings).pack(side="left", padx=6)
        self.hk_state = tk.StringVar(value="")
        tk.Label(row2, textvariable=self.hk_state, font=("Microsoft YaHei", 9),
                 fg="#0F766E").pack(side="left", padx=(14, 0))

        self.env = tk.Label(root, font=("Microsoft YaHei", 9), fg="#B45309")
        self.env.pack(pady=(10, 0))

        btns = tk.Frame(root)
        btns.pack(pady=12)
        self.btn_start = tk.Button(btns, text="开始演奏", width=16,
                                   font=("Microsoft YaHei", 10), command=self.start)
        self.btn_start.grid(row=0, column=0, padx=5)
        self.btn_test = tk.Button(btns, text="测试单音", width=10,
                                  font=("Microsoft YaHei", 10), command=self.test_note)
        self.btn_test.grid(row=0, column=3, padx=5)
        self.btn_pause = tk.Button(btns, text="暂停 / 继续", width=12,
                                   font=("Microsoft YaHei", 10), command=self.toggle_pause,
                                   state="disabled")
        self.btn_pause.grid(row=0, column=1, padx=5)
        self.btn_stop = tk.Button(btns, text="停止", width=10,
                                  font=("Microsoft YaHei", 10), command=self.stop,
                                  state="disabled")
        self.btn_stop.grid(row=0, column=2, padx=5)

        self.status = tk.StringVar(value="就绪 — 选好曲目后点「开始演奏」，然后切到游戏窗口")
        tk.Label(root, textvariable=self.status, font=("Consolas", 10), fg="#333",
                 wraplength=500, height=3).pack(pady=(4, 6))

        hk_tip = "   ".join(f"{lab}={CONFIG['hotkeys'].get(a, '?')}"
                            for a, lab in HOTKEY_LABELS)
        tip = ("开始后先倒计时，请切到游戏窗口让它获得焦点；结束后所有按键会自动松开。\n"
               "分类：右上角下拉框可筛选；顺序/随机循环只在**当前筛选的分类**里走。\n"
               "演奏中请不要碰鼠标（左/中/右键被用来切八度和半音）。")
        tk.Label(root, text=tip, font=("Microsoft YaHei", 9), fg="#888",
                 justify="left", wraplength=510).pack(padx=20, pady=(4, 0))

        # 全局热键监听：常驻后台线程，游戏有焦点时也能收到
        self.listener = HotkeyListener(CONFIG, self.on_hotkey)
        self.listener.start()
        self.cd_var.trace_add("write", lambda *_: self.sync_start_label())

        self.refresh_env()
        self.sync_start_label()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.fit_window()

    def fit_window(self):
        """按实际内容把窗口高度调到刚好装下（屏幕不够高就顶到屏幕高度）。
        曲库、提示文字一变，界面高度就会变，固定尺寸容易把底部按钮挤没。
        """
        self.root.update_idletasks()
        need = self.root.winfo_reqheight() + 12         # 留一点余量，免得最后一行贴边
        maxh = self.root.winfo_screenheight() - 90      # 留出任务栏和标题栏
        h = max(700, min(need, maxh))
        self.root.geometry(f"600x{h}")

    def refresh_env(self):
        """实时显示权限与焦点窗口，方便确认输入到底发给了谁"""
        perm = "管理员 ✓" if is_admin() else "标准用户 ✗（游戏若是管理员运行，本程序也必须以管理员启动）"
        alive = getattr(self, "listener", None) and self.listener.is_alive()
        hk = "热键监听中" if alive else "热键未运行 ✗"
        self.env.config(text=f"权限：{perm}\n当前焦点窗口：{foreground_title() or '（无）'}      {hk}")
        self.root.after(600, self.refresh_env)

    # ---------- 曲库增删 ----------
    def _current_cat(self):
        """下拉框里显示的是「分类（N）」，这里还原成纯分类名供筛选用"""
        v = self.cat_filter.get()
        if v == ALL_CATEGORIES:
            return ALL_CATEGORIES
        return re.sub(r"（\d+）$", "", v).strip()

    def refresh_category_box(self):
        """刷新分类下拉框的选项与数量；当前分类若已不存在就退回「全部」"""
        cats = all_categories()
        raw = [c for c, _ in cats]
        self.cat_box["values"] = [ALL_CATEGORIES] + [f"{c}（{n}）" for c, n in cats]
        cur = self._current_cat()
        if cur != ALL_CATEGORIES and cur not in raw:
            self.cat_filter.set(ALL_CATEGORIES)
        total = len(SONGS)
        if self._current_cat() == ALL_CATEGORIES:
            self.cat_count.config(text=f"共 {total} 首")
        else:
            self.cat_count.config(text=f"筛出 {len(songs_in_category(self._current_cat()))}/{total} 首")

    def refresh_list(self, select=None):
        self.refresh_category_box()
        self._shown = songs_in_category(self._current_cat())
        self.listbox.delete(0, "end")
        for n in self._shown:
            self.listbox.insert("end", f"{n}      [{song_category(SONGS.get(n))}]")
        if self._shown:
            idx = self._shown.index(select) if select in self._shown else 0
            self.listbox.selection_clear(0, "end")   # 不清会残留旧选中，导致选中项错乱
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def selected(self):
        """返回当前选中项的**曲名**（Listbox 里显示的是"曲名 [分类]"，不能直接取）"""
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._shown):
            return None
        return self._shown[sel[0]]

    def manage_categories(self):
        """分类管理：整体改名 / 清空分类"""
        win = tk.Toplevel(self.root)
        win.title("分类管理")
        win.geometry("440x440")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="曲库分类", font=("Microsoft YaHei", 11, "bold")).pack(pady=(12, 2))
        tk.Label(win, text="选中一个分类后可以整体改名（该类下所有曲目一起改），\n"
                           "或清空它（曲目回到「未分类」）。",
                 font=("Microsoft YaHei", 9), fg="#666", justify="left").pack(anchor="w", padx=16)

        lb = tk.Listbox(win, font=("Microsoft YaHei", 10), height=13)
        lb.pack(fill="both", expand=True, padx=16, pady=(8, 6))
        items = []                                    # [(纯分类名, 显示文本)]

        def reload_cats():
            lb.delete(0, "end")
            items.clear()
            items.extend((c, f"{c}      {n} 首") for c, n in all_categories())
            for _, txt in items:
                lb.insert("end", txt)

        def picked():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("提示", "先在列表里选一个分类", parent=win)
                return None
            return items[sel[0]][0]

        def do_rename():
            old = picked()
            if not old:
                return
            new = simpledialog.askstring("分类改名", f"把「{old}」改成：",
                                         initialvalue="" if old == UNCATEGORIZED else old,
                                         parent=win)
            if new is None:
                return
            new = new.strip()
            if not new or new == old:
                return
            n = rename_category(old, new)
            save_songs()
            reload_cats()
            self.refresh_list()
            self.status.set(f"已把「{old}」改名为「{new}」，共 {n} 首")

        def do_clear():
            old = picked()
            if not old:
                return
            if old == UNCATEGORIZED:
                messagebox.showinfo("提示", "「未分类」本身就是空的，不用清", parent=win)
                return
            if not messagebox.askyesno("清空分类", f"把「{old}」下所有曲目改成未分类？", parent=win):
                return
            n = rename_category(old, "")
            save_songs()
            reload_cats()
            self.refresh_list()
            self.status.set(f"已清空分类「{old}」，{n} 首回到未分类")

        btns = tk.Frame(win)
        btns.pack(pady=(0, 12))
        tk.Button(btns, text="改名", width=8, font=("Microsoft YaHei", 10),
                  command=do_rename).pack(side="left", padx=4)
        tk.Button(btns, text="清空分类", width=10, font=("Microsoft YaHei", 10),
                  command=do_clear).pack(side="left", padx=4)
        tk.Button(btns, text="关闭", width=8, font=("Microsoft YaHei", 10),
                  command=win.destroy).pack(side="left", padx=4)
        reload_cats()

    def edit_song(self, name=None):
        SongEditor(self.root, name, self.refresh_list)

    def edit_selected(self):
        n = self.selected()
        if n:
            self.edit_song(n)
        else:
            messagebox.showinfo("提示", "先在列表里选一首曲子")

    def delete_selected(self):
        n = self.selected()
        if not n:
            messagebox.showinfo("提示", "先在列表里选一首曲子")
            return
        if not messagebox.askyesno("删除曲目", f"确定删除《{n}》？\n（会同步从 songs.json 移除）"):
            return
        SONGS.pop(n, None)
        try:
            save_songs()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        self.refresh_list()
        self.status.set(f"已删除《{n}》")

    def reload_library(self):
        try:
            reload_songs()
        except Exception as e:
            messagebox.showerror("读取失败", f"songs.json 有错误：\n{e}")
            return
        self.refresh_list()
        self.status.set(f"已重载曲库，共 {len(SONGS)} 首")

    def open_library(self):
        try:
            os.startfile(SONGS_FILE)          # 用系统默认程序打开（一般是记事本）
            self.status.set(f"已打开 {SONGS_FILE}，改完点「重载曲库」")
        except Exception as e:
            messagebox.showerror("打不开", str(e))

    def test_note(self):
        """发一个单独的 C4，用来快速验证输入通道是否送达游戏"""
        global SEND_MODE
        SEND_MODE = self.mode.get()

        def run():
            _send(key_press("Z"))
            time.sleep(0.45)
            _send(key_press("Z", up=True))

        threading.Thread(target=run, daemon=True).start()
        self.status.set("已发送测试音：Z 键按住 0.45 秒（无修饰 = C4）。"
                        "切到游戏后点这里，听游戏里有没有响。")

    def set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    # ---------- 设置持久化 ----------
    def save_settings(self):
        CONFIG["send_mode"] = self.mode.get()
        CONFIG["speed"] = round(float(self.speed.get()), 3)
        try:
            CONFIG["countdown"] = int(self.cd_var.get())
        except Exception:
            pass
        if hasattr(self, "loop_mode"):
            CONFIG["loop_mode"] = self.loop_mode.get()
        if hasattr(self, "gap_var"):
            try:
                CONFIG["loop_gap"] = round(float(self.gap_var.get()), 2)
            except Exception:
                pass
        try:
            save_config(CONFIG)
        except Exception as e:
            print("配置保存失败：", e)

    def sync_start_label(self):
        try:
            n = int(self.cd_var.get())
        except Exception:
            n = 3
        self.btn_start.config(text="开始演奏" + (f" ({n} 秒后)" if n else ""))

    # ---------- 全局热键 ----------
    def on_hotkey(self, action):
        """监听线程里回调，切回主线程再操作界面"""
        self.root.after(0, lambda: self.do_hotkey(action))

    def do_hotkey(self, action):
        if not getattr(self, "listener", None) or not self.listener.enabled:
            return
        label = dict(HOTKEY_LABELS).get(action, action)
        key = CONFIG["hotkeys"].get(action, "?")
        playing = bool(self.player and self.player.is_alive())
        if action == "start_stop":
            if playing:
                self.stop()
                self.set_status(f"热键 {key}：停止演奏")
            else:
                self.start()
                self.set_status(f"热键 {key}：开始演奏")
        elif action == "stop":
            self.stop()
            self.set_status(f"热键 {key}：停止演奏")
        elif action == "pause":
            if playing:
                self.toggle_pause()
                self.set_status(f"热键 {key}：暂停 / 继续")
        elif action == "replay":
            if playing:
                self.player.stop_ev.set()
            self.start()
            self.set_status(f"热键 {key}：从头重播")
        else:
            return
        self.flash(label)

    def flash(self, label):
        """状态栏右侧闪一下，确认热键确实被收到了"""
        self.hk_state.set(f"● 热键 {label}")
        self.root.after(700, lambda: self.hk_state.set(""))

    def rebind(self, action):
        """点界面上的按键：弹窗等待按下一个键"""
        if getattr(self, "listener", None):
            self.listener.enabled = False
        win = tk.Toplevel(self.root)
        win.title("设置热键")
        win.geometry("340x130")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text=f"请按下要绑定给「{dict(HOTKEY_LABELS)[action]}」的按键\n"
                           f"（按 Esc 取消；不建议绑游戏里已占用的键）",
                 font=("Microsoft YaHei", 10), pady=18).pack()
        win.focus_force()

        def finish(keysym):
            try:
                win.unbind("<KeyPress>")
            except Exception:
                pass
            win.destroy()
            if getattr(self, "listener", None):
                self.listener.enabled = True
            if keysym:
                CONFIG["hotkeys"][action] = keysym
                self.hk_vars[action].set(keysym)
                self.save_settings()
                self.status.set(f"热键已更新：{dict(HOTKEY_LABELS)[action]} → {keysym}")

        def on_key(ev):
            ks = ev.keysym
            if ks == "Escape" and action != "stop":
                finish(None)
                return
            try:
                name_to_vk(ks)
            except ValueError:
                return                       # 纯修饰键等不支持的，忽略继续等
            finish(ks)

        win.bind("<KeyPress>", on_key)
        win.protocol("WM_DELETE_WINDOW", lambda: finish(None))

    # ---------- 播放 / 循环 ----------
    def start(self):
        """手动开始（按钮 / 热键）：遍数从 1 重新计"""
        self.seq += 1                                  # 作废「待启动的下一遍」
        name = self.selected() or (self._shown[0] if self._shown else None)
        self.loop_round = 1
        self._launch(name)

    def _launch(self, name):
        """真正起一条播放线程"""
        if not name or name not in SONGS:
            self.set_status(f"曲库里没有《{name}》，已停止")
            self.finish_play()
            return
        if self.player and self.player.is_alive():
            self.player.stop_ev.set()
            self.player.join(0.5)
        global SEND_MODE
        SEND_MODE = self.mode.get()
        self.player = Player(name, self.speed.get(), self.set_status, self.on_done)
        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.btn_stop.config(state="normal")
        self.player.start()
        threading.Thread(target=self.countdown, args=(name,), daemon=True).start()

    def countdown(self, name):
        try:
            n = max(0, int(self.cd_var.get()))
        except Exception:
            n = 3
        rnd = f"（第 {self.loop_round} 遍）" if self.loop_round > 1 else ""
        tok = self.seq
        for i in range(n, 0, -1):
            if (not self.player) or self.player.stop_ev.is_set() or tok != self.seq:
                return
            self.set_status(f"《{name}》{rnd} {i} 秒后开始… 请切到游戏窗口")
            time.sleep(1)
        if tok != self.seq:
            return
        self.set_status(f"演奏中：《{name}》{rnd}")

    # ---- 循环调度 ----
    def next_song(self, mode):
        """按模式算出下一首要播什么。
        顺序/随机循环只在**当前筛选出来的分类**里走 —— 比如筛了「动漫」，
        随机循环就只挑动漫曲目，不会跳到儿歌去。
        """
        names = self._shown or list(SONGS)             # 优先用当前筛选后的可见列表
        if not names:
            return None
        cur = getattr(self.player, "name", None) or self.selected() or names[0]
        if mode == "one":                              # 单曲循环：还是这首
            return cur if cur in names else names[0]
        if mode == "all":                              # 顺序循环：下一首，到底回到第一首
            i = names.index(cur) if cur in names else -1
            return names[(i + 1) % len(names)]
        if mode == "shuffle":                          # 随机循环：不重复当前这首
            pool = [n for n in names if n != cur] or names
            return random.choice(pool)
        return None

    def schedule_next(self, name, mode):
        """间隔若干秒后自动接上下一遍，期间可被打断"""
        self.refresh_list(name)                        # 列表选中项跟着走
        label = dict(LOOP_MODES).get(mode, mode)
        try:
            gap = max(0.0, float(self.gap_var.get()))
        except Exception:
            gap = 1.0
        tok = self.seq

        def wait_gap():
            if gap >= 1:
                for i in range(int(gap), 0, -1):
                    if tok != self.seq or self.closing:
                        return
                    self.set_status(f"{label}：{i} 秒后播放《{name}》"
                                    f"（第 {self.loop_round} 遍）")
                    time.sleep(1)
            rem = gap - int(gap)
            if rem > 0.05:
                time.sleep(rem)
            if tok != self.seq or self.closing:
                return
            self.root.after(0, lambda: self._fire_next(name, tok))

        threading.Thread(target=wait_gap, daemon=True).start()

    def _fire_next(self, name, tok):
        if tok != self.seq or self.closing:
            return
        self._launch(name)

    def toggle_pause(self):
        if self.player and self.player.is_alive():
            self.player.pause_ev.set() if not self.player.pause_ev.is_set() \
                else self.player.pause_ev.clear()

    def stop(self):
        self.seq += 1                                  # 取消「间隔后自动接下一遍」
        if self.player:
            self.player.stop_ev.set()
        self.finish_play()

    def on_done(self, natural=True):
        """在播放线程里被调用：这里只做纯 Python 判断，碰界面的事一律交给主线程"""
        mode = getattr(self, "_loop_mode", "off")
        if natural and mode != "off" and not self.closing:
            self.root.after(0, lambda: self._continue_loop(mode))
        else:
            self.finish_play()

    def _continue_loop(self, mode):
        """主线程：算出下一首并安排间隔后启动"""
        nxt = self.next_song(mode)               # 这里读列表框，必须在主线程
        if not nxt:
            self.finish_play()
            return
        self.loop_round += 1
        self.schedule_next(nxt, mode)

    def finish_play(self):
        """收尾复位；若已有新的一遍在跑，就不覆盖当前状态"""
        def ui():
            if self.closing:
                return
            if self.player and self.player.is_alive():
                return                                 # 例如「重播」时旧线程收尾，别乱按钮
            self.status.set("演奏结束（所有按键已松开）")
            self.btn_start.config(state="normal")
            self.btn_pause.config(state="disabled")
            self.btn_stop.config(state="disabled")
        self.root.after(0, ui)

    def on_close(self):
        self.closing = True
        self.seq += 1
        if self.player:
            self.player.stop_ev.set()
            self.player.join(0.5)
        if getattr(self, "listener", None):
            self.listener.stop_ev.set()
        self.root.destroy()


def dry_run():
    """不发送任何输入，只检查音高映射是否正确"""
    print("=== 映射自检（不发送按键）===")
    for song, data in SONGS.items():
        keys = set()
        out = []
        for name, _dur in data["notes"]:
            if name == "R":
                continue
            k, mods = map_note(note_to_midi(name))
            keys.add(k)
            out.append(k + ("".join(m[0].upper() for m in mods) if mods else ""))
        used_mods = {m for _k, mod in [map_note(note_to_midi(n))
                                       for n, _d in data["notes"] if n != "R"]
                     for m in mod}
        print(f"{song}: 音域 {min(note_to_midi(n) for n, _ in data['notes'] if n != 'R')}"
              f"~{max(note_to_midi(n) for n, _ in data['notes'] if n != 'R')}  "
              f"用到修饰 {used_mods or '无'}")
    print("\n单音映射示例:")
    for n in ["C4", "D4", "E4", "C5", "C#5", "F#5", "C3", "G5", "C6"]:
        k, mods = map_note(note_to_midi(n))
        print(f"  {n:4s} -> 键 {k}" + (f" + {'+'.join(mods)}" if mods else ""))


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        dry_run()
    else:
        if not ensure_admin():
            sys.exit(0)          # 已触发 UAC 提权重启，当前实例退出
        root = tk.Tk()
        App(root)
        root.mainloop()
