# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Animation Panel (UI)
基于 PySide6 的 Dock 面板，提供帧列表、播放控制、洋葱皮、批量导出等完整交互界面。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QSlider, QSpinBox, QDoubleSpinBox,
    QComboBox, QLineEdit, QCheckBox, QGroupBox,
    QListWidget, QListWidgetItem, QProgressBar,
    QFileDialog, QMessageBox, QToolButton,
    QSizePolicy, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from .frame_scanner import FrameScanner
from .visibility_controller import VisibilityController
from .playback_controller import PlaybackController, PlaybackState, LoopMode
from .onion_skin import OnionSkinController, OnionSkinSettings
from .export_helper import ExportHelper, ExportSettings
from .utils import validate_export_path


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
QPushButton { min-height: 24px; padding: 2px 8px; border-radius: 3px; }
QPushButton:hover { background-color: #4a4a4a; }
QToolButton { min-width: 32px; min-height: 32px; font-size: 14px; border-radius: 3px; }
QToolButton:hover { background-color: #4a4a4a; }
QListWidget { border: 1px solid #555; border-radius: 3px; }
QListWidget::item { padding: 3px 6px; border-bottom: 1px solid #3a3a3a; }
QListWidget::item:selected { background-color: #2a6496; }
QProgressBar {
    border: 1px solid #555; border-radius: 3px;
    text-align: center; min-height: 16px;
}
QProgressBar::chunk { background-color: #2a6496; border-radius: 2px; }
QSlider::groove:horizontal { height: 6px; background: #444; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #aaa; width: 14px; height: 14px;
    margin: -4px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #ccc; }
"""


class AnimationPanel(QWidget):
    """序列帧动画工具主面板，作为 Substance Painter 的 Dock Widget 嵌入。"""

    frame_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 核心控制器
        self._scanner = FrameScanner()
        self._vis_ctrl = VisibilityController()
        self._playback = PlaybackController()
        self._onion_skin = OnionSkinController(self._vis_ctrl)
        self._export_helper = ExportHelper(self._vis_ctrl)
        # 播放定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        # 连接回调
        self._playback.set_on_frame_changed(self._on_frame_changed)
        self._playback.set_on_playback_finished(self._on_playback_finished)
        self._export_helper.set_on_progress(self._on_export_progress)
        self._export_helper.set_on_finished(self._on_export_finished)
        # 内部标志
        self._slider_updating = False  # 防止滑块与播放器循环触发
        # 构建 UI
        self._build_ui()
        self.setStyleSheet(STYLESHEET)
        self._update_ui_state()

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        root.addWidget(self._build_scan_section())
        root.addWidget(self._build_frame_list_section())
        root.addWidget(self._build_timeline_section())
        root.addWidget(self._build_playback_section())
        root.addWidget(self._build_onion_skin_section())
        root.addWidget(self._build_export_section())
        root.addStretch()

    # ---------- 1) 扫描 ----------
    def _build_scan_section(self) -> QGroupBox:
        grp = QGroupBox("扫描设置")
        g = QGridLayout(grp); g.setSpacing(4)

        g.addWidget(QLabel("扫描模式:"), 0, 0)
        self._scan_mode_combo = QComboBox()
        self._scan_mode_combo.addItem("按命名规则", "by_name")
        self._scan_mode_combo.addItem("按图层栈顺序", "by_order")
        self._scan_mode_combo.currentIndexChanged.connect(self._on_scan_mode_changed)
        g.addWidget(self._scan_mode_combo, 0, 1, 1, 2)

        g.addWidget(QLabel("命名规则:"), 1, 0)
        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText("留空使用默认 (Frame_001, F01...)")
        self._pattern_edit.setToolTip(
            "自定义正则表达式，须包含一个捕获组提取帧编号数字。\n"
            "例: Shot_(\\d+) 匹配 Shot_001\n留空则使用内置规则。")
        g.addWidget(self._pattern_edit, 1, 1, 1, 2)

        self._scan_btn = QPushButton("🔍 扫描图层")
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        g.addWidget(self._scan_btn, 2, 0, 1, 3)

        self._texture_set_label = QLabel("当前纹理集: 未扫描")
        self._texture_set_label.setToolTip(
            "显示帧扫描所使用的 Texture Set 名称。\n"
            "帧扫描与可见性控制仅作用于此纹理集。")
        g.addWidget(self._texture_set_label, 3, 0, 1, 3)
        return grp

    # ---------- 2) 帧列表 ----------
    def _build_frame_list_section(self) -> QGroupBox:
        grp = QGroupBox("帧列表")
        v = QVBoxLayout(grp); v.setSpacing(4)

        self._frame_info_label = QLabel("未扫描")
        self._frame_info_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self._frame_info_label)

        self._frame_list = QListWidget()
        self._frame_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._frame_list.setMinimumHeight(80)
        self._frame_list.setMaximumHeight(200)
        self._frame_list.currentRowChanged.connect(self._on_frame_list_selection_changed)
        v.addWidget(self._frame_list)
        return grp

    # ---------- 3) 时间轴 ----------
    def _build_timeline_section(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(0, 2, 0, 2); v.setSpacing(2)

        self._current_frame_label = QLabel("当前帧: -- / --")
        self._current_frame_label.setAlignment(Qt.AlignCenter)
        f = self._current_frame_label.font(); f.setBold(True)
        self._current_frame_label.setFont(f)
        v.addWidget(self._current_frame_label)

        self._timeline_slider = QSlider(Qt.Horizontal)
        self._timeline_slider.setMinimum(0)
        self._timeline_slider.setMaximum(0)
        self._timeline_slider.setTickPosition(QSlider.TicksBelow)
        self._timeline_slider.setTickInterval(1)
        self._timeline_slider.valueChanged.connect(self._on_timeline_slider_changed)
        v.addWidget(self._timeline_slider)
        return w

    # ---------- 4) 播放控制 ----------
    def _build_playback_section(self) -> QGroupBox:
        grp = QGroupBox("播放控制")
        v = QVBoxLayout(grp); v.setSpacing(4)

        # 按钮行
        h = QHBoxLayout(); h.setSpacing(2)
        btns = [
            ("⏮", "跳到第一帧",   self._on_first_frame),
            ("|◀",  "上一帧",       self._on_prev_frame),
        ]
        for txt, tip, slot in btns:
            b = QToolButton(); b.setText(txt); b.setToolTip(tip)
            b.clicked.connect(slot); h.addWidget(b)

        self._play_btn = QToolButton()
        self._play_btn.setText("▶")
        self._play_btn.setToolTip("播放 / 暂停")
        self._play_btn.setMinimumWidth(56)
        self._play_btn.clicked.connect(self._on_play_pause)
        h.addWidget(self._play_btn)

        self._stop_btn = QToolButton(); self._stop_btn.setText("⏹")
        self._stop_btn.setToolTip("停止"); self._stop_btn.clicked.connect(self._on_stop)
        h.addWidget(self._stop_btn)

        btns2 = [
            ("▶|", "下一帧",       self._on_next_frame),
            ("⏭",  "跳到最后一帧", self._on_last_frame),
        ]
        for txt, tip, slot in btns2:
            b = QToolButton(); b.setText(txt); b.setToolTip(tip)
            b.clicked.connect(slot); h.addWidget(b)
        v.addLayout(h)

        # FPS + 循环
        g = QGridLayout(); g.setSpacing(4)
        g.addWidget(QLabel("FPS:"), 0, 0)
        self._fps_slider = QSlider(Qt.Horizontal)
        self._fps_slider.setRange(1, 60); self._fps_slider.setValue(12)
        self._fps_slider.setTickPosition(QSlider.TicksBelow); self._fps_slider.setTickInterval(6)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        g.addWidget(self._fps_slider, 0, 1)
        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(1, 60); self._fps_spin.setValue(12); self._fps_spin.setSuffix(" fps")
        self._fps_spin.setFixedWidth(70)
        self._fps_spin.valueChanged.connect(self._on_fps_spin_changed)
        g.addWidget(self._fps_spin, 0, 2)

        g.addWidget(QLabel("循环:"), 1, 0)
        self._loop_combo = QComboBox()
        self._loop_combo.addItem("🔁 循环",  LoopMode.LOOP)
        self._loop_combo.addItem("1️⃣  单次", LoopMode.ONCE)
        self._loop_combo.addItem("🔀 乒乓",  LoopMode.PING_PONG)
        self._loop_combo.currentIndexChanged.connect(self._on_loop_mode_changed)
        g.addWidget(self._loop_combo, 1, 1, 1, 2)
        v.addLayout(g)
        return grp

    # ---------- 5) 洋葱皮 ----------
    def _build_onion_skin_section(self) -> QGroupBox:
        grp = QGroupBox("洋葱皮 (Onion Skin)")
        g = QGridLayout(grp); g.setSpacing(4)

        self._onion_cb = QCheckBox("启用洋葱皮")
        self._onion_cb.toggled.connect(self._on_onion_toggled)
        g.addWidget(self._onion_cb, 0, 0, 1, 4)

        g.addWidget(QLabel("透明度通道:"), 1, 0)
        self._onion_channel_combo = QComboBox()
        self._onion_channel_combo.setToolTip(
            "选择洋葱皮操作的不透明度通道。\n"
            "单通道模式大幅减少 API 调用次数，显著提升播放性能。\n"
            "全通道模式对所有已启用通道设置透明度，效果最完整但较慢。")
        # 初始只添加默认项，扫描后会刷新
        self._onion_channel_combo.addItem("BaseColor (默认)",
                                          "BaseColor")
        self._onion_channel_combo.addItem("全部通道 (较慢)",
                                          OnionSkinSettings.ALL_CHANNELS)
        self._onion_channel_combo.currentIndexChanged.connect(
            self._on_onion_settings_changed)
        g.addWidget(self._onion_channel_combo, 1, 1, 1, 3)

        g.addWidget(QLabel("前方帧:"), 2, 0)
        self._onion_before = QSpinBox(); self._onion_before.setRange(0, 10); self._onion_before.setValue(1)
        self._onion_before.valueChanged.connect(self._on_onion_settings_changed)
        g.addWidget(self._onion_before, 2, 1)
        g.addWidget(QLabel("后方帧:"), 2, 2)
        self._onion_after = QSpinBox(); self._onion_after.setRange(0, 10); self._onion_after.setValue(1)
        self._onion_after.valueChanged.connect(self._on_onion_settings_changed)
        g.addWidget(self._onion_after, 2, 3)

        g.addWidget(QLabel("最小透明度:"), 3, 0)
        self._onion_min = QDoubleSpinBox(); self._onion_min.setRange(0.0, 1.0)
        self._onion_min.setSingleStep(0.05); self._onion_min.setValue(0.10)
        self._onion_min.valueChanged.connect(self._on_onion_settings_changed)
        g.addWidget(self._onion_min, 3, 1)
        g.addWidget(QLabel("最大透明度:"), 3, 2)
        self._onion_max = QDoubleSpinBox(); self._onion_max.setRange(0.0, 1.0)
        self._onion_max.setSingleStep(0.05); self._onion_max.setValue(0.50)
        self._onion_max.valueChanged.connect(self._on_onion_settings_changed)
        g.addWidget(self._onion_max, 3, 3)
        return grp

    # ---------- 6) 导出 ----------
    def _build_export_section(self) -> QGroupBox:
        grp = QGroupBox("导出序列帧")
        g = QGridLayout(grp); g.setSpacing(4)
        row = 0

        # 输出目录
        g.addWidget(QLabel("输出目录:"), row, 0)
        self._export_dir_edit = QLineEdit()
        g.addWidget(self._export_dir_edit, row, 1)
        browse_btn = QPushButton("浏览")
        browse_btn.setFixedWidth(50)
        browse_btn.clicked.connect(self._on_browse_export_dir)
        g.addWidget(browse_btn, row, 2)
        row += 1

        # 导出预设
        g.addWidget(QLabel("导出预设:"), row, 0)
        preset_h = QHBoxLayout(); preset_h.setSpacing(4)
        self._export_preset_combo = QComboBox()
        self._export_preset_combo.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._export_preset_combo.setToolTip(
            "选择 SP 导出预设，决定输出哪些贴图通道")
        preset_h.addWidget(self._export_preset_combo)
        self._refresh_presets_btn = QPushButton("🔄")
        self._refresh_presets_btn.setFixedWidth(32)
        self._refresh_presets_btn.setToolTip("刷新预设列表")
        self._refresh_presets_btn.clicked.connect(self._on_refresh_presets)
        preset_h.addWidget(self._refresh_presets_btn)
        g.addLayout(preset_h, row, 1, 1, 2)
        row += 1

        # 仅导出当前纹理集
        self._export_current_ts_cb = QCheckBox("仅导出当前纹理集")
        self._export_current_ts_cb.setChecked(True)
        self._export_current_ts_cb.setToolTip(
            "勾选时仅导出扫描帧所在的纹理集贴图（推荐）。\n"
            "取消勾选则导出项目中所有纹理集的贴图。")
        g.addWidget(self._export_current_ts_cb, row, 0, 1, 3)
        row += 1

        # 创建子目录 + 子目录前缀
        self._export_subdir_cb = QCheckBox("创建子目录:")
        self._export_subdir_cb.setChecked(False)
        self._export_subdir_cb.setToolTip(
            "勾选时每帧导出到独立子目录，避免文件名覆盖。\n"
            "目录格式: 前缀_帧号 (如 anim_0001, anim_0002...)\n"
            "取消勾选则所有帧直接导出到输出目录（注意文件可能被覆盖）。")
        self._export_subdir_cb.toggled.connect(self._on_subdir_toggled)
        g.addWidget(self._export_subdir_cb, row, 0)
        self._export_prefix_edit = QLineEdit("anim")
        self._export_prefix_edit.setEnabled(False)
        self._export_prefix_edit.setToolTip(
            "子目录前缀名称。\n"
            "目录格式: 前缀_帧号 (如 anim_0001, anim_0002...)\n"
            "贴图文件名由导出预设决定。")
        g.addWidget(self._export_prefix_edit, row, 1, 1, 2)
        row += 1

        # 导出范围
        g.addWidget(QLabel("导出范围:"), row, 0)
        range_h = QHBoxLayout(); range_h.setSpacing(4)
        self._export_range_combo = QComboBox()
        self._export_range_combo.addItem("全部帧", "all")
        self._export_range_combo.addItem("自定义范围", "custom")
        self._export_range_combo.currentIndexChanged.connect(
            self._on_export_range_changed)
        range_h.addWidget(self._export_range_combo)
        self._export_start_spin = QSpinBox()
        self._export_start_spin.setPrefix("从 ")
        self._export_start_spin.setSuffix(" 帧")
        self._export_start_spin.setRange(1, 9999)
        self._export_start_spin.setValue(1)
        self._export_start_spin.setToolTip("起始帧（含），基于帧列表序号")
        self._export_start_spin.setEnabled(False)
        range_h.addWidget(self._export_start_spin)
        self._export_end_spin = QSpinBox()
        self._export_end_spin.setPrefix("到 ")
        self._export_end_spin.setSuffix(" 帧")
        self._export_end_spin.setRange(1, 9999)
        self._export_end_spin.setValue(1)
        self._export_end_spin.setToolTip("结束帧（含），基于帧列表序号")
        self._export_end_spin.setEnabled(False)
        range_h.addWidget(self._export_end_spin)
        g.addLayout(range_h, row, 1, 1, 2)
        row += 1

        # 格式 + 位深度（同一行）
        g.addWidget(QLabel("格式:"), row, 0)
        self._export_fmt_combo = QComboBox()
        for fmt in ["png", "tga", "exr", "jpg"]:
            self._export_fmt_combo.addItem(fmt.upper(), fmt)
        g.addWidget(self._export_fmt_combo, row, 1)
        self._bit_depth_combo = QComboBox()
        self._bit_depth_combo.setToolTip(
            "每个颜色通道的位数。\n"
            "8-bit: 常规贴图，文件较小\n"
            "16-bit: 高精度，适合法线/位移等需要精度的通道\n"
            "32-bit: 最高精度，仅 EXR 格式支持")
        self._bit_depth_combo.addItem("8-bit", 8)
        self._bit_depth_combo.addItem("16-bit", 16)
        g.addWidget(self._bit_depth_combo, row, 2)
        # 先设默认值，再连信号，避免 setCurrentIndex 触发槽函数时控件尚未就绪
        self._export_fmt_combo.setCurrentIndex(1)   # 默认 TGA
        self._bit_depth_combo.setCurrentIndex(1)    # 默认 16-bit
        self._export_fmt_combo.currentIndexChanged.connect(
            self._on_export_fmt_changed)
        row += 1

        # 贴图尺寸
        g.addWidget(QLabel("贴图尺寸:"), row, 0)
        self._texture_size_combo = QComboBox()
        self._texture_size_combo.setToolTip(
            "导出贴图的分辨率。\n"
            "选择「跟随项目设置」则使用项目中 Texture Set 的当前分辨率。")
        self._texture_size_combo.addItem("跟随项目设置", 0)
        for log2_val, display in ExportSettings.TEXTURE_SIZES:
            self._texture_size_combo.addItem(f"{display} × {display}", log2_val)
        g.addWidget(self._texture_size_combo, row, 1, 1, 2)
        row += 1

        # 填充算法 + 膨胀像素（同一行）
        g.addWidget(QLabel("填充:"), row, 0)
        self._padding_algo_combo = QComboBox()
        self._padding_algo_combo.setToolTip(
            "贴图 UV 岛外部区域的填充方式:\n"
            "Pass through: 无填充，直接通过\n"
            "Infinite: 无限膨胀，边缘像素无限扩展(推荐)\n"
            "Dilation+Transparent: 有限膨胀，剩余区域透明\n"
            "Dilation+Default BG Color: 有限膨胀，剩余区域填充背景色\n"
            "Dilation+Diffusion: 有限膨胀，剩余区域漫反射扩散")
        for algo_key, algo_display in ExportSettings.PADDING_ALGORITHMS:
            self._padding_algo_combo.addItem(algo_display, algo_key)
        self._padding_algo_combo.setCurrentIndex(1)  # 默认 Infinite - 无限膨胀
        self._padding_algo_combo.currentIndexChanged.connect(
            self._on_padding_algo_changed)
        g.addWidget(self._padding_algo_combo, row, 1)
        self._dilation_spin = QSpinBox()
        self._dilation_spin.setRange(1, 256)
        self._dilation_spin.setValue(16)
        self._dilation_spin.setSuffix(" px")
        self._dilation_spin.setToolTip(
            "UV 岛边缘向外膨胀的像素距离。\n"
            "仅在填充算法为透明/背景色/漫反射时生效。")
        self._dilation_spin.setEnabled(False)  # 默认 Infinite 不需要
        g.addWidget(self._dilation_spin, row, 2)
        row += 1

        # 进度条
        self._export_progress = QProgressBar(); self._export_progress.setValue(0)
        g.addWidget(self._export_progress, row, 0, 1, 3)
        row += 1

        # 按钮行
        btn_h = QHBoxLayout()
        self._export_btn = QPushButton("📦 导出序列帧")
        self._export_btn.clicked.connect(self._on_export_clicked)
        btn_h.addWidget(self._export_btn)
        self._cancel_export_btn = QPushButton("取消")
        self._cancel_export_btn.setEnabled(False)
        self._cancel_export_btn.clicked.connect(self._on_cancel_export)
        btn_h.addWidget(self._cancel_export_btn)
        self._open_dir_btn = QPushButton("📂 打开目录")
        self._open_dir_btn.setToolTip("在资源管理器中打开输出目录")
        self._open_dir_btn.clicked.connect(self._on_open_export_dir)
        btn_h.addWidget(self._open_dir_btn)
        g.addLayout(btn_h, row, 0, 1, 3)

        # 初始加载预设列表
        self._load_export_presets()

        return grp

    def _load_export_presets(self):
        """加载所有可用的导出预设到下拉框。"""
        self._export_preset_combo.clear()
        # 第一项：自动选择（使用默认逻辑）
        self._export_preset_combo.addItem("自动选择（默认预设）", "")
        try:
            presets = ExportHelper.list_all_presets()
            for display_name, url in presets:
                self._export_preset_combo.addItem(display_name, url)
            if presets:
                print(f"[SequenceAnimation] 已加载 {len(presets)} 个导出预设")
        except Exception as e:
            print(f"[SequenceAnimation] 加载导出预设列表失败: {e}")

    def _on_refresh_presets(self):
        """刷新导出预设列表。"""
        self._load_export_presets()
        QMessageBox.information(
            self, "预设刷新",
            f"已加载 {self._export_preset_combo.count() - 1} 个导出预设")

    # ============================================================
    # 槽函数 —— 扫描
    # ============================================================
    def _on_scan_mode_changed(self, index):
        is_name = self._scan_mode_combo.currentData() == "by_name"
        self._pattern_edit.setEnabled(is_name)

    def _on_scan_clicked(self):
        try:
            pattern = self._pattern_edit.text().strip() or None
            self._scanner.set_custom_pattern(pattern)
            mode = self._scan_mode_combo.currentData()
            if mode == "by_order":
                frames = self._scanner.scan_by_stack_order()
            else:
                frames = self._scanner.scan()
        except RuntimeError as e:
            QMessageBox.warning(self, "扫描失败", str(e))
            return

        # 分发到各控制器
        self._vis_ctrl.set_frames(frames)
        self._onion_skin.set_frames(frames)
        self._export_helper.set_frames(frames)
        self._playback.total_frames = len(frames)
        self._playback.current_index = 0

        # 更新纹理集名称显示
        ts_name = self._scanner.active_texture_set_name or "未知"
        self._texture_set_label.setText(f"当前纹理集: {ts_name}")
        self._export_current_ts_cb.setText(
            f"仅导出当前纹理集 ({ts_name})")

        # 刷新洋葱皮通道下拉框
        self._refresh_onion_channels()

        # 刷新 UI
        self._refresh_frame_list()
        self._update_ui_state()
        # 更新导出范围 SpinBox 上限
        frame_count = len(frames)
        if frame_count > 0:
            self._export_start_spin.setRange(1, frame_count)
            self._export_end_spin.setRange(1, frame_count)
            self._export_start_spin.setValue(1)
            self._export_end_spin.setValue(frame_count)
        if frames:
            # 如果洋葱皮处于启用状态，直接应用
            if self._onion_skin.enabled:
                self._onion_skin.apply(0)
            else:
                self._vis_ctrl.show_frame(0)
            self._update_frame_display(0)

    # ============================================================
    # 槽函数 —— 帧列表
    # ============================================================
    def _on_frame_list_selection_changed(self, row):
        if row < 0 or self._playback.is_playing:
            return
        self._playback.go_to_frame(row)

    # ============================================================
    # 槽函数 —— 时间轴
    # ============================================================
    def _on_timeline_slider_changed(self, value):
        if self._slider_updating:
            return
        self._playback.go_to_frame(value)

    # ============================================================
    # 槽函数 —— 播放控制
    # ============================================================
    def _on_play_pause(self):
        if self._playback.is_playing:
            self._playback.pause()
            self._timer.stop()
            self._play_btn.setText("▶")
        else:
            try:
                self._vis_ctrl.save_original_visibility()
                self._playback.play()
                self._timer.start(self._playback.frame_interval_ms)
                self._play_btn.setText("⏸")
            except Exception as e:
                print(f"[SequenceAnimation] 播放启动失败: {e}")
                self._timer.stop()
                self._play_btn.setText("▶")
                QMessageBox.warning(self, "播放失败",
                                    f"无法启动播放:\n{e}")

    def _on_stop(self):
        self._timer.stop()
        self._play_btn.setText("▶")
        try:
            self._playback.stop()
            self._vis_ctrl.restore_original_visibility()
            self._onion_skin.reset_all_opacities()
        except Exception as e:
            print(f"[SequenceAnimation] 停止播放时恢复状态失败: {e}")

    def _on_first_frame(self):
        self._playback.go_to_first()

    def _on_last_frame(self):
        self._playback.go_to_last()

    def _on_prev_frame(self):
        self._playback.prev_frame()

    def _on_next_frame(self):
        self._playback.next_frame()

    def _on_fps_changed(self, val):
        self._fps_spin.blockSignals(True)
        self._fps_spin.setValue(val)
        self._fps_spin.blockSignals(False)
        self._playback.fps = val
        if self._timer.isActive():
            self._timer.setInterval(self._playback.frame_interval_ms)

    def _on_fps_spin_changed(self, val):
        self._fps_slider.blockSignals(True)
        self._fps_slider.setValue(val)
        self._fps_slider.blockSignals(False)
        self._playback.fps = val
        if self._timer.isActive():
            self._timer.setInterval(self._playback.frame_interval_ms)

    def _on_loop_mode_changed(self, _index):
        mode = self._loop_combo.currentData()
        if mode:
            self._playback.loop_mode = mode

    # ============================================================
    # 槽函数 —— 洋葱皮
    # ============================================================
    def _on_onion_toggled(self, checked):
        self._onion_skin.enabled = checked
        # 切换洋葱皮时自动暂停播放，避免视觉混乱
        if self._playback.is_playing:
            self._playback.pause()
            self._timer.stop()
            self._play_btn.setText("▶")
        try:
            if not checked:
                self._onion_skin.clear(self._playback.current_index)
                # 恢复到当前帧显示
                if self._scanner.frame_count > 0:
                    self._vis_ctrl.show_frame(self._playback.current_index)
            else:
                # 启用洋葱皮：同步设置并应用一次即可
                # _on_onion_settings_changed 内部会检查 enabled 并调用 apply()，
                # 无需再手动调用一次 apply()
                self._on_onion_settings_changed()
        except Exception as e:
            print(f"[SequenceAnimation] 洋葱皮切换异常: {e}")
            QMessageBox.warning(self, "洋葱皮",
                                f"洋葱皮操作异常:\n{e}")

    def _refresh_onion_channels(self):
        """扫描后刷新洋葱皮通道下拉框，使用当前 Texture Set 的实际通道。"""
        self._onion_channel_combo.blockSignals(True)
        prev_data = self._onion_channel_combo.currentData()
        self._onion_channel_combo.clear()

        # 获取可用通道列表
        available = self._onion_skin.get_available_channels()
        if available:
            for ch_obj, ch_name in available:
                self._onion_channel_combo.addItem(ch_name, ch_obj)
        else:
            # 回退：至少有 BaseColor 选项
            self._onion_channel_combo.addItem("BaseColor", "BaseColor")

        # 全部通道选项放在最后
        self._onion_channel_combo.addItem(
            "全部通道 (较慢)", OnionSkinSettings.ALL_CHANNELS)

        # 尝试恢复之前的选择
        restored = False
        for i in range(self._onion_channel_combo.count()):
            if self._onion_channel_combo.itemData(i) == prev_data:
                self._onion_channel_combo.setCurrentIndex(i)
                restored = True
                break
        if not restored:
            self._onion_channel_combo.setCurrentIndex(0)  # 默认第一个通道

        self._onion_channel_combo.blockSignals(False)
        # 同步设置
        self._on_onion_settings_changed()

    def _on_onion_settings_changed(self, _=None):
        s = self._onion_skin.settings
        s.frames_before = self._onion_before.value()
        s.frames_after = self._onion_after.value()
        s.min_opacity = self._onion_min.value()
        s.max_opacity = self._onion_max.value()
        # 同步通道选择
        channel_data = self._onion_channel_combo.currentData()
        if channel_data is not None:
            s.opacity_channel = channel_data
            self._onion_skin.invalidate_channel_cache()
        if self._onion_skin.enabled and not self._playback.is_playing:
            self._onion_skin.apply(self._playback.current_index)

    # ============================================================
    # 槽函数 —— 导出
    # ============================================================
    def _on_browse_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._export_dir_edit.setText(d)

    def _on_export_fmt_changed(self, _index):
        """导出格式切换时，更新位深度可选项。"""
        fmt = self._export_fmt_combo.currentData()
        prev_depth = self._bit_depth_combo.currentData()
        self._bit_depth_combo.clear()

        if fmt == "exr":
            # EXR 支持 16-bit 和 32-bit
            self._bit_depth_combo.addItem("16-bit", 16)
            self._bit_depth_combo.addItem("32-bit", 32)
        elif fmt == "jpg":
            # JPG 仅支持 8-bit
            self._bit_depth_combo.addItem("8-bit", 8)
        else:
            # PNG / TGA 支持 8-bit 和 16-bit
            self._bit_depth_combo.addItem("8-bit", 8)
            self._bit_depth_combo.addItem("16-bit", 16)

        # 尝试恢复之前的选择
        for i in range(self._bit_depth_combo.count()):
            if self._bit_depth_combo.itemData(i) == prev_depth:
                self._bit_depth_combo.setCurrentIndex(i)
                break

    def _on_padding_algo_changed(self, _index):
        """填充算法切换时，启用/禁用膨胀像素 SpinBox。"""
        algo = self._padding_algo_combo.currentData()
        needs_dilation = algo in ExportSettings.ALGORITHMS_NEED_DILATION
        self._dilation_spin.setEnabled(needs_dilation)

    def _on_export_range_changed(self, _index):
        """导出范围切换时，启用/禁用起始帧和结束帧 SpinBox。"""
        is_custom = self._export_range_combo.currentData() == "custom"
        self._export_start_spin.setEnabled(is_custom)
        self._export_end_spin.setEnabled(is_custom)

    def _on_subdir_toggled(self, checked):
        """创建子目录复选框切换时，启用/禁用子目录前缀输入框。"""
        self._export_prefix_edit.setEnabled(checked)

    def _on_export_clicked(self):
        # 如果正在播放，先停止播放
        if self._playback.is_playing or self._playback.is_paused:
            self._on_stop()

        # 如果洋葱皮处于启用状态，临时关闭并恢复所有帧 opacity
        onion_was_enabled = self._onion_skin.enabled
        if onion_was_enabled:
            self._onion_skin.reset_all_opacities()
            self._onion_skin.enabled = False
            self._onion_cb.blockSignals(True)
            self._onion_cb.setChecked(False)
            self._onion_cb.blockSignals(False)

        s = self._export_helper.settings
        s.output_dir = self._export_dir_edit.text().strip()
        s.file_prefix = self._export_prefix_edit.text().strip() or "anim"
        s.file_format = self._export_fmt_combo.currentData()
        s.use_sub_dirs = self._export_subdir_cb.isChecked()

        # 同步位深度
        s.bit_depth = self._bit_depth_combo.currentData()

        # 同步导出预设选择
        preset_url = self._export_preset_combo.currentData()
        s.export_preset_url = preset_url if preset_url else ""

        # 同步纹理集导出范围
        s.export_current_ts_only = self._export_current_ts_cb.isChecked()

        # 同步贴图尺寸
        s.texture_size_log2 = self._texture_size_combo.currentData()

        # 同步填充算法
        s.padding_algorithm = self._padding_algo_combo.currentData()

        # 同步膨胀像素
        s.dilation_distance = self._dilation_spin.value()

        ok, msg = validate_export_path(s.output_dir)
        if not ok:
            QMessageBox.warning(self, "导出错误", msg); return

        # 导出范围
        if self._export_range_combo.currentData() == "custom":
            start = self._export_start_spin.value()
            end = self._export_end_spin.value()
            if start > end:
                QMessageBox.warning(self, "导出错误",
                                    f"起始帧 ({start}) 不能大于结束帧 ({end})")
                return
            frame_range = (start - 1, end)  # 转为 0-based 切片
        else:
            frame_range = None

        self._export_btn.setEnabled(False)
        self._cancel_export_btn.setEnabled(True)
        self._export_progress.setValue(0)
        self._export_helper.export_sequence(frame_range=frame_range)

    def _on_cancel_export(self):
        self._export_helper.cancel()

    def _on_open_export_dir(self):
        """在系统文件管理器中打开输出目录。"""
        import os, subprocess, sys
        path = self._export_dir_edit.text().strip()
        if not path:
            QMessageBox.information(self, "提示", "请先设置输出目录")
            return
        if not os.path.isdir(path):
            QMessageBox.warning(self, "提示", f"目录不存在:\n{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"无法打开目录:\n{e}")

    def _on_export_progress(self, current, total):
        pct = int(current / total * 100) if total > 0 else 0
        self._export_progress.setValue(pct)

    def _on_export_finished(self, success, message):
        self._export_btn.setEnabled(True)
        self._cancel_export_btn.setEnabled(False)
        self._export_progress.setValue(100 if success else 0)
        if success:
            # 使用标准按钮组合，比 addButton+ActionRole 在 SP 内嵌 Qt 中更可靠
            result = QMessageBox.question(
                self, "导出完成",
                f"{message}\n\n是否打开输出目录？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            if result == QMessageBox.Yes:
                self._on_open_export_dir()
        else:
            QMessageBox.warning(self, "导出", message)

    # ============================================================
    # 回调 —— 播放器 / 定时器
    # ============================================================
    def _on_timer_tick(self):
        try:
            self._playback.advance_frame()
        except Exception as e:
            print(f"[SequenceAnimation] 定时器帧推进异常，已停止播放: {e}")
            self._timer.stop()
            self._play_btn.setText("▶")

    def _on_frame_changed(self, frame_index: int):
        """播放控制器通知帧变化。带异常保护，防止单帧错误中断播放。"""
        try:
            if self._onion_skin.enabled:
                self._onion_skin.apply(frame_index)
            else:
                self._vis_ctrl.show_frame(frame_index)
        except Exception as e:
            print(f"[SequenceAnimation] 帧切换异常 (index={frame_index}): {e}")
        self._update_frame_display(frame_index)
        self.frame_changed.emit(frame_index)

    def _on_playback_finished(self):
        """单次播放结束。"""
        self._timer.stop()
        self._play_btn.setText("▶")

    # ============================================================
    # UI 更新辅助
    # ============================================================
    def _refresh_frame_list(self):
        """刷新帧列表控件。"""
        self._frame_list.clear()
        frames = self._scanner.frames
        for entry in frames:
            sub_count = entry.get_sub_layer_count()
            text = f"#{entry.frame_number:03d}  {entry.layer_name}  ({sub_count} 子图层)"
            self._frame_list.addItem(text)
        count = len(frames)
        self._frame_info_label.setText(f"共 {count} 帧" if count else "未找到帧 Group")

    def _update_frame_display(self, frame_index: int):
        """更新帧显示相关 UI 元素。"""
        total = self._scanner.frame_count
        self._current_frame_label.setText(
            f"当前帧: {frame_index + 1} / {total}" if total > 0 else "当前帧: -- / --"
        )
        # 滑块（仅在 total 变化时更新 maximum，播放中 total 不变可跳过）
        self._slider_updating = True
        slider_max = max(0, total - 1)
        if self._timeline_slider.maximum() != slider_max:
            self._timeline_slider.setMaximum(slider_max)
        self._timeline_slider.setValue(frame_index)
        self._slider_updating = False
        # 列表选中（仅在行号变化时设置，避免播放中每帧触发 Qt 内部重绘）
        if self._frame_list.currentRow() != frame_index:
            self._frame_list.blockSignals(True)
            self._frame_list.setCurrentRow(frame_index)
            self._frame_list.blockSignals(False)

    def _update_ui_state(self):
        """根据当前状态启用/禁用控件。"""
        has_frames = self._scanner.frame_count > 0
        self._play_btn.setEnabled(has_frames)
        self._stop_btn.setEnabled(has_frames)
        self._timeline_slider.setEnabled(has_frames)
        self._export_btn.setEnabled(has_frames)
        if has_frames:
            self._timeline_slider.setMaximum(self._scanner.frame_count - 1)

    # ============================================================
    # 清理
    # ============================================================
    def cleanup(self):
        """插件关闭时调用，停止定时器并恢复图层状态。"""
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            if self._playback.is_playing or self._playback.is_paused:
                self._vis_ctrl.restore_original_visibility()
                self._onion_skin.reset_all_opacities()
        except Exception as e:
            print(f"[SequenceAnimation] 清理时恢复状态失败: {e}")
