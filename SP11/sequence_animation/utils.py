# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Utility Module
提供帧命名解析、排序等通用工具函数
"""

import re
import os
from typing import List, Tuple, Optional


# ============================================================
# 预置帧命名正则模式
# ============================================================

# 默认命名模式：匹配 Frame_001, Frame_01, frame-1, F001, f_01 等
_DEFAULT_FRAME_PATTERN_STRS = [
    r"(?i)^frame[_\-\s]?(\d+)$",   # Frame_001, Frame-01, Frame 1
    r"(?i)^f[_\-]?(\d+)$",          # F001, F_01, f-1
    r"(?i)^fr[_\-]?(\d+)$",         # Fr001, fr_01
    r"(?i)^seq[_\-]?(\d+)$",        # Seq_001, seq-01
    r"^(\d+)$",                       # 纯数字: 001, 01, 1
]

# 预编译正则对象，避免每次 parse_frame_number 调用都重新编译
DEFAULT_FRAME_PATTERNS = [re.compile(p) for p in _DEFAULT_FRAME_PATTERN_STRS]


def compile_custom_pattern(pattern: str) -> Optional[re.Pattern]:
    """
    预编译自定义正则表达式。

    在设置自定义模式时调用一次，后续 parse_frame_number 直接使用
    编译后的 Pattern 对象，避免每次匹配都重新编译。

    Args:
        pattern: 正则表达式字符串

    Returns:
        编译后的 re.Pattern 对象，编译失败返回 None
    """
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as e:
        print(f"[SequenceAnimation] 自定义正则编译失败: {e}")
        return None


def parse_frame_number(layer_name: str, custom_pattern=None) -> Optional[int]:
    """
    从图层名称中提取帧编号。

    Args:
        layer_name: 图层名称
        custom_pattern: 可选的自定义正则，支持两种类型：
            - re.Pattern: 已预编译的正则对象（推荐，零编译开销）
            - str: 正则字符串（兼容旧调用方式，每次调用会编译）
            必须包含一个捕获组用于提取帧编号数字

    Returns:
        帧编号（int），如果无法匹配则返回 None
    """
    # 如果提供了自定义模式，优先使用
    if custom_pattern is not None:
        try:
            # 支持已编译的 Pattern 对象和原始字符串两种形式
            if isinstance(custom_pattern, re.Pattern):
                match = custom_pattern.match(layer_name)
            else:
                match = re.match(custom_pattern, layer_name)
            if match:
                return int(match.group(1))
        except (re.error, IndexError):
            pass
        return None

    # 依次尝试预置模式（已预编译）
    for pattern in DEFAULT_FRAME_PATTERNS:
        match = pattern.match(layer_name)
        if match:
            return int(match.group(1))

    return None


def generate_frame_name(frame_number: int, prefix: str = "Frame", padding: int = 3) -> str:
    """
    生成帧名称。

    Args:
        frame_number: 帧编号
        prefix: 名称前缀
        padding: 数字补零位数

    Returns:
        格式化的帧名称，如 "Frame_001"
    """
    return f"{prefix}_{str(frame_number).zfill(padding)}"


def get_next_frame_number(existing_numbers: List[int]) -> int:
    """
    获取下一个可用的帧编号。

    Args:
        existing_numbers: 已存在的帧编号列表

    Returns:
        下一个帧编号
    """
    if not existing_numbers:
        return 1
    return max(existing_numbers) + 1


def validate_export_path(path: str) -> Tuple[bool, str]:
    """
    验证导出路径是否有效。

    Args:
        path: 导出目录路径

    Returns:
        (是否有效, 错误信息或空字符串)
    """
    if not path:
        return False, "导出路径不能为空"

    if not os.path.isabs(path):
        return False, "请使用绝对路径"

    parent = os.path.dirname(path)
    if not os.path.exists(parent):
        return False, f"父目录不存在: {parent}"

    return True, ""


def clamp(value, min_val, max_val):
    """将值限制在指定范围内。"""
    return max(min_val, min(max_val, value))


def lerp(a: float, b: float, t: float) -> float:
    """线性插值。"""
    return a + (b - a) * clamp(t, 0.0, 1.0)
