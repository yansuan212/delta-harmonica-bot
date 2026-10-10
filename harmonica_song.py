# -*- coding: utf-8 -*-
"""
口琴独奏合成脚本
根据简谱生成《主题与变奏》小曲，音色为合成口琴（簧片乐器）：
  - 基频 + 6 个泛音（口琴奇次谐波偏强）
  - 5.5Hz 自然颤音 (vibrato)
  - 带通滤波的气息噪声 (breath noise)
  - ADSR 包络 + 轻微音量颤动
  - 简易卷积混响 + 立体声展开
"""
import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100          # 采样率
BPM = 90            # 速度：每分钟 90 拍
BEAT = 60.0 / BPM   # 一拍时长（秒）
BREATH_GAP = 0.12   # 乐句之间的呼吸间隙（秒）

# 1 = C5，中高音区更接近独奏口琴的明亮音色
NOTE_FREQ = {
    "1": 523.25,  # C5
    "2": 587.33,  # D5
    "3": 659.25,  # E5
    "5": 783.99,  # G5
    "6": 880.00,  # A5
}

# 节奏型（单位：拍）：短短 + 长长长长 + 结尾延音，合计 8 拍 = 4 小节 (2/4)
PATTERN = [0.5, 0.5, 1.0, 1.0, 1.0, 1.0, 2.0]

# 简谱旋律：主题 - 变奏 - 对比 - 再现
MELODY = [
    "5565321",   # 1-4   主题动机
    "5565231",   # 5-8   变奏发展
    "1123553",   # 9-12  对比段落
    "5565321",   # 13-16 主题再现
]


def harmonica_note(freq: float, dur: float) -> np.ndarray:
    """合成一个口琴音符，长度 dur 秒"""
    n = int(dur * SR)
    t = np.arange(n) / SR

    # --- 颤音：5.5Hz 频率调制，幅度约 0.35%（簧片乐器的自然音高波动）---
    vib = 0.0035 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * freq * (t + np.cumsum(vib) / SR)

    # --- 泛音叠加：口琴频谱基频最强、2/3 次谐波明显 ---
    wave = np.zeros(n)
    harmonics = [(1, 1.00), (2, 0.45), (3, 0.28), (4, 0.14), (5, 0.08), (6, 0.05)]
    for h, amp in harmonics:
        if freq * h < SR / 2 - 2000:      # 避免超过奈奎斯特频率
            wave += amp * np.sin(h * phase)

    # --- 气息噪声：白噪声经 800~4000Hz 带通，模拟吹奏气声 ---
    noise = np.random.randn(n)
    b, a = signal.butter(2, [800 / (SR / 2), 4000 / (SR / 2)], btype="band")
    breath = 0.045 * signal.lfilter(b, a, noise)

    x = signal.lfilter(*signal.butter(2, 6000 / (SR / 2)), wave + breath)  # 轻柔化高频

    # --- ADSR 包络：快起音、自然衰减、末尾释放（避免爆音）---
    # 注意：起音 35ms + 释放 120ms 一共 155ms，比 1/4 拍还长。
    # 遇到很短的音（十六分音符、三连音）时 n 会小于 r_n，
    # 旧写法 env[-r_n:] 拿到的是整段、却去乘 r_n 长度的包络 → 直接崩。
    # 这里把两段都夹在音符长度之内，保证 a_n + r_n <= n。
    if n <= 1:
        return x * np.ones(max(n, 0))
    env = np.ones(n)
    a_n = max(1, min(int(0.035 * SR), n // 2))
    r_n = max(1, min(int(0.12 * SR), n - a_n))
    env[:a_n] = np.linspace(0, 1, a_n) ** 0.7
    env[n - r_n:] *= np.linspace(1, 0, r_n)
    # 与颤音同频的轻微音量波动
    env *= 1 + 0.03 * np.sin(2 * np.pi * 5.5 * t)
    return x * env


def render_score() -> np.ndarray:
    """按简谱把所有音符拼接成单声道旋律"""
    pieces = []
    for phrase in MELODY:
        for note_char, beats in zip(phrase, PATTERN):
            freq = NOTE_FREQ[note_char]
            dur = beats * BEAT
            pieces.append(harmonica_note(freq, dur))
        pieces.append(np.zeros(int(BREATH_GAP * SR)))  # 乐句间呼吸
    return np.concatenate(pieces)


def reverb_pair(x: np.ndarray) -> tuple:
    """生成左右两路卷积混响（不同随机脉冲响应 → 自然立体声宽度）"""
    ir_len = int(1.4 * SR)
    t_ir = np.arange(ir_len) / ir_len
    outs = []
    for seed in (7, 99):
        rng = np.random.default_rng(seed)
        ir = rng.standard_normal(ir_len) * np.exp(-3.5 * t_ir)
        ir /= np.linalg.norm(ir)
        outs.append(signal.fftconvolve(x, ir)[: len(x)])
    return outs


def main():
    print("正在合成口琴旋律 ...")
    dry = render_score()

    # 干声 + 湿声混合，立体声输出
    wet_l, wet_r = reverb_pair(dry)
    wet = 0.22
    left = 0.82 * dry + wet * wet_l
    right = 0.82 * dry + wet * wet_r

    # 整体归一化到 0.85 峰值，转 16bit
    stereo = np.stack([left, right], axis=1)
    stereo *= 0.85 / np.max(np.abs(stereo))
    out = (stereo * 32767).astype(np.int16)

    out_path = r"C:\Users\yansuan\Desktop\AI_work\小曲\口琴小曲_主题与变奏.wav"
    wavfile.write(out_path, SR, out)
    print(f"完成：{out_path}")
    print(f"总时长：{len(dry) / SR:.1f} 秒 | {BPM} BPM | 1=C5 | 2/4 拍 | 16 小节")


if __name__ == "__main__":
    main()
