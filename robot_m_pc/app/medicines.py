from __future__ import annotations

MEDICINES: dict[int, str] = {
    1: "山楂",
    2: "大枣",
    3: "酸枣仁",
    4: "黄芪",
    5: "菊花",
    6: "枸杞",
    7: "当归",
    8: "陈皮",
    9: "茯苓",
    10: "甘草",
    11: "麦冬",
    12: "桑叶",
}


def medicine_name(slot_index: int) -> str:
    try:
        return MEDICINES[slot_index]
    except KeyError as exc:
        raise ValueError(f"不存在的药仓编号：{slot_index}") from exc

