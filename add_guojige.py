# -*- coding: utf-8 -*-
"""
把《国际歌》(欧仁·鲍狄埃词 / 比尔·狄盖特曲) 加入曲库。

谱源：群谱子/160847.gif —— 官方版简谱（4/4 拍，中板 庄严 雄伟地）
      原谱 1 = bB（两个降号，曲中 b7 即 F#/Gb 为特征音）。

【关于调与八度】
      谱面原调 1=bB，音域 bB3~bA3 全在低音区，口琴键位 Z~M 的甜区是 C4~B4。
      这里按 1=C4 记谱 —— 正好比原调 bB 高一个全音，音级完全照谱面誊写、
      不做任何八度挪动，谱面 i 就记 1'、中音 5 就记 5。

      另一条路是「照谱面写、但整体降八度」（把 i 记成 (1)），音域会落到 C3~G4，
      直接掉出口琴键位范围、要压左键，所以没用。

      注：这样记出来音域是 D4~A5，谱面 i 那几句会需要右键升八度；
      若要一个八度修饰都不用，可整曲改记成 1=F4（谱面 1 记作 5），
      音区完全落在 G4~G5 —— 按需在曲子编辑里改调即可。

【关于时值】
      谱面是「一曲到底、无小节线」的排版，音值全靠下划线/附点分辨。
      16 分音符的连缀（如 4 4 2 3 4 0 4）按吐音颗粒感处理，不减时值。
      句尾长音（原谱 5 - - 、i - -）已按谱面照写。

用法：
    python add_guojige.py
"""
import sys

import harmonica_autoplay as H

# 记谱：5 一拍 / 5_ 半拍 / 5- 两拍 / 5. 附点 / 0 休止 / #5 升号 / (5) 低八度 / 5' 高八度
# 完全照谱面誊写（1=C4）：谱面 i 即 1'，中音 5 即 5
GUOJIGE_JIANPU = "\n".join([
    # ===== 第一句：起来，饥寒交迫的奴隶 =====
    "5 1'.7_2'_1'_5_3_ 6. 6 4 0 6 2'.1'_7_6_5_4_ 3 - - 5",
    # ===== 第二句：满腔的热血已经沸腾 =====
    "1'.7_2'_1'_5_3_ 6 - 4^6_2'_1' 7 2 4 7 1' - 1' 0 3_2_",
    # ===== 第三句：旧世界打个落花流水 =====
    "7 - 6_7_1'6_ 7 - 5^5_4_5_ 6. 6 2'.1'_ 7 - 7 0 2'",
    # ===== 第四句：我们要做天下的主人 =====
    "2'. 7_5_5_4_5_ 3 - 1'^6_7_1'_ 7_2'_1'_6_ 5 - 5 0 3_2_",
    # ===== 第五句：这是最后的斗争，团结起来到明天 =====
    "1' - 5. 3 6 - 4 0 2'.1' 7 - 6 5 5 - 5 0 5 3' - 2' 5",
    # ===== 第六句：英特纳雄耐尔就一定要实现 =====
    "1' - 7. 7 6.^5_6_2' 2 - 2 0 3.2' 1' - 5. 3 6 - 4 0 2'.1'",
    # ===== 第七句：这是最后的斗争，团结起来到明天 =====
    "7 - 6 5 3' - - 3' 5 - 4 3 2'.3_4_0_4_ 3.3'_2'.",
    # ===== 第八句：英特纳雄耐尔就一定要实现 =====
    "1' - -",
])

# 谱面还原按原调 1=bB 记时的音高对照（去掉低八度括号 + 高八度点），
# 用于核对「音级是否与谱一致」——把 (1). 还原成 1'. 后应能对上图片谱面
CHECK_JIANPU = GUOJIGE_JIANPU


SONG_NAME = "国际歌"


def main():
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())

    # 1=C4 把整曲降八度记谱，音域落在 C4~A4
    notes = H.parse_jianpu(GUOJIGE_JIANPU, "C4")
    if not notes:
        print("[失败] 没解析出音符")
        return

    H.SONGS[SONG_NAME] = dict(bpm=72, notes=notes, jianpu=GUOJIGE_JIANPU, tonic="C4")

    pitches = [H.note_to_midi(n) for n, _ in notes if n != "R"]
    lo, hi = H.midi_to_name(min(pitches)), H.midi_to_name(max(pitches))
    beats = sum(d for _, d in notes)
    secs = beats * 60.0 / 72
    mods = {m for n, _ in notes if n != "R" for m in H.map_note(H.note_to_midi(n))[1]}
    keys = {H.map_note(H.note_to_midi(n))[0] for n, _ in notes if n != "R"}
    print(f"《{SONG_NAME}》 {len(notes)} 音符  音域 {lo}~{hi}  "
          f"{int(secs // 60)}:{int(secs % 60):02d}  用键 {''.join(sorted(keys))}  "
          f"修饰 {sorted(mods) or '无'}")

    H.save_songs()
    print(f"\n已写入 songs.json，当前共 {len(H.SONGS)} 首")


def check():
    """核对：同一份简谱文本按原调 1=bB 与入库的 1=C4 各解析一遍，
    只要两者差的都是同一个固定音程，就说明音级完全照谱、没有抄错音"""
    ref = H.parse_jianpu(GUOJIGE_JIANPU, "A#3")       # 1=bB —— 原调实际音高
    got = H.parse_jianpu(GUOJIGE_JIANPU, "C4")        # 1=C4 —— 入库移高一个全音
    print(f"\n核对：原调 1=bB 解析 {len(ref)} 音 / 入库 1=C4 解析 {len(got)} 音")
    if len(ref) != len(got):
        print("  音符数不一致")
        return
    bad = 0
    for i, ((na, da), (nb, db)) in enumerate(zip(ref, got), 1):
        if abs(da - db) > 1e-6:
            bad += 1
            print(f"  [{i}] 时值不一致：{na}/{da:g} vs {nb}/{db:g}")
        if na != "R" and H.note_to_midi(nb) - H.note_to_midi(na) != 2:
            bad += 1
            print(f"  [{i}] 音程不是 2 个半音：{na} vs {nb}")
    print("音级与时值全部与谱面一致（整体移高一个全音）" if not bad else f"存在 {bad} 处差异")


if __name__ == "__main__":
    main()
    check()
