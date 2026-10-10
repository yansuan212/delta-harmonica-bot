# -*- coding: utf-8 -*-
"""
给曲库里每一首歌补上分类（只补 category 为空或未指定的，已有分类不动）。
分类词表见 harmonica_autoplay.CATEGORY_PRESETS。
用法：python set_categories.py
"""
import sys

import harmonica_autoplay as H

CATEGORY_OF = {
    # ---- 儿歌 ----
    "小星星": "儿歌",
    "生日快乐": "儿歌",
    # ---- 华语流行 ----
    "稻香": "华语流行",
    "孤勇者": "华语流行",
    "童年": "华语流行",
    "起风了": "华语流行",
    "晴天 (周杰伦)": "华语流行",
    "七里香 (周杰伦)": "华语流行",
    "夜曲 (周杰伦)": "华语流行",
    "一路向北 (周杰伦)": "华语流行",
    "反方向的钟 (周杰伦)": "华语流行",
    "勇气 (梁静茹)": "华语流行",
    "戒烟 (李荣浩)": "华语流行",
    "青花瓷 (周杰伦)": "华语流行",
    "爸爸妈妈 (李荣浩)": "华语流行",
    "Melody (陶喆)": "华语流行",
    "乌梅子酱 (李荣浩)": "华语流行",
    # ---- 摇滚 ----
    "海阔天空 (Beyond)": "摇滚",
    "蓝莲花 (许巍)": "摇滚",
    "光辉岁月 (Beyond)": "摇滚",
    "杀死那个石家庄人 (万能青年旅店)": "摇滚",
    "夜空中最亮的星 (逃跑计划)": "摇滚",
    # ---- 民谣 ----
    "成都 (赵雷)": "民谣",
    "东南苦行山 (殷正洋)": "民谣",
    "平凡之路 (朴树)": "民谣",
    # ---- 动漫 / 欧美 ----
    "打上花火": "动漫",
    "See You Again": "欧美",
    # ---- 纯音乐 ----
    "回家 (Kenny G)": "纯音乐",
    # ---- 影视游戏 ----
    "太阳照常升起": "影视游戏",
    "The Other Side Of Pa": "影视游戏",
    # ---- 经典红歌 ----
    "国际歌": "经典红歌",
    # ---- 网络热歌 ----
    "朋友的酒": "网络热歌",
    "得吃？！": "网络热歌",
}


def main():
    H.SONGS.clear()
    H.SONGS.update(H.load_songs())
    changed, unknown = 0, []
    for name, s in H.SONGS.items():
        cat = CATEGORY_OF.get(name)
        if cat and s.get("category") != cat:
            s["category"] = cat
            changed += 1
        elif not s.get("category") and not cat:
            unknown.append(name)
    H.save_songs()
    print(f"更新分类 {changed} 首，曲库共 {len(H.SONGS)} 首")
    if unknown:
        print("没有分配分类（仍是未分类）：", unknown)
    print()
    for c, n in H.all_categories():
        print(f"  {c}: {n} 首")


if __name__ == "__main__":
    main()
