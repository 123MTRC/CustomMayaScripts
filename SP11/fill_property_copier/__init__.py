# -*- coding: utf-8 -*-
"""
Fill Property Copier Plugin for Substance 3D Painter
填充属性复制工具 —— 读取图层/Mask 的填充映射方式、UV Wrap、UV 平铺、旋转、偏移等信息，
并应用到其他图层/Mask。新增 BaseColor 纯色颜色的读取、调整与应用功能。

用法:
    将 fill_property_copier 文件夹放入 SP 的 python/plugins/ 目录，
    在 SP 中启用插件：Python → fill_property_copier

版本: 1.1.0
"""

import substance_painter.ui as sp_ui

PLUGIN_NAME = "填充属性复制工具"
PLUGIN_VERSION = "1.1.0"

# 开发调试模式：启用后每次加载插件会 reload 所有子模块
_DEV_MODE = True

plugin_widgets = []


def start_plugin():
    """插件启动入口，由 Substance Painter 调用。"""
    try:
        if _DEV_MODE:
            import importlib
            import sys

            package_name = __name__
            sub_modules = [
                "property_core",
                "copier_panel",
            ]
            for mod_name in sub_modules:
                full_name = f"{package_name}.{mod_name}"
                if full_name in sys.modules:
                    importlib.reload(sys.modules[full_name])
            print("[FillPropertyCopier] DEV_MODE: 子模块已重新加载")

        from .copier_panel import CopierPanel

        panel = CopierPanel()
        panel.setWindowTitle(PLUGIN_NAME)

        sp_ui.add_dock_widget(panel)

        panel.show()
        parent_dock = panel.parent()
        if parent_dock is not None:
            parent_dock.show()
            parent_dock.setVisible(True)
            parent_dock.raise_()

        plugin_widgets.append(panel)
        print(f"[FillPropertyCopier] {PLUGIN_NAME} v{PLUGIN_VERSION} 已启动")

    except Exception as e:
        import traceback
        print(f"[FillPropertyCopier] 启动失败: {e}")
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
    print(f"[FillPropertyCopier] {PLUGIN_NAME} 已关闭")
