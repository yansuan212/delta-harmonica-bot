# -*- coding: utf-8 -*-
"""
添加 筷子兄弟《父亲》—— 直接按谱子文件自己的规则入库，不做任何移调/转换。

谱源：`群谱子/父亲.txt`（由 D:\\QQ文件\\父亲.txt 移过来的）
      原始谱：简谱家 jianpujia.com《父亲 王太利词曲》，1=E 4/4 ♩=72。
      文件已把 1=E 换算成绝对音高记谱，所以**正文的 1 就是 C4**，
      升号（#1 #2 #4 #5）已全部显式写出。

【入库方式：原样照搬】
      · tonic 填 C4 —— 依据文件头部「已换算为绝对音高记谱，1 = C4」
      · jianpu 字段**原封不动**存文件里的【简谱】正文，不做重排、不做往返转换
      · 因此 E 大调的四个升号（F#/G#/C#/D#）全部保留，
        演奏时这些音会走**中键（升半音）**，与用户要求一致

【按键映射（与程序 map_note 一致）】
      8 个白键 Z X C V B N M ,  = C4 D4 E4 F4 G4 A4 B4 C5
      左键 = 降八度     中键 = 升半音     右键 = 升八度

【为什么不做移调】
      上一版我把整曲降 4 个半音挪到 C 大调，好处是几乎不用按中键，
      但代价是**所有升号都没了**——那不是这首歌本来的样子。
      按用户要求改回原调 E 大调。
"""
import sys
from collections import Counter

import harmonica_autoplay as H

SRC_TXT = r"C:\Users\yansuan\Desktop\AI_work\小曲\群谱子\父亲.txt"
SONG_NAME = "父亲 (筷子兄弟)"


def load_jianpu(path=SRC_TXT):
    """只取【简谱】标记之后的正文，原样返回（头部说明含数字，不能被解析器看到）"""
    lines = open(path, encoding='utf-8').read().split('\n')
    k = next(i for i, l in enumerate(lines) if '【简谱】' in l)
    return '\n'.join(l.strip() for l in lines[k + 1:] if l.strip())


def main():
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())
    before = len(H.SONGS)

    jp = load_jianpu()
    notes = H.parse_jianpu(jp, "C4")                 # 依据文件规则：1 = C4
    if not notes:
        print("[失败] 没解析出音符")
        return

    H.SONGS[SONG_NAME] = dict(bpm=72, notes=notes, jianpu=jp,
                              tonic="C4", category="华语流行")

    pitched = [n for n, _ in notes if n != "R"]
    midis = [H.note_to_midi(n) for n in pitched]
    lo, hi = H.midi_to_name(min(midis)), H.midi_to_name(max(midis))
    beats = sum(d for _, d in notes)
    secs = beats * 60.0 / 72

    mods = [m for x in midis for m in H.map_note(x)[1]]
    c = Counter(mods)
    sharp_n = sum(1 for x in midis if (x % 12) not in H.NATURAL_PC)
    keys = {H.map_note(x)[0] for x in midis}

    print(f"《{SONG_NAME}》  调号 1=E（绝对音高记谱 1=C4，未移调）")
    print(f"  {len(notes)} 个音符（含休止），发声音 {len(pitched)} 个")
    print(f"  音域 {lo}~{hi}   总拍 {beats:g} = {beats / 4:g} 小节   "
          f"时长 {int(secs // 60)}:{int(secs % 60):02d}（BPM 72）")
    print(f"  带升号的音 {sharp_n} 个（{sharp_n / len(pitched) * 100:.0f}%）→ 走中键")
    print(f"  修饰次数 {dict(c)}")
    print(f"  用键 {''.join(sorted(keys))}")

    H.save_songs()
    print(f"\n{before} -> {len(H.SONGS)} 首")


if __name__ == "__main__":
    main()
