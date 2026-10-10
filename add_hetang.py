# -*- coding: utf-8 -*-
"""
添加 凤凰传奇《荷塘月色》。

谱源：简谱之家 jianpujia.com   id=320294
      「荷塘月色高清版简谱_凤凰传奇演唱_张超/张超词曲」，2 页 2400×3394，罗文毅制谱。
      1=C  4/4  ♩=100  张超 词曲  凤凰传奇 演唱。
      这是**单行简谱 + 歌词**的干净版本，逐句读图誊写。

【记号】
      谱面大量使用**低音点**（数字下方的小圆点）—— 主歌的 6、5 大多在低八度，
      副歌「只为和你守候那皎白月光」里 1' 是高八度。本程序用 `,` 记低八度、`'` 记高八度。
      时值这里按「一个音一拍」平铺（rebuild_rhythm.py 会再统一配一次节奏），
      所以重点是**音高序列**准确，不纠结原谱的八分/十六分细分。

      第二页有一段男声二重唱（谱面分「男高」「男低」两行），这里取**男高**那一行为主。
"""
import sys

import harmonica_autoplay as H

SONG_NAME = "荷塘月色 (凤凰传奇)"

# 前奏 / 间奏 / 尾奏 用的是同一段动机，抽出来复用
_INTRO = [
    "1 5 1 5 1 2 | 3 - - | 1 5 1 5 1 2 | 2 - - |",
    "1 5 1 5 2 1 | 6, 6, 5, 1 2 | 1 5 1 5 1 6 | 1 - - |",
]
# 主歌（女声）—— 两遍歌词共用同一段旋律
_VERSE = [
    "1 1 6, 5, 6, | 1 1 2 3 - |",
    "2 2 1 2 2 5 | 5 3 3 2 3 - |",
    "1 1 6, 5, 5, 3 | 3 2 3 2 1 - |",
    "2 2 1 2 2 3 | 2 1 6, 2 1 - |",
]
# 副歌
#   注：末小节只有最后那个 6 带**低音点**（6,），前面的 5 3 2 1 都是中音 ——
#   放大逐音核对过，不能把 5 2 1 一并当成低音，否则会有莫名其妙的大跳。
_CHORUS = [
    "5 5 5 5 5 | 6 5 3 2 1 - |",
    "6 1' 6 5 3 2 1 6, | 2 2 3 3 2 - |",
    "3 5 5 5 5 | 6 5 3 2 1 - |",
    "1 6, 5, 2 3 | 1 - - - |",
]

HE_TANG = "\n".join(
    _INTRO
    + _VERSE                                    # 第一遍：剪一段时光…
    + _VERSE                                    # 第二遍：萤火虫点亮…
    + _CHORUS                                   # 我像只鱼儿在你的荷塘…
    + _INTRO                                    # 1 房子间奏
    # ---- 2 房子：漫天迷人的星光 ----
    + ["1 3 2 1 | 3 6, 5, 1 | 2 1 1 2 3 | 2 2 2 1 2 1 | 5 3 3 2 3 - |",
       "1 1 6, 5, 5 | 5 3 2 1 | 2 2 2 3 2 1 6 2 | 1 - - - |"]
    # ---- 男声段（取男高一行）：荷塘呀荷塘你慢慢唱哟 ----
    + ["3 3 6 3 3 6 | 1 6 1 2 2 1 | 3 3 6 3 3 6 | 2 1 2 3 5 5 |",
       "3 3 6 3 3 6 | 5 3 3 2 1 1 | 3 2 3 6 3 2 3 6 | 1 6 1 2 1 - |"]
    + _CHORUS                                   # 我像只鱼儿…（再现）
    + _CHORUS                                   # 转 1=D 后再来一遍
    + _INTRO                                    # 尾奏
)


def main():
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())
    before = len(H.SONGS)

    print("试不同 tonic 看音域：")
    for t in ("C4", "C5"):
        n = H.parse_jianpu(HE_TANG, t)
        ns = [x for x, _ in n if x != "R"]
        p = [H.note_to_midi(x) for x in ns]
        out = sum(1 for x in p if x < H.note_to_midi("C3") or x > H.note_to_midi("C6"))
        print("   1=%-3s  %-4s~%-5s  越界 %d" % (
            t, H.midi_to_name(min(p)), H.midi_to_name(max(p)), out))

    # 音区选择：谱面按女声记（1=C5，音域 G4~C6），但那样 388 个音里有 252 个
    # 要按右键升八度；改成 1=C4 后音域变 G3~C5，只有 36 个音需要按左键降八度，
    # 旋律一模一样、只是整体低一个八度。口琴游戏里音高绝对值不影响听感，选好按的。
    tonic = "C4"
    notes = H.parse_jianpu(HE_TANG, tonic)
    if not notes:
        print("[失败] 没解析出音符")
        return

    H.SONGS[SONG_NAME] = dict(bpm=100, notes=notes, jianpu=HE_TANG,
                              tonic=tonic, category="华语流行")
    pitches = [H.note_to_midi(n) for n, _ in notes if n != "R"]
    lo, hi = H.midi_to_name(min(pitches)), H.midi_to_name(max(pitches))
    beats = sum(d for _, d in notes)
    secs = beats * 60.0 / 100
    keys = {H.map_note(H.note_to_midi(n))[0] for n, _ in notes if n != "R"}
    mods = {m for n, _ in notes if n != "R" for m in H.map_note(H.note_to_midi(n))[1]}
    print()
    print(f"《{SONG_NAME}》 {len(notes)} 音符  音域 {lo}~{hi}  "
          f"{int(secs // 60)}:{int(secs % 60):02d}  用键 {''.join(sorted(keys))}  "
          f"修饰 {sorted(mods) or '无'}")

    H.save_songs()
    print(f"\n{before} -> {len(H.SONGS)} 首")


if __name__ == "__main__":
    main()
