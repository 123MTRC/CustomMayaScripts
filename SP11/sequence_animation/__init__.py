# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin for Substance Painter 11
序列帧动画工具 —— 在 SP 中逐帧绘制、预览和导出序列帧动画。

用法:
    将 sequence_animation 文件夹放入 SP 的 python/plugins/ 目录，
    在 SP 中启用插件：Python → sequence_animation

作者: Sequence Animation Plugin
版本: 1.0.0
"""

import substance_painter.ui as sp_ui

PLUGIN_NAME = "序列帧动画工具"
PLUGIN_VERSION = "1.0.0"

# 开发调试模式：启用后每次加载插件会 reload 所有子模块，确保代码修改即时生效。
# 发布时请设为 False，避免 reload 在某些 SP 版本下导致状态残留。
_DEV_MODE = True

# 跟踪所有注册到 SP 的 UI 元素，关闭时逐个删除（参照官方 hello_plugin 模式）
plugin_widgets = []


def start_plugin():
    """插件启动入口，由 Substance Painter 调用。"""
    try:
        if _DEV_MODE:
            # 强制重新加载所有子模块，确保代码修改后 reload 能生效
            import importlib
            import sys

            package_name = __name__  # "sequence_animation"
            sub_modules = [
                "utils",
                "frame_scanner",
                "visibility_controller",
                "playback_controller",
                "onion_skin",
                "export_helper",
                "animation_panel",
            ]
            for mod_name in sub_modules:
                full_name = f"{package_name}.{mod_name}"
                if full_name in sys.modules:
                    importlib.reload(sys.modules[full_name])
            print("[SequenceAnimation] DEV_MODE: 子模块已重新加载")

        from .animation_panel import AnimationPanel

        # 创建面板
        panel = AnimationPanel()
        panel.setWindowTitle(PLUGIN_NAME)

        # 注册为 Dock Widget
        sp_ui.add_dock_widget(panel)

        # 确保窗口可见（reload 后 dock 可能默认隐藏）
        panel.show()
        parent_dock = panel.parent()
        if parent_dock is not None:
            parent_dock.show()
            parent_dock.setVisible(True)
            parent_dock.raise_()

        # 记录 widget 以便关闭时清理
        plugin_widgets.append(panel)

        print(f"[SequenceAnimation] {PLUGIN_NAME} v{PLUGIN_VERSION} 已启动")

    except Exception as e:
        import traceback
        print(f"[SequenceAnimation] 启动失败: {e}")
        traceback.print_exc()


def close_plugin():
    """插件关闭入口，由 Substance Painter 调用。"""
    for widget in plugin_widgets:
        try:
            if hasattr(widget, 'cleanup'):
                widget.cleanup()
        except Exception:
            pass
        try:
            sp_ui.delete_ui_element(widget)
        except Exception:
            pass

    plugin_widgets.clear()
    print(f"[SequenceAnimation] {PLUGIN_NAME} 已关闭")
