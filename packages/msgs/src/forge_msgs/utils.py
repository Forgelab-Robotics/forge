"""Arrow 等通用工具函数。"""

from __future__ import annotations


def parse_int_list_from_arrow(raw, length: int, int_to_str: dict, default: str) -> list:
    """
    从 Arrow 的 mode/unit 列（list of int8）取出的单个元素解析为长度为 length 的字符串列表。
    """
    if hasattr(raw, "as_py"):
        raw = raw.as_py()
    if not isinstance(raw, (list, tuple)):
        raise TypeError(
            f"mode/unit 列应为 list，得到 {type(raw).__name__}；请使用 to_arrow 生成的标准格式。"
        )
    return [
        int_to_str.get(int(raw[i]) if i < len(raw) else default, default)
        for i in range(length)
    ]
