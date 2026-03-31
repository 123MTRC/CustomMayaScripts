# -*- coding: utf-8 -*-
"""
Fill Property Copier - UI Panel
基于 PySide6 的 Dock 面板，提供读取填充属性、预览和批量应用的交互界面。
支持 UV 映射和 3D 映射两套参数的分区显示与智能控制。
新增 BaseColor 纯色颜色读取/调整/应用功能。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QGroupBox,
    QTextEdit, QSizePolicy, QFrame,
    QScrollArea, QColorDialog, QSpinBox, QLineEdit,
    QTabWidget, QSlider
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QLinearGradient

from .property_core import (
    FillProperties,
    ApplyResult,
    BaseColorData,
    read_fill_properties,
    apply_fill_properties,
    get_selected_nodes,
    apply_to_selected,
    is_fill_node,
    _get_node_type_name,
    read_basecolor,
    apply_basecolor_to_selected,
    probe_layer_api,
)


# ============================================================
# 样式表
# ============================================================
STYLESHEET = """
QGroupBox {
    font-weight: bold;
    border: 1px solid #555;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    min-height: 26px;
    padding: 4px 10px;
    border-radius: 3px;
    border: 1px solid #555;
    background-color: #3a3a3a;
    color: #ddd;
}
QPushButton:hover {
    background-color: #4a4a4a;
    border-color: #777;
}
QPushButton:pressed {
    background-color: #2a6496;
}
QPushButton:disabled {
    background-color: #2a2a2a;
    color: #666;
    border-color: #444;
}
QPushButton#readBtn {
    background-color: #2a5a2a;
    border-color: #3a7a3a;
    font-weight: bold;
}
QPushButton#readBtn:hover {
    background-color: #3a7a3a;
}
QPushButton#applyBtn {
    background-color: #2a4a8a;
    border-color: #3a5aaa;
    font-weight: bold;
}
QPushButton#applyBtn:hover {
    background-color: #3a5aaa;
}
QPushButton#colorReadBtn {
    background-color: #6a3a2a;
    border-color: #8a5a3a;
    font-weight: bold;
}
QPushButton#colorReadBtn:hover {
    background-color: #8a5a3a;
}
QPushButton#colorApplyBtn {
    background-color: #2a4a6a;
    border-color: #3a5a8a;
    font-weight: bold;
}
QPushButton#colorApplyBtn:hover {
    background-color: #3a5a8a;
}
QPushButton#colorPickBtn {
    background-color: #4a3a6a;
    border-color: #6a5a8a;
}
QPushButton#colorPickBtn:hover {
    background-color: #6a5a8a;
}
QPushButton#probeBtn {
    background-color: #5a5a2a;
    border-color: #7a7a3a;
    font-size: 10px;
}
QPushButton#probeBtn:hover {
    background-color: #7a7a3a;
}
QTextEdit {
    border: 1px solid #555;
    border-radius: 3px;
    background-color: #1e1e1e;
    color: #ccc;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    padding: 4px;
}
QCheckBox {
    spacing: 6px;
    color: #ccc;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}
QCheckBox:disabled {
    color: #666;
}
QLabel {
    color: #ccc;
}
QLabel#statusLabel {
    color: #999;
    font-style: italic;
    padding: 2px 0;
}
QLabel#resultLabel {
    padding: 6px 8px;
    border-radius: 4px;
    font-size: 11px;
    line-height: 1.4;
}
QLabel#resultLabel[resultType="success"] {
    background-color: #1a3a1a;
    border: 1px solid #2a6a2a;
    color: #8fdf8f;
}
QLabel#resultLabel[resultType="warning"] {
    background-color: #3a3a1a;
    border: 1px solid #6a6a2a;
    color: #dfdf8f;
}
QLabel#resultLabel[resultType="error"] {
    background-color: #3a1a1a;
    border: 1px solid #6a2a2a;
    color: #df8f8f;
}
QLabel#resultLabel[resultType="info"] {
    background-color: #1a2a3a;
    border: 1px solid #2a4a6a;
    color: #8fbfdf;
}
QLabel#resultLabel[resultType="faded"] {
    background-color: transparent;
    border: none;
    color: #666;
}
QLabel#headerLabel {
    font-size: 13px;
    font-weight: bold;
    color: #ddd;
    padding: 2px 0;
}
QLabel#sectionLabel {
    font-size: 11px;
    color: #aaa;
    padding: 2px 0 0 4px;
}
QLabel#hintLabel {
    font-size: 10px;
    color: #888;
    font-style: italic;
    padding: 0 0 0 20px;
}
QFrame#separator {
    background-color: #555;
    min-height: 1px;
    max-height: 1px;
}
QTabWidget::pane {
    border: 1px solid #555;
    border-radius: 3px;
    padding: 4px;
}
QTabBar::tab {
    background: #2a2a2a;
    color: #aaa;
    padding: 6px 16px;
    border: 1px solid #555;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #3a3a3a;
    color: #ddd;
    font-weight: bold;
}
QTabBar::tab:hover {
    background: #4a4a4a;
}
QSlider::groove:horizontal {
    background: #2a2a2a;
    border: 1px solid #555;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #8a8a8a;
    border: 1px solid #aaa;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #aaa;
}
QSlider::sub-page:horizontal {
    background: #4a6a9a;
    border-radius: 3px;
}
QLabel.rgbValue {
    background-color: #2a2a2a;
    color: #ccc;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 2px 4px;
    min-width: 30px;
}
QLineEdit {
    background-color: #2a2a2a;
    color: #ccc;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 2px 4px;
}
"""


class ColorPreviewWidget(QWidget):
    """颜色预览小方块，点击可打开颜色选择器。"""

    color_changed = Signal(QColor)

    def __init__(self, parent=None, size=48):
        super().__init__(parent)
        self._color = QColor(128, 128, 128)
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点击打开颜色选择器")

    def get_color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def set_color_rgb(self, r: int, g: int, b: int):
        self._color = QColor(r, g, b)
        self.update()

    def set_color_float(self, r: float, g: float, b: float):
        self._color = QColor(
            max(0, min(255, int(r * 255 + 0.5))),
            max(0, min(255, int(g * 255 + 0.5))),
            max(0, min(255, int(b * 255 + 0.5))),
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 棋盘格背景（表示透明度参考）
        checker_size = 6
        for row in range(self._size // checker_size + 1):
            for col in range(self._size // checker_size + 1):
                if (row + col) % 2 == 0:
                    painter.fillRect(
                        col * checker_size, row * checker_size,
                        checker_size, checker_size,
                        QColor(200, 200, 200)
                    )
                else:
                    painter.fillRect(
                        col * checker_size, row * checker_size,
                        checker_size, checker_size,
                        QColor(150, 150, 150)
                    )

        # 颜色填充
        painter.setBrush(QBrush(self._color))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRoundedRect(0, 0, self._size - 1, self._size - 1, 3, 3)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            color = QColorDialog.getColor(
                self._color, self, "选择颜色",
                QColorDialog.ShowAlphaChannel
            )
            if color.isValid():
                self._color = color
                self.update()
                self.color_changed.emit(color)


class CopierPanel(QWidget):
    """填充属性复制工具主面板（投射属性 + BaseColor 纯色颜色）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stored_props: FillProperties = None
        self._stored_color: BaseColorData = None
        self._build_ui()
        self.setStyleSheet(STYLESHEET)
        self._update_ui_state()

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- 标题 ----
        header = QLabel("📋 填充属性复制工具")
        header.setObjectName("headerLabel")
        header.setAlignment(Qt.AlignCenter)
        root.addWidget(header)

        # ---- 分隔线 ----
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        # ---- Tab 选项卡 ----
        self._tab_widget = QTabWidget()
        root.addWidget(self._tab_widget)

        # Tab 1: 投射属性
        projection_tab = QWidget()
        self._build_projection_tab(projection_tab)
        self._tab_widget.addTab(projection_tab, "🗺 投射属性")

        # Tab 2: BaseColor 颜色
        color_tab = QWidget()
        self._build_color_tab(color_tab)
        self._tab_widget.addTab(color_tab, "🎨 BaseColor")

        # ---- 结果提示区域 ----
        self._result_label = QLabel("")
        self._result_label.setObjectName("resultLabel")
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        root.addWidget(self._result_label)

        # 提示自动淡化定时器
        self._result_fade_timer = QTimer(self)
        self._result_fade_timer.setSingleShot(True)
        self._result_fade_timer.timeout.connect(self._fade_result)

        # ---- 状态栏 ----
        self._status_label = QLabel("就绪 — 请先选中一个图层或效果后操作")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        root.addStretch()

    # ============================================================
    # Tab 1: 投射属性
    # ============================================================
    def _build_projection_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ---- 读取区域 ----
        layout.addWidget(self._build_read_section())

        # ---- 属性预览区域 ----
        layout.addWidget(self._build_preview_section())

        # ---- 应用选项 ----
        layout.addWidget(self._build_options_section())

        # ---- 应用区域 ----
        layout.addWidget(self._build_apply_section())

        layout.addStretch()

    # ============================================================
    # Tab 2: BaseColor 颜色
    # ============================================================
    def _build_color_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ---- 读取区域 ----
        layout.addWidget(self._build_color_read_section())

        # ---- 颜色编辑区域 ----
        layout.addWidget(self._build_color_edit_section())

        # ---- 颜色预览信息 ----
        layout.addWidget(self._build_color_info_section())

        # ---- 应用区域 ----
        layout.addWidget(self._build_color_apply_section())

        # ---- API 探测工具（调试用）----
        layout.addWidget(self._build_probe_section())

        layout.addStretch()

    # ---------- 读取区域 ----------
    def _build_read_section(self) -> QGroupBox:
        grp = QGroupBox("① 读取属性")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        desc = QLabel(
            "选中一个填充图层（Fill Layer）或效果（Fill Effect），\n"
            "点击下方按钮读取其填充属性。"
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._read_btn = QPushButton("📖 从选中图层读取属性")
        self._read_btn.setObjectName("readBtn")
        self._read_btn.setToolTip(
            "读取当前选中的填充图层/效果的映射方式、UV 转换、\n"
            "3D 映射设置等所有参数。"
        )
        self._read_btn.clicked.connect(self._on_read_clicked)
        v.addWidget(self._read_btn)

        return grp

    # ---------- 预览区域 ----------
    def _build_preview_section(self) -> QGroupBox:
        grp = QGroupBox("已记录的属性")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setMaximumHeight(220)
        self._preview_text.setMinimumHeight(100)
        self._preview_text.setPlaceholderText("尚未读取任何属性...")
        v.addWidget(self._preview_text)

        # 清除按钮
        self._clear_btn = QPushButton("🗑 清除记录")
        self._clear_btn.setToolTip("清除已记录的属性")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        v.addWidget(self._clear_btn)

        return grp

    # ---------- 应用选项 ----------
    def _build_options_section(self) -> QGroupBox:
        grp = QGroupBox("② 选择要应用的属性")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        # ==== 映射模式 ====
        self._cb_projection = QCheckBox("映射模式 (Projection Mode)")
        self._cb_projection.setChecked(True)
        self._cb_projection.setToolTip(
            "UV Projection / Tri-planar / Planar 等映射方式。\n"
            "勾选此项会先切换目标的映射模式，确保后续参数结构一致。"
        )
        v.addWidget(self._cb_projection)

        # ==== 基础 UV 转换区 ====
        uv_section_label = QLabel("▸ UV 转换")
        uv_section_label.setObjectName("sectionLabel")
        v.addWidget(uv_section_label)

        self._cb_uv_scale = QCheckBox("UV 平铺比例 (Tiling/Scale)")
        self._cb_uv_scale.setChecked(True)
        self._cb_uv_scale.setToolTip("UV 纹理的缩放/平铺比例（所有映射模式共有）")
        v.addWidget(self._cb_uv_scale)

        self._cb_uv_rotation = QCheckBox("UV 旋转 (Rotation)")
        self._cb_uv_rotation.setChecked(True)
        self._cb_uv_rotation.setToolTip("UV 纹理的旋转角度（所有映射模式共有）")
        v.addWidget(self._cb_uv_rotation)

        self._cb_uv_offset = QCheckBox("UV 偏移 (Offset)")
        self._cb_uv_offset.setChecked(True)
        self._cb_uv_offset.setToolTip("UV 纹理的位移偏移（仅 UV 映射模式）")
        v.addWidget(self._cb_uv_offset)

        self._cb_uv_wrap = QCheckBox("UV Wrap 模式")
        self._cb_uv_wrap.setChecked(True)
        self._cb_uv_wrap.setToolTip("Repeat / Clamp 等 UV 包裹模式（仅 UV 映射模式）")
        v.addWidget(self._cb_uv_wrap)

        # ==== 3D 映射区 ====
        self._3d_section_label = QLabel("▸ 3D 映射设置")
        self._3d_section_label.setObjectName("sectionLabel")
        v.addWidget(self._3d_section_label)

        self._3d_hint_label = QLabel("仅 Tri-planar / Planar 等映射模式可用")
        self._3d_hint_label.setObjectName("hintLabel")
        v.addWidget(self._3d_hint_label)

        self._cb_3d_offset = QCheckBox("3D 偏移 (Offset XYZ)")
        self._cb_3d_offset.setChecked(True)
        self._cb_3d_offset.setToolTip("三维空间中的投射偏移位置")
        v.addWidget(self._cb_3d_offset)

        self._cb_3d_rotation = QCheckBox("3D 旋转 (Rotation XYZ)")
        self._cb_3d_rotation.setChecked(True)
        self._cb_3d_rotation.setToolTip("三维空间中的投射旋转角度")
        v.addWidget(self._cb_3d_rotation)

        self._cb_3d_scale = QCheckBox("3D 比例 (Scale XYZ)")
        self._cb_3d_scale.setChecked(True)
        self._cb_3d_scale.setToolTip("三维空间中的投射缩放比例")
        v.addWidget(self._cb_3d_scale)

        self._cb_filtering_mode = QCheckBox("过滤模式 (Filtering Mode)")
        self._cb_filtering_mode.setChecked(True)
        self._cb_filtering_mode.setToolTip("纹理过滤方式：Bilinear HQ / Bilinear Sharp / Nearest")
        v.addWidget(self._cb_filtering_mode)

        self._cb_hardness = QCheckBox("硬度 (Hardness)")
        self._cb_hardness.setChecked(True)
        self._cb_hardness.setToolTip("Tri-planar 混合边缘的硬度值")
        v.addWidget(self._cb_hardness)

        self._cb_shape_crop_mode = QCheckBox("裁剪模式 (Shape Crop Mode)")
        self._cb_shape_crop_mode.setChecked(True)
        self._cb_shape_crop_mode.setToolTip("投射超出形状范围的裁剪行为")
        v.addWidget(self._cb_shape_crop_mode)

        # ==== 全选/取消全选 ====
        h = QHBoxLayout()
        h.setSpacing(4)
        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedWidth(60)
        select_all_btn.clicked.connect(lambda: self._set_all_checkboxes(True))
        h.addWidget(select_all_btn)
        deselect_all_btn = QPushButton("取消全选")
        deselect_all_btn.setFixedWidth(80)
        deselect_all_btn.clicked.connect(lambda: self._set_all_checkboxes(False))
        h.addWidget(deselect_all_btn)
        h.addStretch()
        v.addLayout(h)

        return grp

    # ---------- 应用区域 ----------
    def _build_apply_section(self) -> QGroupBox:
        grp = QGroupBox("③ 应用到目标")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        desc = QLabel(
            "选中一个或多个目标图层/效果，点击下方按钮应用属性。\n"
            "支持多选（Ctrl/Shift+点击），可一键应用到批量图层。\n"
            "跨映射模式时，不兼容的参数会被自动跳过并提示。"
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._apply_btn = QPushButton("✅ 应用到选中的图层")
        self._apply_btn.setObjectName("applyBtn")
        self._apply_btn.setToolTip(
            "将记录的属性应用到当前选中的所有图层/效果。\n"
            "操作支持 Ctrl+Z 撤销。"
        )
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        v.addWidget(self._apply_btn)

        return grp

    # ---------- 颜色读取区域 ----------
    def _build_color_read_section(self) -> QGroupBox:
        grp = QGroupBox("① 读取 BaseColor")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        desc = QLabel(
            "选中一个填充图层（Fill Layer），点击下方按钮\n"
            "读取其 BaseColor 通道的纯色颜色值。"
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._color_read_btn = QPushButton("🎨 从选中图层读取 BaseColor")
        self._color_read_btn.setObjectName("colorReadBtn")
        self._color_read_btn.setToolTip(
            "读取当前选中填充图层的 BaseColor 纯色颜色值。\n"
            "读取后可在下方调整颜色，再应用到其他图层。"
        )
        self._color_read_btn.clicked.connect(self._on_color_read_clicked)
        v.addWidget(self._color_read_btn)

        return grp

    # ---------- 颜色编辑区域 ----------
    def _build_color_edit_section(self) -> QGroupBox:
        grp = QGroupBox("② 调整颜色")
        v = QVBoxLayout(grp)
        v.setSpacing(6)

        # 颜色预览 + 选择器按钮
        h_preview = QHBoxLayout()
        h_preview.setSpacing(8)

        self._color_preview = ColorPreviewWidget(size=48)
        self._color_preview.color_changed.connect(self._on_color_picker_changed)
        h_preview.addWidget(self._color_preview)

        # 右侧信息
        v_info = QVBoxLayout()
        v_info.setSpacing(2)

        self._color_hex_label = QLabel("HEX: #808080")
        self._color_hex_label.setObjectName("sectionLabel")
        v_info.addWidget(self._color_hex_label)

        self._color_float_label = QLabel("Float: (0.5020, 0.5020, 0.5020)")
        self._color_float_label.setObjectName("hintLabel")
        v_info.addWidget(self._color_float_label)

        pick_btn = QPushButton("🖌 打开调色板")
        pick_btn.setObjectName("colorPickBtn")
        pick_btn.setToolTip("打开系统颜色选择器")
        pick_btn.clicked.connect(self._on_open_color_picker)
        v_info.addWidget(pick_btn)

        h_preview.addLayout(v_info)
        h_preview.addStretch()
        v.addLayout(h_preview)

        # ---------- RGB 滑块 ----------
        rgb_header = QLabel("RGB")
        rgb_header.setStyleSheet("color: #aaa; font-weight: bold; font-size: 11px; border: none; background: transparent; padding: 2px 0;")
        v.addWidget(rgb_header)

        rgb_grid = QVBoxLayout()
        rgb_grid.setSpacing(3)

        for label_text, slider_attr, label_attr, color_accent in [
            ("R:", "_slider_r", "_val_r", "#cc4444"),
            ("G:", "_slider_g", "_val_g", "#44aa44"),
            ("B:", "_slider_b", "_val_b", "#4488cc"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(20)
            lbl.setStyleSheet(f"color: {color_accent}; font-weight: bold; border: none; background: transparent;")
            row.addWidget(lbl)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setValue(128)
            slider.setMinimumWidth(80)
            slider.valueChanged.connect(self._on_rgb_slider_changed)
            setattr(self, slider_attr, slider)
            row.addWidget(slider, 1)

            val_label = QLabel("128")
            val_label.setFixedWidth(32)
            val_label.setAlignment(Qt.AlignCenter)
            val_label.setProperty("class", "rgbValue")
            setattr(self, label_attr, val_label)
            row.addWidget(val_label)

            rgb_grid.addLayout(row)

        v.addLayout(rgb_grid)

        # ---------- HSV 滑块 ----------
        hsv_header = QLabel("HSV")
        hsv_header.setStyleSheet("color: #aaa; font-weight: bold; font-size: 11px; border: none; background: transparent; padding: 2px 0;")
        v.addWidget(hsv_header)

        hsv_grid = QVBoxLayout()
        hsv_grid.setSpacing(3)

        # H: 0-359, S: 0-255, V: 0-255
        for label_text, slider_attr, label_attr, color_accent, max_val, init_val in [
            ("H:", "_slider_h", "_val_h", "#cc8844", 359, 0),
            ("S:", "_slider_s", "_val_s", "#aa44aa", 255, 0),
            ("V:", "_slider_v", "_val_v", "#44aaaa", 255, 128),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(20)
            lbl.setStyleSheet(f"color: {color_accent}; font-weight: bold; border: none; background: transparent;")
            row.addWidget(lbl)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, max_val)
            slider.setValue(init_val)
            slider.setMinimumWidth(80)
            slider.valueChanged.connect(self._on_hsv_slider_changed)
            setattr(self, slider_attr, slider)
            row.addWidget(slider, 1)

            val_label = QLabel(str(init_val))
            val_label.setFixedWidth(32)
            val_label.setAlignment(Qt.AlignCenter)
            val_label.setProperty("class", "rgbValue")
            setattr(self, label_attr, val_label)
            row.addWidget(val_label)

            hsv_grid.addLayout(row)

        v.addLayout(hsv_grid)

        # HEX 输入框
        hex_row = QHBoxLayout()
        hex_row.setSpacing(4)
        hex_row.addWidget(QLabel("HEX:"))
        self._hex_input = QLineEdit("#808080")
        self._hex_input.setMaxLength(7)
        self._hex_input.setFixedWidth(80)
        self._hex_input.setToolTip("输入 #RRGGBB 格式的十六进制颜色值")
        self._hex_input.editingFinished.connect(self._on_hex_input_changed)
        hex_row.addWidget(self._hex_input)
        hex_row.addStretch()
        v.addLayout(hex_row)

        # ---------- 实时预览开关 ----------
        self._live_preview_cb = QCheckBox("🔴 实时预览（拖动滑块即时应用到选中图层）")
        self._live_preview_cb.setChecked(False)
        self._live_preview_cb.setToolTip(
            "开启后，拖动 RGB/HSV 滑块或修改 HEX 时，\n"
            "会自动将颜色实时推送到当前选中的填充图层。\n"
            "关闭后需手动点击「应用颜色」按钮。"
        )
        self._live_preview_cb.toggled.connect(self._on_live_preview_toggled)
        v.addWidget(self._live_preview_cb)

        # 防抖定时器（避免滑块拖动时频繁调用 API）
        self._live_apply_timer = QTimer()
        self._live_apply_timer.setSingleShot(True)
        self._live_apply_timer.setInterval(80)  # 80ms 防抖
        self._live_apply_timer.timeout.connect(self._do_live_apply)

        return grp

    # ---------- 颜色信息区域 ----------
    def _build_color_info_section(self) -> QGroupBox:
        grp = QGroupBox("颜色信息")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        self._color_info_text = QTextEdit()
        self._color_info_text.setReadOnly(True)
        self._color_info_text.setMaximumHeight(100)
        self._color_info_text.setMinimumHeight(60)
        self._color_info_text.setPlaceholderText("尚未读取 BaseColor 颜色...")
        v.addWidget(self._color_info_text)

        # 清除按钮
        self._color_clear_btn = QPushButton("🗑 清除颜色记录")
        self._color_clear_btn.setToolTip("清除已读取的颜色数据")
        self._color_clear_btn.clicked.connect(self._on_color_clear_clicked)
        v.addWidget(self._color_clear_btn)

        return grp

    # ---------- 颜色应用区域 ----------
    def _build_color_apply_section(self) -> QGroupBox:
        grp = QGroupBox("③ 应用颜色到目标")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        desc = QLabel(
            "选中一个或多个目标填充图层，点击下方按钮\n"
            "将调整好的颜色应用到它们的 BaseColor 通道。\n"
            "操作支持 Ctrl+Z 撤销。"
        )
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._color_apply_btn = QPushButton("✅ 应用颜色到选中图层")
        self._color_apply_btn.setObjectName("colorApplyBtn")
        self._color_apply_btn.setToolTip(
            "将当前颜色应用到选中图层的 BaseColor 通道。"
        )
        self._color_apply_btn.clicked.connect(self._on_color_apply_clicked)
        v.addWidget(self._color_apply_btn)

        return grp

    # ---------- API 探测区域 ----------
    def _build_probe_section(self) -> QGroupBox:
        grp = QGroupBox("🔧 API 探测 (调试)")
        v = QVBoxLayout(grp)
        v.setSpacing(4)

        desc = QLabel(
            "如果颜色读取失败，点击下方按钮探测当前选中\n"
            "图层的 API 信息，结果会输出到 SP 控制台日志。"
        )
        desc.setWordWrap(True)
        desc.setObjectName("hintLabel")
        v.addWidget(desc)

        self._probe_btn = QPushButton("🔍 探测选中图层 API")
        self._probe_btn.setObjectName("probeBtn")
        self._probe_btn.setToolTip(
            "探测选中图层的可用 API 方法/属性，\n"
            "输出到 Substance Painter 的 Python 控制台日志。\n"
            "如果读取颜色失败，请运行此探测并将日志发给开发者。"
        )
        self._probe_btn.clicked.connect(self._on_probe_clicked)
        v.addWidget(self._probe_btn)

        return grp

    # ============================================================
    # 槽函数 - 投射属性
    # ============================================================
    def _on_read_clicked(self):
        """读取选中图层的填充属性。"""
        selected = get_selected_nodes()

        if not selected:
            self._show_result("⚠ 请先在图层面板中选中一个图层或效果。", "warning")
            return

        if len(selected) > 1:
            self._set_status(
                f"当前选中了 {len(selected)} 个节点，将从第一个节点读取属性。"
            )

        source_node = selected[0]
        source_name = source_node.get_name()
        source_type = _get_node_type_name(source_node)

        # 尝试读取属性
        props = read_fill_properties(source_node)

        if props is None:
            self._show_result(
                f"⚠ 无法从 \"{source_name}\" ({source_type}) 读取填充属性。\n"
                f"请确保选中的是填充图层（Fill Layer）或填充效果（Fill Effect）。",
                "error"
            )
            return

        self._stored_props = props
        self._update_preview()
        self._update_ui_state()

        mode_hint = ""
        if props.has_3d_params:
            mode_hint = "（含 3D 映射参数）"
        self._set_status(f"✅ 已从 \"{source_name}\" 读取属性 {mode_hint}")

    def _on_clear_clicked(self):
        """清除记录的属性。"""
        self._stored_props = None
        self._preview_text.clear()
        self._preview_text.setPlaceholderText("尚未读取任何属性...")
        self._update_ui_state()
        self._set_status("已清除记录的属性")

    def _on_apply_clicked(self):
        """将记录的属性应用到选中的图层。"""
        if self._stored_props is None or not self._stored_props.is_valid():
            self._show_result("⚠ 请先读取一个图层的填充属性。", "warning")
            return

        selected = get_selected_nodes()
        if not selected:
            self._show_result("⚠ 请先在图层面板中选中目标图层。", "warning")
            return

        # 收集所有启用的选项
        opts = self._get_apply_options()

        if not any(opts.values()):
            self._show_result("⚠ 请至少勾选一项要应用的属性。", "warning")
            return

        # 执行应用
        results = apply_to_selected(self._stored_props, **opts)

        if not results:
            self._set_status("⚠️ 没有节点被处理")
            return

        # 构建结果报告
        self._show_apply_results(results)

    def _get_apply_options(self) -> dict:
        """从 UI 复选框收集所有应用选项。"""
        return {
            "apply_projection_mode": self._cb_projection.isChecked(),
            "apply_uv_scale": self._cb_uv_scale.isChecked(),
            "apply_uv_rotation": self._cb_uv_rotation.isChecked(),
            "apply_uv_offset": self._cb_uv_offset.isChecked(),
            "apply_uv_wrap": self._cb_uv_wrap.isChecked(),
            "apply_3d_offset": self._cb_3d_offset.isChecked(),
            "apply_3d_rotation": self._cb_3d_rotation.isChecked(),
            "apply_3d_scale": self._cb_3d_scale.isChecked(),
            "apply_filtering_mode": self._cb_filtering_mode.isChecked(),
            "apply_hardness": self._cb_hardness.isChecked(),
            "apply_shape_crop_mode": self._cb_shape_crop_mode.isChecked(),
        }

    def _show_apply_results(self, results: list):
        """显示应用结果的详细报告（面板内提示）。"""
        total_applied = 0
        total_skipped = 0
        total_errors = 0
        detail_lines = []

        for r in results:
            icon = "✅" if r.success else "❌"
            parts = []
            if r.applied:
                total_applied += len(r.applied)
                parts.append(f"✔ {', '.join(r.applied)}")
            if r.skipped:
                total_skipped += len(r.skipped)
                parts.append(f"⊘ {', '.join(r.skipped)}")
            if r.errors:
                total_errors += len(r.errors)
                parts.append(f"✘ {', '.join(r.errors)}")
            detail_lines.append(f"{icon} {r.layer_name}  {' | '.join(parts)}")

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        # 状态栏摘要
        status_parts = [f"应用 {total_applied} 项"]
        if total_skipped > 0:
            status_parts.append(f"跳过 {total_skipped} 项")
        if total_errors > 0:
            status_parts.append(f"失败 {total_errors} 项")
        self._set_status(f"✅ {', '.join(status_parts)}（{len(results)} 个图层）")

        # 面板内提示
        if total_errors == 0 and total_skipped == 0:
            msg = f"✅ 已成功应用到 {success_count} 个图层"
            if len(results) <= 5:
                msg += "\n" + "\n".join(detail_lines)
            self._show_result(msg, "success")
        elif total_errors == 0 and total_skipped > 0:
            msg = (f"✅ 应用 {total_applied} 项，跳过 {total_skipped} 项不兼容参数\n"
                   + "\n".join(detail_lines))
            self._show_result(msg, "warning")
        else:
            msg = (f"⚠ 成功 {success_count} 个，失败 {fail_count} 个\n"
                   + "\n".join(detail_lines))
            self._show_result(msg, "error", duration_ms=12000)

    # ============================================================
    # 槽函数 - BaseColor 颜色
    # ============================================================
    def _on_color_read_clicked(self):
        """读取选中图层的 BaseColor 颜色。"""
        selected = get_selected_nodes()

        if not selected:
            self._show_result("⚠ 请先在图层面板中选中一个填充图层。", "warning")
            return

        if len(selected) > 1:
            self._set_status(
                f"当前选中了 {len(selected)} 个节点，将从第一个节点读取颜色。"
            )

        source_node = selected[0]
        source_name = source_node.get_name()

        # 读取 BaseColor
        color_data = read_basecolor(source_node, "BaseColor")

        if color_data is None or not color_data.valid:
            self._show_result(
                f"⚠ 无法从 \"{source_name}\" 读取 BaseColor 纯色颜色。\n"
                f"可能原因：通道使用纹理而非纯色 / 不是填充图层\n"
                f"建议：点击「API 探测」按钮获取详细信息。",
                "error"
            )
            return

        self._stored_color = color_data

        # 更新 UI 中的颜色显示
        self._sync_color_to_ui(color_data.r, color_data.g, color_data.b)
        self._update_color_info()
        self._update_ui_state()

        hex_str = color_data.to_hex()
        self._set_status(
            f"🎨 已从 \"{source_name}\" 读取 BaseColor: {hex_str}"
        )

    def _on_color_clear_clicked(self):
        """清除已读取的颜色数据。"""
        self._stored_color = None
        self._color_info_text.clear()
        self._color_info_text.setPlaceholderText("尚未读取 BaseColor 颜色...")
        self._color_preview.set_color_rgb(128, 128, 128)
        self._slider_r.setValue(128)
        self._slider_g.setValue(128)
        self._slider_b.setValue(128)
        self._val_r.setText("128")
        self._val_g.setText("128")
        self._val_b.setText("128")
        self._slider_h.setValue(0)
        self._slider_s.setValue(0)
        self._slider_v.setValue(128)
        self._val_h.setText("0")
        self._val_s.setText("0")
        self._val_v.setText("128")
        self._hex_input.setText("#808080")
        self._color_hex_label.setText("HEX: #808080")
        self._color_float_label.setText("Float: (0.5020, 0.5020, 0.5020)")
        self._update_ui_state()
        self._set_status("已清除颜色记录")

    def _on_color_apply_clicked(self):
        """将调整好的颜色应用到选中图层。"""
        selected = get_selected_nodes()
        if not selected:
            self._show_result("⚠ 请先在图层面板中选中目标图层。", "warning")
            return

        # 从当前 UI 获取颜色值
        r = self._slider_r.value()
        g = self._slider_g.value()
        b = self._slider_b.value()

        color_data = BaseColorData(
            r=r / 255.0,
            g=g / 255.0,
            b=b / 255.0,
            a=1.0,
            source_layer_name="用户调整",
            channel_name="BaseColor",
            valid=True,
            api_method="manual",
        )

        # 执行应用
        results = apply_basecolor_to_selected(color_data, "BaseColor")

        if not results:
            self._set_status("⚠️ 没有节点被处理")
            return

        # 构建报告
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        hex_str = color_data.to_hex()

        if fail_count == 0:
            self._set_status(
                f"🎨 已应用颜色 {hex_str} 到 {success_count} 个图层"
            )
            self._show_result(
                f"🎨 已将 BaseColor 颜色 {hex_str} 应用到 {success_count} 个图层",
                "success"
            )
        else:
            detail_lines = []
            for r in results:
                icon = "✅" if r.success else "❌"
                err_info = f" ✘ {', '.join(r.errors)}" if r.errors else ""
                detail_lines.append(f"{icon} {r.layer_name}{err_info}")
            detail = "\n".join(detail_lines)

            self._set_status(
                f"🎨 成功 {success_count}, 失败 {fail_count}"
            )
            self._show_result(
                f"⚠ 颜色应用：成功 {success_count}，失败 {fail_count}\n{detail}",
                "error", duration_ms=12000
            )

    def _on_color_picker_changed(self, color: QColor):
        """颜色选择器变更后同步到 RGB 输入框。"""
        self._sync_color_to_ui_from_qcolor(color)

    def _on_open_color_picker(self):
        """打开颜色选择器对话框。"""
        current_color = self._color_preview.get_color()
        color = QColorDialog.getColor(
            current_color, self, "选择 BaseColor 颜色"
        )
        if color.isValid():
            self._sync_color_to_ui_from_qcolor(color)

    def _on_rgb_slider_changed(self):
        """RGB 滑块变更后同步数值标签、HSV 滑块、预览和 HEX。"""
        r = self._slider_r.value()
        g = self._slider_g.value()
        b = self._slider_b.value()
        self._val_r.setText(str(r))
        self._val_g.setText(str(g))
        self._val_b.setText(str(b))

        # 同步到 HSV 滑块（阻止信号避免循环）
        color = QColor(r, g, b)
        h, s, v, _ = color.getHsv()
        if h < 0:
            h = 0  # 灰色时 Qt 返回 -1
        self._slider_h.blockSignals(True)
        self._slider_s.blockSignals(True)
        self._slider_v.blockSignals(True)
        self._slider_h.setValue(h)
        self._slider_s.setValue(s)
        self._slider_v.setValue(v)
        self._slider_h.blockSignals(False)
        self._slider_s.blockSignals(False)
        self._slider_v.blockSignals(False)
        self._val_h.setText(str(h))
        self._val_s.setText(str(s))
        self._val_v.setText(str(v))

        self._color_preview.set_color_rgb(r, g, b)
        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hex_str)
        self._hex_input.blockSignals(False)
        self._color_hex_label.setText(f"HEX: {hex_str}")
        self._color_float_label.setText(
            f"Float: ({r/255:.4f}, {g/255:.4f}, {b/255:.4f})"
        )

        # 实时预览
        self._schedule_live_apply()

    def _on_hsv_slider_changed(self):
        """HSV 滑块变更后同步到 RGB 滑块、数值标签、预览和 HEX。"""
        h = self._slider_h.value()
        s = self._slider_s.value()
        v = self._slider_v.value()
        self._val_h.setText(str(h))
        self._val_s.setText(str(s))
        self._val_v.setText(str(v))

        # HSV → RGB
        color = QColor.fromHsv(h, s, v)
        r, g, b = color.red(), color.green(), color.blue()

        # 同步到 RGB 滑块（阻止信号避免循环）
        self._slider_r.blockSignals(True)
        self._slider_g.blockSignals(True)
        self._slider_b.blockSignals(True)
        self._slider_r.setValue(r)
        self._slider_g.setValue(g)
        self._slider_b.setValue(b)
        self._slider_r.blockSignals(False)
        self._slider_g.blockSignals(False)
        self._slider_b.blockSignals(False)
        self._val_r.setText(str(r))
        self._val_g.setText(str(g))
        self._val_b.setText(str(b))

        self._color_preview.set_color_rgb(r, g, b)
        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hex_str)
        self._hex_input.blockSignals(False)
        self._color_hex_label.setText(f"HEX: {hex_str}")
        self._color_float_label.setText(
            f"Float: ({r/255:.4f}, {g/255:.4f}, {b/255:.4f})"
        )

        # 实时预览
        self._schedule_live_apply()

    def _on_hex_input_changed(self):
        """HEX 输入框确认后同步到 RGB 和预览。"""
        hex_str = self._hex_input.text().strip()
        if not hex_str.startswith('#'):
            hex_str = '#' + hex_str
        try:
            color = QColor(hex_str)
            if color.isValid():
                self._sync_color_to_ui_from_qcolor(color)
        except Exception:
            pass

    # ============================================================
    # 实时预览
    # ============================================================
    def _on_live_preview_toggled(self, checked: bool):
        """实时预览开关切换。"""
        if checked:
            self._live_preview_cb.setText("🟢 实时预览 ON（拖动滑块即时应用到选中图层）")
            self._live_preview_cb.setStyleSheet(
                "QCheckBox { color: #6fdf6f; font-weight: bold; }"
            )
            # 开启时立即推送一次当前颜色
            self._schedule_live_apply()
        else:
            self._live_preview_cb.setText("🔴 实时预览（拖动滑块即时应用到选中图层）")
            self._live_preview_cb.setStyleSheet("")
            self._live_apply_timer.stop()

    def _schedule_live_apply(self):
        """调度一次防抖的实时颜色推送。"""
        if self._live_preview_cb.isChecked():
            self._live_apply_timer.start()  # 重新开始计时（自动取消上一次）

    def _do_live_apply(self):
        """防抖定时器到期后，将当前颜色推送到选中图层。"""
        if not self._live_preview_cb.isChecked():
            return

        selected = get_selected_nodes()
        if not selected:
            return

        r = self._slider_r.value()
        g = self._slider_g.value()
        b = self._slider_b.value()

        color_data = BaseColorData(
            r=r / 255.0,
            g=g / 255.0,
            b=b / 255.0,
            a=1.0,
            source_layer_name="实时预览",
            channel_name="BaseColor",
            valid=True,
            api_method="live_preview",
        )

        try:
            apply_basecolor_to_selected(color_data, "BaseColor")
        except Exception as e:
            print(f"[FillPropertyCopier] 实时预览应用失败: {e}")

    def _on_probe_clicked(self):
        """运行 API 探测。"""
        selected = get_selected_nodes()
        if not selected:
            self._show_result("⚠ 请先选中一个图层。", "warning")
            return

        source_node = selected[0]
        try:
            report = probe_layer_api(source_node)
            self._set_status(
                f"🔍 已探测 \"{source_node.get_name()}\" 的 API 信息（见控制台日志）"
            )
            self._show_result(
                f"🔍 已将 \"{source_node.get_name()}\" 的 API 探测报告输出到控制台日志。\n"
                f"请打开 Window → Views → Log 查看详细信息。",
                "info"
            )
        except Exception as e:
            self._show_result(
                f"⚠ API 探测过程中出错：{e}",
                "error"
            )

    # ============================================================
    # 颜色 UI 同步辅助
    # ============================================================
    def _sync_color_to_ui(self, r_float: float, g_float: float, b_float: float):
        """从 float (0~1) 颜色值同步到所有 UI 控件。"""
        r = max(0, min(255, int(r_float * 255 + 0.5)))
        g = max(0, min(255, int(g_float * 255 + 0.5)))
        b = max(0, min(255, int(b_float * 255 + 0.5)))

        # 同步 RGB 滑块
        self._slider_r.blockSignals(True)
        self._slider_g.blockSignals(True)
        self._slider_b.blockSignals(True)
        self._slider_r.setValue(r)
        self._slider_g.setValue(g)
        self._slider_b.setValue(b)
        self._slider_r.blockSignals(False)
        self._slider_g.blockSignals(False)
        self._slider_b.blockSignals(False)
        self._val_r.setText(str(r))
        self._val_g.setText(str(g))
        self._val_b.setText(str(b))

        # 同步 HSV 滑块
        color = QColor(r, g, b)
        h, s, v, _ = color.getHsv()
        if h < 0:
            h = 0
        self._slider_h.blockSignals(True)
        self._slider_s.blockSignals(True)
        self._slider_v.blockSignals(True)
        self._slider_h.setValue(h)
        self._slider_s.setValue(s)
        self._slider_v.setValue(v)
        self._slider_h.blockSignals(False)
        self._slider_s.blockSignals(False)
        self._slider_v.blockSignals(False)
        self._val_h.setText(str(h))
        self._val_s.setText(str(s))
        self._val_v.setText(str(v))

        self._color_preview.set_color_rgb(r, g, b)

        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hex_str)
        self._hex_input.blockSignals(False)

        self._color_hex_label.setText(f"HEX: {hex_str}")
        self._color_float_label.setText(
            f"Float: ({r_float:.4f}, {g_float:.4f}, {b_float:.4f})"
        )

        # 实时预览
        self._schedule_live_apply()

    def _sync_color_to_ui_from_qcolor(self, color: QColor):
        """从 QColor 同步到所有 UI 控件。"""
        self._sync_color_to_ui(
            color.redF(), color.greenF(), color.blueF()
        )

    def _update_color_info(self):
        """更新颜色信息文本区。"""
        if self._stored_color is None:
            self._color_info_text.clear()
            return

        info = self._stored_color.to_display_dict()
        lines = []
        for key, value in info.items():
            lines.append(f"  {key}:  {value}")
        self._color_info_text.setPlainText("\n".join(lines))
    # ============================================================
    def _update_preview(self):
        """更新属性预览显示。"""
        if self._stored_props is None:
            self._preview_text.clear()
            return

        info = self._stored_props.to_display_dict()
        lines = []
        for key, value in info.items():
            if key.startswith("---"):
                # 分区标题
                lines.append(f"\n{key.strip('- ')}")
            elif value == "":
                continue
            else:
                lines.append(f"  {key}:  {value}")

        self._preview_text.setPlainText("\n".join(lines).strip())

    def _update_ui_state(self):
        """根据当前状态更新控件启用/禁用状态。"""
        # ==== 投射属性 Tab ====
        has_props = self._stored_props is not None and self._stored_props.is_valid()
        self._apply_btn.setEnabled(has_props)
        self._clear_btn.setEnabled(has_props)

        # ---- 智能灰显 3D 映射区复选框 ----
        has_3d = has_props and self._stored_props.has_3d_params
        self._cb_3d_offset.setEnabled(has_3d)
        self._cb_3d_rotation.setEnabled(has_3d)
        self._cb_3d_scale.setEnabled(has_3d)

        # Tri-planar 额外参数：有对应数据时才启用
        has_filtering = has_props and self._stored_props.filtering_mode is not None
        has_hardness = has_props and self._stored_props.hardness is not None
        has_crop = has_props and self._stored_props.shape_crop_mode is not None
        self._cb_filtering_mode.setEnabled(has_filtering)
        self._cb_hardness.setEnabled(has_hardness)
        self._cb_shape_crop_mode.setEnabled(has_crop)

        if has_props and not has_3d:
            # 源数据没有 3D 参数，自动取消勾选并灰显
            self._cb_3d_offset.setChecked(False)
            self._cb_3d_rotation.setChecked(False)
            self._cb_3d_scale.setChecked(False)
            self._cb_filtering_mode.setChecked(False)
            self._cb_hardness.setChecked(False)
            self._cb_shape_crop_mode.setChecked(False)
            self._3d_hint_label.setText(
                "源图层为 UV 映射模式，无 3D 映射参数"
            )
        elif has_3d:
            self._3d_hint_label.setText(
                "仅 Tri-planar / Planar 等映射模式可用"
            )
            # 有 3D 参数时恢复勾选
            self._cb_3d_offset.setChecked(True)
            self._cb_3d_rotation.setChecked(True)
            self._cb_3d_scale.setChecked(True)
            self._cb_filtering_mode.setChecked(has_filtering)
            self._cb_hardness.setChecked(has_hardness)
            self._cb_shape_crop_mode.setChecked(has_crop)
        else:
            self._3d_hint_label.setText(
                "仅 Tri-planar / Planar 等映射模式可用"
            )

        # ---- 智能灰显 UV Wrap / UV 偏移 ----
        has_uv_wrap = has_props and self._stored_props.uv_wrap is not None
        self._cb_uv_wrap.setEnabled(has_uv_wrap)
        if has_props and not has_uv_wrap:
            self._cb_uv_wrap.setChecked(False)

        has_uv_offset = has_props and self._stored_props.uv_offset is not None
        self._cb_uv_offset.setEnabled(has_uv_offset)
        if has_props and not has_uv_offset:
            self._cb_uv_offset.setChecked(False)

        # ==== BaseColor 颜色 Tab ====
        has_color = self._stored_color is not None and self._stored_color.valid
        self._color_apply_btn.setEnabled(True)  # 始终可用（可手动输入颜色）
        self._color_clear_btn.setEnabled(has_color)

    def _set_all_checkboxes(self, checked: bool):
        """设置所有应用选项复选框（仅对启用的生效）。"""
        self._cb_projection.setChecked(checked)
        self._cb_uv_scale.setChecked(checked)
        self._cb_uv_rotation.setChecked(checked)

        # 仅在启用时才勾选
        if self._cb_uv_offset.isEnabled():
            self._cb_uv_offset.setChecked(checked)
        if self._cb_uv_wrap.isEnabled():
            self._cb_uv_wrap.setChecked(checked)
        if self._cb_3d_offset.isEnabled():
            self._cb_3d_offset.setChecked(checked)
        if self._cb_3d_rotation.isEnabled():
            self._cb_3d_rotation.setChecked(checked)
        if self._cb_3d_scale.isEnabled():
            self._cb_3d_scale.setChecked(checked)
        if self._cb_filtering_mode.isEnabled():
            self._cb_filtering_mode.setChecked(checked)
        if self._cb_hardness.isEnabled():
            self._cb_hardness.setChecked(checked)
        if self._cb_shape_crop_mode.isEnabled():
            self._cb_shape_crop_mode.setChecked(checked)

    def _set_status(self, text: str):
        """更新状态栏文本。"""
        self._status_label.setText(text)

    def _show_result(self, text: str, result_type: str = "success",
                     duration_ms: int = 8000):
        """
        在面板内显示操作结果提示。

        Args:
            text: 提示文本，支持多行
            result_type: 提示类型 "success" / "warning" / "error" / "info"
            duration_ms: 提示持续显示时间（毫秒），之后自动淡化。0 表示不自动消失。
        """
        # 先清除可能残留的内联样式，确保属性选择器能正常生效
        self._result_label.setStyleSheet("")
        self._result_label.setText(text)
        self._result_label.setProperty("resultType", result_type)
        # 刷新样式（属性变化后需要 repolish）
        self._result_label.style().unpolish(self._result_label)
        self._result_label.style().polish(self._result_label)
        self._result_label.setVisible(True)

        # 重置定时器
        self._result_fade_timer.stop()
        if duration_ms > 0:
            self._result_fade_timer.start(duration_ms)

    def _fade_result(self):
        """定时器到期后淡化结果提示（降低透明度但不隐藏，用户仍可看到）。"""
        # 使用 "faded" 类型通过属性选择器设置淡化样式，避免使用内联 setStyleSheet
        # （内联样式优先级高于全局样式表，会导致后续 _show_result 的属性选择器失效）
        self._result_label.setProperty("resultType", "faded")
        self._result_label.style().unpolish(self._result_label)
        self._result_label.style().polish(self._result_label)

    def _clear_result(self):
        """完全清除结果提示。"""
        self._result_label.setVisible(False)
        self._result_label.setText("")
        self._result_label.setProperty("resultType", "")
        self._result_label.setStyleSheet("")

    # ============================================================
    # 清理
    # ============================================================
    def cleanup(self):
        """插件关闭时调用。"""
        self._stored_props = None
        self._stored_color = None
