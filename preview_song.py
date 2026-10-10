# -*- coding: utf-8 -*-
"""
把 songs.json 里的曲子渲染成口琴音色的 wav，用来试听效果。

用法：
    python preview_song.py 蓝莲花 海阔天空     # 渲染指定曲目（曲名可只写前两个字）
    python preview_song.py --all               # 渲染全部
输出到同目录，文件名形如 试听_蓝莲花 (许巍).wav
"""
import os
import sys

import numpy as np
from scipy.io import wavfile

import harmonica_autoplay as H
from harmonica_song import SR, harmonica_note, reverb_pair

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "试听")


def render(name, s):
    beat = 60.0 / s["bpm"]
    pieces = []
    for nm, dur in s["notes"]:
        n = max(1, int(dur * beat * SR))
        if nm == "R":
            pieces.append(np.zeros(n))
        else:
            freq = 440.0 * 2 ** ((H.note_to_midi(nm) - 69) / 12)
            pieces.append(harmonica_note(freq, dur * beat))
    if not pieces:
        return None
    dry = np.concatenate(pieces)
    wl, wr = reverb_pair(dry)
    stereo = np.stack([0.82 * dry + 0.22 * wl, 0.82 * dry + 0.22 * wr], axis=1)
    peak = np.max(np.abs(stereo))
    if peak > 0:
        stereo *= 0.85 / peak
    os.makedirs(OUT_DIR, exist_ok=True)
    fn = os.path.join(OUT_DIR, f"试听_{name}.wav")
    wavfile.write(fn, SR, (stereo * 32767).astype(np.int16))
    return fn


def main(argv):
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())
    if not argv or argv == ["--all"]:
        targets = list(H.SONGS)
    else:
        targets = []
        for key in argv:
            hit = [n for n in H.SONGS if key in n and n != "R"]
            targets.extend(hit or [key])
    for name in targets:
        s = H.SONGS.get(name)
        if not s:
            print(f"[跳过] 曲库里没有：{name}")
            continue
        fn = render(name, s)
        secs = sum(d for _, d in s["notes"]) * 60.0 / s["bpm"]
        print(f"《{name}》 {len(s['notes'])} 音符  {int(secs // 60)}:{int(secs % 60):02d}"
              f"  ->  {os.path.basename(fn) if fn else '失败'}")


if __name__ == "__main__":
    main(sys.argv[1:])
