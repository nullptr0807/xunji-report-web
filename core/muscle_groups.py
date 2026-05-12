"""把每个动作映射到主要肌群 (primary) 和次要肌群 (secondary)。
肌群标签: chest 胸, back 背, shoulders 肩, biceps 二头, triceps 三头,
        quads 股四, hams 腘绳, glutes 臀, adductors 内收, abductors 外展,
        core 核心
"""

# (primary_groups, secondary_groups)
MAP = {
    # ===== 胸 =====
    "杠铃卧推": (["chest"], ["triceps","shoulders"]),
    "上斜杠铃卧推": (["chest"], ["triceps","shoulders"]),
    "下斜杠铃卧推": (["chest"], ["triceps"]),
    "哑铃卧推": (["chest"], ["triceps","shoulders"]),
    "上斜哑铃卧推": (["chest"], ["triceps","shoulders"]),
    "悍马机推胸": (["chest"], ["triceps"]),
    "下斜悍马机推胸": (["chest"], ["triceps"]),
    "上斜悍马机": (["chest"], ["triceps"]),
    "器械推胸": (["chest"], ["triceps"]),
    "器械飞鸟": (["chest"], []),
    "蝴蝶机飞鸟": (["chest"], []),
    "绳索十字夹胸": (["chest"], []),
    "绳索夹胸": (["chest"], []),
    "下斜绳索夹胸": (["chest"], []),
    "弹力绳-高位飞鸟": (["chest"], []),
    "上斜史密斯机卧推": (["chest"], ["triceps","shoulders"]),

    # ===== 背 =====
    "硬拉": (["back","hams","glutes"], ["core"]),
    "杠铃划船": (["back"], ["biceps"]),
    "哑铃划船": (["back"], ["biceps"]),
    "站姿哑铃划船": (["back"], ["biceps"]),
    "坐姿划船": (["back"], ["biceps"]),
    "拉杆坐姿划船(窄握)": (["back"], ["biceps"]),
    "器械划船": (["back"], ["biceps"]),
    "器械划船2": (["back"], ["biceps"]),
    "V-bar划船": (["back"], ["biceps"]),
    "俯卧T-bar划船": (["back"], ["biceps"]),
    "宽距下拉": (["back"], ["biceps"]),
    "窄距下拉": (["back"], ["biceps"]),
    "悍马机下拉": (["back"], ["biceps"]),
    "悍马机正手下拉": (["back"], ["biceps"]),
    "V-bar下拉": (["back"], ["biceps"]),
    "引体向上": (["back"], ["biceps"]),
    "引体向上（辅助）": (["back"], ["biceps"]),
    "面拉": (["back","shoulders"], []),

    # ===== 腿 =====
    "深蹲": (["quads","glutes"], ["hams","core"]),
    "史密斯机深蹲": (["quads","glutes"], ["hams"]),
    "哈克机深蹲": (["quads","glutes"], []),
    "哑铃酒杯深蹲": (["quads","glutes"], []),
    "腿举": (["quads","glutes"], []),
    "器械倒蹬": (["quads","glutes"], []),
    "器械倒蹬(版本2)": (["quads","glutes"], []),
    "坐姿腿屈伸": (["quads"], []),
    "腿弯举": (["hams"], []),
    "坐姿腿弯举": (["hams"], []),
    "单边腿弯举（器械）": (["hams"], []),
    "坐姿髋内收": (["adductors"], []),
    "坐姿髋外展": (["abductors","glutes"], []),

    # ===== 肩 =====
    "站姿杠铃推举": (["shoulders"], ["triceps"]),
    "哑铃推肩": (["shoulders"], ["triceps"]),
    "悍马机坐姿推举": (["shoulders"], ["triceps"]),
    "史密斯机推举": (["shoulders"], ["triceps"]),
    "侧平举": (["shoulders"], []),
    "器械侧平举": (["shoulders"], []),
    "Y字绳索侧平举": (["shoulders"], []),
    "绳索侧平举（单边）": (["shoulders"], []),
    "半俯身侧平举": (["shoulders"], []),  # rear delt
    "肩膀后束哑铃": (["shoulders"], []),
    "杠铃直立划船": (["shoulders"], ["biceps"]),
    "杠铃前平举": (["shoulders"], []),
    "弹力带-前平举": (["shoulders"], []),
    "绳索胯裆前平举": (["shoulders"], []),

    # ===== 二头 =====
    "杠铃弯举": (["biceps"], []),
    "哑铃弯举": (["biceps"], []),
    "上斜哑铃弯举": (["biceps"], []),
    "坐姿哑铃弯举": (["biceps"], []),
    "锤式弯举": (["biceps"], []),
    "上斜锤式弯举": (["biceps"], []),
    "绳索弯举": (["biceps"], []),
    "直杆绳索弯举": (["biceps"], []),
    "器械弯举": (["biceps"], []),
    "牧师凳弯举": (["biceps"], []),
    "集中弯举": (["biceps"], []),
    "Biceps curl": (["biceps"], []),

    # ===== 三头 =====
    "绳索臂屈伸": (["triceps"], []),
    "直杆绳索下压": (["triceps"], []),
    "V-Bar 绳索下压": (["triceps"], []),
    "绳索直臂下压": (["triceps"], []),
    "铁杆直臂下压": (["triceps"], []),
    "双杠臂屈伸": (["triceps"], ["chest"]),
    "双杠臂屈伸（辅助）": (["triceps"], ["chest"]),
    "哑铃臂屈伸": (["triceps"], []),
    "哑铃过头臂屈伸": (["triceps"], []),

    # ===== 核心 =====
    "抬腿": (["core"], []),
    "悬挂抬腿": (["core"], []),
    "负重悬挂抬腿": (["core"], []),
    "转体抬腿": (["core"], []),
    "负重仰卧起坐": (["core"], []),
    "绳索跪姿卷腹": (["core"], []),
    "器械侧卷腹": (["core"], []),
    "上斜卷腹转体": (["core"], []),
    "站姿健腹轮前推": (["core"], []),

    # ===== 噪声 =====
    "kg": ([], []),  # 解析残留
}


def lookup(name: str):
    """返回 (primary_list, secondary_list)。未识别返回 (['unknown'], [])。"""
    if name in MAP:
        return MAP[name]
    # 尝试模糊匹配
    return (["unknown"], [])
