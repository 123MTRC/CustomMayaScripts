# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Onion Skin Module
洋葱皮功能：在当前帧前后显示半透明参考帧，辅助绘制。
通过直接调整帧 Group 文件夹自身的 opacity 实现半透明效果。

关键 API 注意事项：
  SP 的 get_opacity() / set_opacity() 对于非 mask 图层，
  需要传入 ChannelType 参数（如 BaseColor）。
  必须对所有启用的通道都设置 opacity 才能生效。
"""

from typing import List, Dict
from .frame_scanner import FrameEntry
from .visibility_controller import VisibilityController
from .utils import lerp


def _get_active_channels():
    """
    获取当前活动 Texture Set 的所有已启用通道列表。
    返回 list[Channel]，获取失败返回空列表。

    已验证的 SP Python API 结构（来自运行时 dir() 自省）：
      - ts.get_active_stack() -> Stack
      - TextureSet.get_stack(stack_name) / TextureSet.all_stacks() -> [Stack]
      - Stack.all_channels() -> list[Channel]  ← 正确获取通道的方式
      - Stack.has_channel(ChannelType) -> bool
      - Stack.get_channel(ChannelType) -> Channel
    """
    try:
        import substance_painter.textureset as ts

        # ---- 步骤 1：获取 Stack 对象 ----
        stack = None

        # 方式 A：模块级 get_active_stack()（最直接）
        try:
            stack = ts.get_active_stack()
        except Exception:
            pass

        # 方式 B：从 TextureSet 获取
        if stack is None:
            all_tsets = ts.all_texture_sets()
            tset = all_tsets[0] if all_tsets else None
            if tset:
                try:
                    stacks = tset.all_stacks()
                    if stacks:
                        stack = stacks[0]
                except Exception:
                    pass

                if stack is None:
                    for name_arg in ['', 'Default']:
                        try:
                            stack = tset.get_stack(name_arg)
                            if stack:
                                break
                        except Exception:
                            pass

        if stack is None:
            return []

        # ---- 步骤 2：从 Stack 获取通道列表 ----
        try:
            channels = stack.all_channels()
            if channels:
                return list(channels)
        except Exception:
            pass

        # ---- 步骤 3（回退）：用 Stack.has_channel() 遍历检测 ----
        if hasattr(ts, 'ChannelType'):
            ct = ts.ChannelType
            all_channel_names = [
                'BaseColor', 'Height', 'Roughness', 'Metallic',
                'Normal', 'Opacity', 'AmbientOcclusion', 'Emissive',
                'Specular', 'SpecularLevel', 'Glossiness',
                'Displacement', 'Diffuse',
            ]
            active_channels = []
            for name in all_channel_names:
                if hasattr(ct, name):
                    ch_type = getattr(ct, name)
                    try:
                        if stack.has_channel(ch_type):
                            ch_obj = stack.get_channel(ch_type)
                            active_channels.append(ch_obj)
                    except Exception:
                        pass
            if active_channels:
                return active_channels

        return []
    except Exception:
        return []


def _extract_channel_type(ch):
    """
    从 Channel 对象或 ChannelType 枚举中提取 set_opacity 所需的参数。

    SP 的 set_opacity(opacity, channel) 第二个参数需要 ChannelType 枚举值。
    Stack.all_channels() 返回的是 Channel 对象，需要提取其 channel_type 属性。

    Returns:
        ChannelType 枚举值，或原始对象（如果无法提取）
    """
    # 如果是 Channel 对象，提取 channel_type / type 属性
    for attr_name in ['channel_type', 'type']:
        if hasattr(ch, attr_name):
            return getattr(ch, attr_name)
    return ch


def _set_opacity_with_channel(node, opacity, channels, valid_channels=None):
    """
    使用通道参数设置节点 opacity。
    需要对所有有效通道都设置。

    支持传入 Channel 对象（会自动提取 ChannelType）或直接传入 ChannelType。

    Args:
        node: SP 图层节点
        opacity: 不透明度值
        channels: 所有候选通道列表（Channel 对象或 ChannelType）
        valid_channels: 已验证有效的通道列表（缓存），传入可跳过无效通道

    Returns:
        (success: bool, effective_channels: list or None)
        effective_channels 为本次实际成功的通道列表，可作为后续缓存
    """
    success = False

    # 如果有已验证的有效通道缓存，直接使用（跳过无效通道的 try/except）
    target_channels = valid_channels if valid_channels else channels

    if target_channels:
        effective = []
        for ch in target_channels:
            ch_type = _extract_channel_type(ch)
            try:
                node.set_opacity(opacity, ch_type)
                success = True
                effective.append(ch)
            except Exception:
                # 如果提取的 ch_type 失败，尝试直接用原始 ch
                if ch_type is not ch:
                    try:
                        node.set_opacity(opacity, ch)
                        success = True
                        effective.append(ch)
                    except Exception:
                        pass
        return success, effective if effective else None
    else:
        # 没有通道信息时才尝试不带参数
        try:
            node.set_opacity(opacity)
            return True, None
        except Exception:
            return False, None


class OnionSkinSettings:
    """洋葱皮参数设置。"""

    # 特殊标记：全通道模式
    ALL_CHANNELS = "__all__"

    def __init__(self):
        self.enabled: bool = False
        self.frames_before: int = 1      # 向前显示的帧数
        self.frames_after: int = 1       # 向后显示的帧数
        self.min_opacity: float = 0.1    # 最远帧的不透明度
        self.max_opacity: float = 0.5    # 最近帧的不透明度（非当前帧）
        # 不透明度通道选择：ALL_CHANNELS 表示全通道，否则为单个 ChannelType
        self.opacity_channel = self.ALL_CHANNELS


class OnionSkinController:
    """
    洋葱皮控制器：
    通过直接调整帧 Group 文件夹自身的 opacity 和 visibility 实现洋葱皮效果。

    工作原理：
    - 当前帧：Group opacity 设为 1.0（100%），可见
    - 洋葱皮范围内的帧：Group opacity 根据距离插值（min_opacity ~ max_opacity），可见
    - 范围外的帧：Group opacity 恢复为 1.0，隐藏

    设计假设：序列帧动画中每帧是独立的图层 Group，正常透明度均为 100%，
    因此无需记录原始透明度，统一以 1.0 作为基准值。

    性能优化：通过缓存上一次洋葱皮的影响帧集合，apply() 只需更新
    发生变化的帧（新增/移除/opacity 变动），而非全量遍历。
    """

    def __init__(self, visibility_controller: VisibilityController):
        self._vis_ctrl = visibility_controller
        self._settings = OnionSkinSettings()
        self._frames: List[FrameEntry] = []
        # 缓存可用的通道列表（候选通道）
        self._channels = []
        # 经过首次 set_opacity 验证后的有效通道缓存（避免重复 try/except）
        self._valid_channels = None
        # 上一次 apply() 的状态缓存
        # key: frame index, value: 设置的 opacity 值（当前帧为 1.0）
        self._last_applied: Dict[int, float] = {}
        # 上一次 apply() 中可见的帧索引集合
        self._last_visible_set: set = set()
        # 被洋葱皮修改过 opacity 的帧索引集合（用于智能 reset）
        self._dirty_opacities: set = set()

    @property
    def settings(self) -> OnionSkinSettings:
        return self._settings

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._settings.enabled = value

    def set_frames(self, frames: List[FrameEntry]):
        """设置帧列表。"""
        self._frames = frames
        self._channels = []
        self._valid_channels = None
        self._last_applied.clear()
        self._last_visible_set.clear()
        self._dirty_opacities.clear()

    def _ensure_channels(self):
        """确保已获取通道列表。"""
        if not self._channels:
            self._channels = _get_active_channels()

    def get_available_channels(self):
        """
        获取当前可用的通道列表，供 UI 构建下拉框使用。

        Returns:
            list of (channel_object, display_name) 元组。
            channel_object: SP ChannelType 枚举值
            display_name: 用于 UI 显示的通道名称字符串
        """
        self._ensure_channels()
        result = []
        for ch in self._channels:
            # ChannelType 枚举的 name 属性即为 'BaseColor', 'Height' 等
            name = getattr(ch, 'name', None) or str(ch)
            result.append((ch, name))
        return result

    def _get_effective_channels(self):
        """
        根据当前通道选择设置，返回要操作的通道列表。
        单通道模式只返回一个元素的列表，全通道模式返回全部。
        """
        self._ensure_channels()
        selected = self._settings.opacity_channel
        if selected == OnionSkinSettings.ALL_CHANNELS:
            return self._channels

        # 单通道模式
        if selected:
            # 如果 selected 是 ChannelType 枚举对象，直接使用
            if not isinstance(selected, str):
                return [selected]
            # 如果是字符串（初始状态/扫描前），从已缓存的通道中按名称查找
            for ch in self._channels:
                ch_name = getattr(ch, 'name', None) or str(ch)
                if ch_name == selected:
                    return [ch]
            # 找不到则回退到第一个通道
            if self._channels:
                return [self._channels[0]]

        return self._channels

    def invalidate_channel_cache(self):
        """
        通道选择变更后调用，清除有效通道缓存。
        下次 apply() 时会重新验证。
        """
        self._valid_channels = None

    def reset_all_opacities(self):
        """
        将被洋葱皮修改过 opacity 的帧恢复为 1.0（100%）。
        在关闭洋葱皮或停止播放时调用。

        注意：恢复时使用全通道模式，确保所有被修改过的通道都被还原，
        即使当前设置为单通道模式。
        """
        if not self._dirty_opacities:
            return
        self._ensure_channels()
        total = len(self._frames)
        for idx in self._dirty_opacities:
            if 0 <= idx < total and self._frames[idx].is_valid():
                try:
                    # 恢复时始终使用全通道，确保彻底还原
                    _set_opacity_with_channel(
                        self._frames[idx].layer_node, 1.0,
                        self._channels, self._valid_channels)
                except Exception:
                    pass
        self._dirty_opacities.clear()

    def apply(self, current_index: int):
        """
        应用洋葱皮效果（增量更新）。

        性能优化：
        1. 窄化遍历：只计算 [current - before, current + after] 区间内的帧，
           而非全量 range(total)。洋葱皮通常只涉及 3~5 帧。
        2. 增量差分：与上次状态对比，只对发生变化的帧执行 SP API 调用。
        3. 有效通道缓存：首次 set_opacity 成功后记录有效通道，后续跳过无效通道。

        容错机制：
        - current_index 越界时安全返回
        - 单帧操作失败不影响其余帧
        - 整体异常时自动清除缓存，下次重新全量应用

        Args:
            current_index: 当前帧索引 (0-based)
        """
        if not self._settings.enabled or not self._frames:
            return

        total = len(self._frames)
        if not (0 <= current_index < total):
            print(f"[SequenceAnimation] 洋葱皮: current_index={current_index} "
                  f"越界 (total={total})，已忽略")
            return

        try:
            # 根据通道选择获取要操作的通道列表
            effective_channels = self._get_effective_channels()

            # ---- 1. 计算本次需要的状态（窄化遍历） ----
            # 只遍历当前帧 ± 洋葱皮范围，而非全部帧
            new_state: Dict[int, float] = {}
            new_visible: set = set()

            # 当前帧
            new_state[current_index] = 1.0
            new_visible.add(current_index)

            # 前方帧 (before)
            fb = self._settings.frames_before
            for d in range(1, fb + 1):
                idx = current_index - d
                if idx < 0:
                    break
                if fb <= 1:
                    t = 1.0
                else:
                    t = 1.0 - (d - 1) / (fb - 1)
                new_state[idx] = lerp(
                    self._settings.min_opacity,
                    self._settings.max_opacity, t)
                new_visible.add(idx)

            # 后方帧 (after)
            fa = self._settings.frames_after
            for d in range(1, fa + 1):
                idx = current_index + d
                if idx >= total:
                    break
                if fa <= 1:
                    t = 1.0
                else:
                    t = 1.0 - (d - 1) / (fa - 1)
                new_state[idx] = lerp(
                    self._settings.min_opacity,
                    self._settings.max_opacity, t)
                new_visible.add(idx)

            # ---- 2. 增量更新：只操作有变化的帧 ----

            # 2a. 需要隐藏的帧（上次可见，本次不在可见集合中）
            to_hide = self._last_visible_set - new_visible
            for idx in to_hide:
                if 0 <= idx < total and self._frames[idx].is_valid():
                    try:
                        # 恢复 opacity 为 1.0 后再隐藏
                        ok, vc = _set_opacity_with_channel(
                            self._frames[idx].layer_node, 1.0,
                            effective_channels, self._valid_channels)
                        if vc and self._valid_channels is None:
                            self._valid_channels = vc
                        self._frames[idx].layer_node.set_visible(False)
                        # 已恢复为 1.0，从 dirty 中移除
                        self._dirty_opacities.discard(idx)
                    except Exception as e:
                        print(f"[SequenceAnimation] 洋葱皮: 隐藏帧 "
                              f"{self._frames[idx].layer_name} 失败: {e}")

            # 2b. 需要显示或更新 opacity 的帧
            for idx, target_opacity in new_state.items():
                if not self._frames[idx].is_valid():
                    continue  # 跳过失效节点

                old_opacity = self._last_applied.get(idx)
                was_visible = idx in self._last_visible_set

                try:
                    if not was_visible:
                        # 新出现的帧：设置 opacity + 显示
                        ok, vc = _set_opacity_with_channel(
                            self._frames[idx].layer_node, target_opacity,
                            effective_channels, self._valid_channels)
                        if vc and self._valid_channels is None:
                            self._valid_channels = vc
                        self._frames[idx].layer_node.set_visible(True)
                        if abs(target_opacity - 1.0) > 1e-6:
                            self._dirty_opacities.add(idx)
                    elif old_opacity is None or abs(old_opacity - target_opacity) > 1e-6:
                        # opacity 发生变化：只更新 opacity
                        ok, vc = _set_opacity_with_channel(
                            self._frames[idx].layer_node, target_opacity,
                            effective_channels, self._valid_channels)
                        if vc and self._valid_channels is None:
                            self._valid_channels = vc
                        if abs(target_opacity - 1.0) > 1e-6:
                            self._dirty_opacities.add(idx)
                        else:
                            self._dirty_opacities.discard(idx)
                    # 如果 opacity 未变且已可见，跳过（无操作）
                except Exception as e:
                    print(f"[SequenceAnimation] 洋葱皮: 更新帧 "
                          f"{self._frames[idx].layer_name} 失败: {e}")

            # ---- 3. 保存本次状态供下次增量比较 ----
            self._last_applied = new_state
            self._last_visible_set = new_visible

        except Exception as e:
            # 整体异常兜底：清除缓存，下次将执行全量应用
            print(f"[SequenceAnimation] 洋葱皮 apply() 发生意外异常: {e}")
            self._last_applied.clear()
            self._last_visible_set.clear()

    def clear(self, current_index: int = -1):
        """
        清除洋葱皮效果：恢复 opacity 并隐藏前后参考帧。

        关闭洋葱皮时，除了恢复 opacity 为 1.0，还需将洋葱皮
        额外显示的前后帧隐藏，只保留当前帧可见。

        Args:
            current_index: 当前帧索引，该帧保持可见。
                           -1 表示隐藏所有洋葱皮帧。
        """
        # 1. 恢复所有被修改过 opacity 的帧
        self.reset_all_opacities()

        # 2. 隐藏洋葱皮额外显示的前后帧
        total = len(self._frames)
        for idx in self._last_visible_set:
            if idx == current_index:
                continue  # 当前帧保持可见
            if 0 <= idx < total and self._frames[idx].is_valid():
                try:
                    self._frames[idx].layer_node.set_visible(False)
                except Exception as e:
                    print(f"[SequenceAnimation] 洋葱皮 clear: 隐藏帧 "
                          f"{self._frames[idx].layer_name} 失败: {e}")

        self._last_applied.clear()
        self._last_visible_set.clear()
