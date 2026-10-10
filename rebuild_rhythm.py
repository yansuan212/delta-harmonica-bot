# -*- coding: utf-8 -*-
"""
把新加的曲目时值重新配一遍。

原问题：手写时值太随意，行长度不是 4 拍的整数倍（出现 6.5、13.5 拍这种），
        节拍站不住，演奏出来散乱。

重建规则：
    - 每个音统一半拍（八分），与正常歌唱语速相当
    - 「一行 = 一个乐句」，把行尾最后一个音拖长，使整行拍数补齐到 4 的整数倍

用法：
    python rebuild_rhythm.py            # 重建下面 TARGETS 里的所有曲目并写回 songs.json
    python rebuild_rhythm.py --dry      # 只打印重建结果，不写文件
"""
import math
import sys

import harmonica_autoplay as H

MAJOR = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
INV = {v: k for k, v in MAJOR.items()}

# 谱源不规整、需要重配时值的曲目（原谱导入的稻香/孤勇者/童年/起风了/东南苦行山不动）
TARGETS = [
    "海阔天空 (Beyond)",
    "蓝莲花 (许巍)",
    "光辉岁月 (Beyond)",
    "成都 (赵雷)",
    "晴天 (周杰伦)",
    "七里香 (周杰伦)",
    "夜曲 (周杰伦)",
    "一路向北 (周杰伦)",
    "反方向的钟 (周杰伦)",
    "杀死那个石家庄人 (万能青年旅店)",
    "回家 (Kenny G)",
    # ---- 2026-09-13 补：群谱子那批导入时漏跑，一并重配 ----
    "勇气 (梁静茹)",
    "国际歌",
    "See You Again",
    "打上花火",
    "The Other Side Of Pa",
    "得吃？！",
    # ---- 2026-09-13 新增：用户点名的 6 首 + 同风格补充 ----
    "戒烟 (李荣浩)",
    "青花瓷 (周杰伦)",
    "爸爸妈妈 (李荣浩)",
    "夜空中最亮的星 (逃跑计划)",
    "Melody (陶喆)",
    "平凡之路 (朴树)",
    "乌梅子酱 (李荣浩)",
    # ---- 2026-09-13 同风格补充第二批 ----
    "漠河舞厅 (柳爽)",
    "大鱼 (周深)",
    "南山南 (马頔)",
    "荷塘月色 (凤凰传奇)",
]


def name_to_jp(nm, base):
    """音名 -> 简谱写法（含高低八度点、半音记号）"""
    if nm == "R":
        return "0"
    q, pc = divmod(H.note_to_midi(nm) - base, 12)
    s = str(INV[pc]) if pc in INV else "#" + str(INV[(pc - 1) % 12])
    s += "'" * q if q > 0 else "," * (-q)
    return s


def dur_suffix(d):
    """拍数 -> 简谱时值记号（后缀形式）
       0.5 -> _      1.0 -> 空     1.5 -> -_
       2.0 -> -      2.5 -> --_    3.5 -> ---_   ...
    """
    n = int(d)
    half = abs(d - n - 0.5) < 1e-6
    if n == 0:
        return "_" if half else ""
    s = "-" * (n - 1)
    if half:
        s += "-_"
    return s


def rebuild(jp, tonic, omap=None):
    """把简谱重配时值。omap 为该曲括号八度语义，解析原文时要带上；
    输出用的是 name_to_jp 生成的显式 ' / , 八度记号，已自包含，不再依赖括号。"""
    base = H.note_to_midi(tonic)
    out = []
    for line in jp.split("\n"):
        if not line.strip():
            continue
        notes = H.parse_jianpu(line, tonic, omap)
        if not notes:
            continue
        n = len(notes)
        total = n * 0.5
        target = max(4, math.ceil(total / 4 - 1e-9) * 4)
        extra = target - total
        parts = []
        for i, (nm, _) in enumerate(notes):
            d = 0.5 + (extra if i == n - 1 else 0)
            parts.append(name_to_jp(nm, base) + dur_suffix(d))
        out.append(" ".join(parts))
    return "\n".join(out)


def main():
    dry = "--dry" in sys.argv
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())

    changed = {}
    for name in TARGETS:
        s = H.SONGS.get(name)
        if not s or not s.get("jianpu"):
            print(f"[跳过] {name}：没有简谱原文")
            continue
        tonic, bpm = s["tonic"], s["bpm"]
        omap = s.get("octave_map")
        new_jp = rebuild(s["jianpu"], tonic, omap)
        notes = H.parse_jianpu(new_jp, tonic)      # 输出已自包含，不再传 omap

        # 逐行核对
        bad = []
        for i, line in enumerate(new_jp.split("\n"), 1):
            b = sum(d for _, d in H.parse_jianpu(line, tonic))
            if abs(b / 4 - round(b / 4)) > 1e-6:
                bad.append((i, b))
        beats = sum(d for _, d in notes)
        secs = beats * 60.0 / bpm
        print(f"\n《{name}》 1={tonic} {bpm:g}BPM  "
              f"{len(notes)} 音符  总拍 {beats:g}  时长 {int(secs // 60)}:{int(secs % 60):02d}")
        print(f"  小节不整的行：{len(bad)}" + (f" {bad}" if bad else "（全部规整）"))
        if dry:
            print("  ---- 重建后简谱 ----")
            print("  " + new_jp.replace("\n", "\n  "))
        else:
            # 重建后简谱用显式八度记号，octave_map 不再需要；
            # 但 category 必须保留，否则分类会被这次重配抹掉
            H.SONGS[name] = dict(bpm=bpm, notes=notes, jianpu=new_jp, tonic=tonic,
                                 category=s.get("category", ""))
            changed[name] = new_jp

    if not dry and changed:
        H.save_songs()
        print(f"\n已写回 songs.json，重建 {len(changed)} 首")


if __name__ == "__main__":
    main()
