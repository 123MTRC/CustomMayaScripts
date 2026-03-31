# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Visibility Controller Module
控制图层 Group 文件夹的可见性切换，实现帧切换效果。
"""

from typing import List, Optional
from .frame_scanner import FrameEntry


class VisibilityController:
    """
    可见性控制器：管理帧 Group 的 visible/hidden 状态。
    核心功能是将指定帧设为可见，其余帧隐藏。

    性能优化：通过缓存上一次显示的帧索引，show_frame() 只需
    隐藏旧帧 + 显示新帧，从 O(n) 降为 O(1)。
    """

    def __init__(self):
        self._frames: List[FrameEntry] = []
        self._visibility_cache: dict = {}  # 缓存原始可见性状态
        self._last_shown_index: int = -1   # 上一次显示的帧索引，-1 表示未初始化

    def set_frames(self, frames: List[FrameEntry]):
        """
        设置要控制的帧列表。

        Args:
            frames: FrameEntry 列表
        """
        self._frames = frames
        self._visibility_cache.clear()
        self._last_shown_index = -1  # 重置缓存

    def save_original_visibility(self):
        """
        保存所有帧的原始可见性状态，以便恢复。
        在开始播放前调用。
        """
        self._visibility_cache.clear()
        self._last_shown_index = -1  # 重置，确保恢复后首次 show_frame 执行全量设置
        for entry in self._frames:
            self._visibility_cache[entry.frame_number] = entry.safe_is_visible()

    def restore_original_visibility(self):
        """
        恢复所有帧的原始可见性状态。
        在停止播放后调用。
        """
        for entry in self._frames:
            original = self._visibility_cache.get(entry.frame_number, True)
            entry.safe_set_visible(original)
        self._last_shown_index = -1  # 恢复后重置缓存

    def show_frame(self, frame_index: int):
        """
        显示指定索引的帧，隐藏其余所有帧。
        这是播放器的核心方法。

        性能优化：如果已知上一帧索引，仅隐藏旧帧 + 显示新帧（O(1)）；
        首次调用或索引无效时执行全量设置（O(n)）。

        容错机制：增量模式失败时自动降级到全量模式。

        Args:
            frame_index: 帧列表索引（0-based）
        """
        if not self._frames:
            return

        if frame_index == self._last_shown_index:
            # 同一帧，无需操作
            return

        n = len(self._frames)
        if not (0 <= frame_index < n):
            return

        if 0 <= self._last_shown_index < n:
            # ---- 增量模式：仅切换两帧 O(1) ----
            hide_ok = self._frames[self._last_shown_index].safe_set_visible(False)
            show_ok = self._frames[frame_index].safe_set_visible(True)

            if not hide_ok or not show_ok:
                # 增量模式失败，降级到全量模式以保证状态一致
                print("[SequenceAnimation] 增量切帧失败，降级为全量模式")
                self._last_shown_index = -1  # 使下面的逻辑走全量分支
                self._show_frame_full(frame_index, n)
        else:
            # ---- 全量模式：首次调用或索引失效 O(n) ----
            self._show_frame_full(frame_index, n)

        self._last_shown_index = frame_index

    def _show_frame_full(self, frame_index: int, n: int):
        """全量模式设置帧可见性（内部方法）。"""
        for idx in range(n):
            entry = self._frames[idx]
            if not entry.safe_set_visible(idx == frame_index):
                # 节点失效，静默跳过（已在 safe_set_visible 中打印日志）
                pass

    def show_all_frames(self):
        """显示所有帧。"""
        for entry in self._frames:
            entry.safe_set_visible(True)
        self._last_shown_index = -1  # 全部可见，缓存失效

    def hide_all_frames(self):
        """隐藏所有帧。"""
        for entry in self._frames:
            entry.safe_set_visible(False)
        self._last_shown_index = -1  # 全部隐藏，缓存失效

    def set_frame_visibility(self, frame_index: int, visible: bool):
        """
        设置单个帧的可见性。

        Args:
            frame_index: 帧列表索引（0-based）
            visible: 是否可见
        """
        if 0 <= frame_index < len(self._frames):
            self._frames[frame_index].safe_set_visible(visible)

    def set_frame_opacity(self, frame_index: int, opacity: float):
        """
        设置单个帧的不透明度。

        Args:
            frame_index: 帧列表索引（0-based）
            opacity: 不透明度 (0.0 ~ 1.0)
        """
        if 0 <= frame_index < len(self._frames):
            try:
                self._frames[frame_index].layer_node.set_opacity(opacity)
            except Exception as e:
                print(f"[SequenceAnimation] 设置帧 "
                      f"{self._frames[frame_index].layer_name} "
                      f"不透明度失败 (节点可能已失效): {e}")

    def get_frame_opacity(self, frame_index: int) -> float:
        """获取单个帧的不透明度。"""
        if 0 <= frame_index < len(self._frames):
            try:
                return self._frames[frame_index].layer_node.get_opacity()
            except Exception:
                return 1.0
        return 1.0
