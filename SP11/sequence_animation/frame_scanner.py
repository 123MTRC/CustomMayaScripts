# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Frame Scanner Module
扫描 Substance Painter 图层栈，识别帧 Group 文件夹并构建帧列表。
"""

import substance_painter.layerstack as layerstack
import substance_painter.textureset as textureset

from .utils import parse_frame_number


class FrameEntry:
    """表示一个帧条目，对应图层栈中的一个 Group 文件夹。"""

    def __init__(self, frame_number: int, layer_node, layer_name: str):
        """
        Args:
            frame_number: 帧编号
            layer_node: substance_painter layerstack 中的图层节点引用
            layer_name: 图层名称
        """
        self.frame_number = frame_number
        self.layer_node = layer_node
        self.layer_name = layer_name

    def __repr__(self):
        return f"FrameEntry(#{self.frame_number}, '{self.layer_name}')"

    def is_valid(self) -> bool:
        """
        检测图层节点引用是否仍然有效。
        SP 中图层可能被用户手动删除/撤销，导致节点失效。

        Returns:
            True 表示节点有效，False 表示节点已失效（stale）
        """
        if self.layer_node is None:
            return False
        try:
            # 尝试访问节点的基本属性来验证有效性
            self.layer_node.get_name()
            return True
        except Exception:
            return False

    def safe_set_visible(self, visible: bool) -> bool:
        """
        安全地设置可见性，捕获节点失效异常。

        Args:
            visible: 是否可见

        Returns:
            True 表示操作成功，False 表示失败（节点可能已失效）
        """
        try:
            self.layer_node.set_visible(visible)
            return True
        except Exception as e:
            print(f"[SequenceAnimation] 设置帧 {self.layer_name} "
                  f"可见性失败 (节点可能已失效): {e}")
            return False

    def safe_is_visible(self) -> bool:
        """安全获取可见性状态，节点失效时返回 True（默认值）。"""
        try:
            return self.layer_node.is_visible()
        except Exception:
            return True

    def get_sub_layer_count(self) -> int:
        """获取该 Group 内的子图层数量。"""
        try:
            sub_layers = self.layer_node.sub_layers()
            return len(sub_layers)
        except Exception:
            return 0


class FrameScanner:
    """
    帧扫描器：扫描当前 Texture Set 的图层栈，
    识别所有符合命名规则的 Group 文件夹，构建帧列表。
    """

    def __init__(self):
        self._frames: list = []
        self._non_frame_layers: list = []
        self._custom_pattern: str = None
        self._active_texture_set_name: str = ""

    @property
    def frames(self) -> list:
        """已排序的帧条目列表。"""
        return self._frames

    @property
    def non_frame_layers(self) -> list:
        """非帧图层列表（常驻层）。"""
        return self._non_frame_layers

    @property
    def active_texture_set_name(self) -> str:
        """最近一次扫描使用的 Texture Set 名称。"""
        return self._active_texture_set_name

    @property
    def frame_count(self) -> int:
        """帧总数。"""
        return len(self._frames)

    def set_custom_pattern(self, pattern: str):
        """
        设置自定义帧命名正则表达式。

        Args:
            pattern: 正则表达式字符串，必须包含一个捕获组用于提取帧编号数字
        """
        self._custom_pattern = pattern if pattern else None

    def scan(self) -> list:
        """
        扫描当前活动 Texture Set 的图层栈。

        Returns:
            排序后的帧条目列表

        Raises:
            RuntimeError: 如果没有活动的 Texture Set
        """
        self._frames.clear()
        self._non_frame_layers.clear()

        # 获取当前活动的 Texture Set Stack
        active_stack = self._get_active_stack()
        if active_stack is None:
            raise RuntimeError("没有找到活动的 Texture Set，请确保项目已打开。")

        # 记录当前扫描的 Texture Set 名称
        self._active_texture_set_name = self._resolve_stack_name(active_stack)

        # 获取图层栈的顶层节点
        root_layers = layerstack.get_root_layer_nodes(active_stack)

        for layer_node in root_layers:
            layer_name = layer_node.get_name()
            layer_type = layer_node.get_type()

            # 只处理 Group (Folder) 类型的图层
            if layer_type == layerstack.NodeType.GroupLayer:
                frame_num = parse_frame_number(layer_name, self._custom_pattern)
                if frame_num is not None:
                    entry = FrameEntry(
                        frame_number=frame_num,
                        layer_node=layer_node,
                        layer_name=layer_name
                    )
                    self._frames.append(entry)
                else:
                    # Group 但名称不符合帧规则 → 常驻层
                    self._non_frame_layers.append(layer_node)
            else:
                # 非 Group 类型 → 常驻层
                self._non_frame_layers.append(layer_node)

        # 按帧编号排序
        self._frames.sort(key=lambda e: e.frame_number)

        return self._frames

    def scan_by_stack_order(self) -> list:
        """
        按图层栈的物理顺序（从下到上）扫描帧 Group，
        不依赖命名规则，所有 Group 都视为帧。

        Returns:
            帧条目列表（按栈顺序，底部 Group 为第 1 帧）
        """
        self._frames.clear()
        self._non_frame_layers.clear()

        active_stack = self._get_active_stack()
        if active_stack is None:
            raise RuntimeError("没有找到活动的 Texture Set，请确保项目已打开。")

        # 记录当前扫描的 Texture Set 名称
        self._active_texture_set_name = self._resolve_stack_name(active_stack)

        root_layers = layerstack.get_root_layer_nodes(active_stack)

        # SP 图层栈列表顺序通常是从上到下，需要反转为从下到上
        groups = []
        non_groups = []
        for layer_node in root_layers:
            layer_type = layer_node.get_type()
            if layer_type == layerstack.NodeType.GroupLayer:
                groups.append(layer_node)
            else:
                non_groups.append(layer_node)

        # 反转使底部 Group 为第 1 帧
        groups.reverse()

        for idx, layer_node in enumerate(groups):
            entry = FrameEntry(
                frame_number=idx + 1,
                layer_node=layer_node,
                layer_name=layer_node.get_name()
            )
            self._frames.append(entry)

        self._non_frame_layers = non_groups

        return self._frames

    def get_frame_by_number(self, frame_number: int):
        """
        根据帧编号获取帧条目。

        Args:
            frame_number: 帧编号

        Returns:
            FrameEntry 或 None
        """
        for entry in self._frames:
            if entry.frame_number == frame_number:
                return entry
        return None

    def get_frame_by_index(self, index: int):
        """
        根据列表索引获取帧条目。

        Args:
            index: 列表索引 (0-based)

        Returns:
            FrameEntry 或 None
        """
        if 0 <= index < len(self._frames):
            return self._frames[index]
        return None

    def get_frame_numbers(self) -> list:
        """获取所有帧编号列表。"""
        return [e.frame_number for e in self._frames]

    def _get_active_stack(self):
        """获取当前活动的 Texture Set Stack。"""
        try:
            active_ts = textureset.get_active_stack()
            return active_ts
        except Exception:
            # 尝试获取第一个可用的 texture set
            try:
                all_ts = textureset.all_texture_sets()
                if all_ts:
                    return all_ts[0].get_stack()
            except Exception:
                pass
        return None

    @staticmethod
    def _resolve_stack_name(stack) -> str:
        """
        从 Stack 对象解析出可读的 Texture Set 名称。

        Args:
            stack: substance_painter textureset Stack 对象

        Returns:
            名称字符串，解析失败时返回 str(stack)
        """
        try:
            # Stack 对象的 material() 方法返回所属的 TextureSet
            ts = stack.material()
            if hasattr(ts, 'name'):
                name = ts.name()
                if name:
                    return str(name)
        except Exception:
            pass
        # 回退：直接转字符串，SP 的 Stack.__str__ 通常返回有意义的名称
        return str(stack)
