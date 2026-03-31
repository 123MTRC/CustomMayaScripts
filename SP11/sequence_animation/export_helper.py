# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Export Helper Module
批量导出序列帧：逐帧切换可见性并调用 SP 导出功能。
"""

import os
import time
from typing import List, Optional, Callable

import substance_painter.export as sp_export
import substance_painter.project as sp_project
import substance_painter.textureset as textureset

from PySide6.QtWidgets import QApplication

from .frame_scanner import FrameEntry
from .visibility_controller import VisibilityController


class ExportSettings:
    """导出设置。"""

    # SP 支持的填充算法（与 SP 导出设置一一对应）
    PADDING_ALGORITHMS = [
        ("passthrough", "Pass through - 无填充(通过)"),
        ("infinite", "Infinite - 无限膨胀"),
        ("transparent", "Dilation + Transparent - 膨胀+透明度"),
        ("color", "Dilation + Default BackGround Color - 膨胀+默认背景色"),
        ("diffusion", "Dilation + Diffusion - 膨胀+漫反射"),
    ]

    # SP 支持的贴图尺寸 (log2值, 显示名称)
    TEXTURE_SIZES = [
        (7,  "128"),
        (8,  "256"),
        (9,  "512"),
        (10, "1024"),
        (11, "2048"),
        (12, "4096"),
    ]

    # 需要提供膨胀距离的填充算法
    ALGORITHMS_NEED_DILATION = {"transparent", "color", "diffusion"}

    def __init__(self):
        self.output_dir: str = ""
        self.file_prefix: str = "anim"      # 子目录前缀
        self.file_format: str = "tga"       # png, tga, exr, jpg
        self.padding: int = 4               # 帧号数字补零位数
        self.export_preset_url: str = ""    # SP 导出预设 URL（留空使用默认）
        self.bit_depth: int = 16            # 8, 16 or 32(仅EXR)
        self.padding_algorithm: str = "infinite"  # 填充算法
        self.dilation_distance: int = 16    # 膨胀像素距离（透明/颜色/漫反射时生效）
        self.texture_size_log2: int = 0     # 贴图尺寸 log2 值，0 表示跟随项目设置
        self.export_current_ts_only: bool = True  # 仅导出当前纹理集
        self.use_sub_dirs: bool = False          # 每帧导出到独立子目录


class ExportHelper:
    """
    导出助手：
    依次显示每帧 → 调用 SP 导出 → 自动命名输出文件，生成序列帧。
    """

    def __init__(self, visibility_controller: VisibilityController):
        self._vis_ctrl = visibility_controller
        self._settings = ExportSettings()
        self._frames: List[FrameEntry] = []
        self._is_exporting: bool = False
        self._cancelled: bool = False

        # 回调
        self._on_progress: Optional[Callable[[int, int], None]] = None
        self._on_finished: Optional[Callable[[bool, str], None]] = None

    @property
    def settings(self) -> ExportSettings:
        return self._settings

    @property
    def is_exporting(self) -> bool:
        return self._is_exporting

    def set_frames(self, frames: List[FrameEntry]):
        """设置帧列表。"""
        self._frames = frames

    def set_on_progress(self, callback: Callable[[int, int], None]):
        """设置进度回调。callback(current_frame, total_frames)"""
        self._on_progress = callback

    def set_on_finished(self, callback: Callable[[bool, str], None]):
        """设置完成回调。callback(success, message)"""
        self._on_finished = callback

    def cancel(self):
        """取消导出。"""
        self._cancelled = True

    @staticmethod
    def list_all_presets():
        """
        获取所有可用的导出预设，返回 (display_name, url) 元组列表。
        供 UI 下拉框使用。

        Returns:
            list of (str, str): [(显示名称, 预设URL), ...]
        """
        presets = []

        # 1. Predefined presets（内置预设）
        try:
            predefined = sp_export.list_predefined_export_presets()
            for p in predefined:
                name = p.name if hasattr(p, 'name') else '?'
                if callable(name):
                    name = name()
                url = p.url if hasattr(p, 'url') else ''
                if callable(url):
                    url = url()
                presets.append((f"[内置] {name}", str(url)))
        except Exception as e:
            print(f"[SequenceAnimation] list_predefined_export_presets 异常: {e}")

        # 2. Resource presets（项目/资源库预设）
        try:
            resource = sp_export.list_resource_export_presets()
            for p in resource:
                # 提取名称和 URL
                name = "Unknown"
                url = ""
                if hasattr(p, 'resource_id'):
                    rid = p.resource_id
                    if callable(rid):
                        rid = rid()
                    if hasattr(rid, 'name'):
                        rname = rid.name
                        name = rname() if callable(rname) else rname
                    if hasattr(rid, 'context'):
                        ctx = rid.context
                        ctx = ctx() if callable(ctx) else ctx
                        url = f"resource://{ctx}/{name}"
                    else:
                        url = str(rid)
                presets.append((f"[资源] {name}", url))
        except Exception as e:
            print(f"[SequenceAnimation] list_resource_export_presets 异常: {e}")

        return presets

    @staticmethod
    def list_output_maps_for_preset(preset_url: str):
        """
        获取指定预设的输出贴图列表。

        Returns:
            list of str: 输出贴图名称列表
        """
        maps = []
        try:
            predefined = sp_export.list_predefined_export_presets()
            for p in predefined:
                url = p.url if hasattr(p, 'url') else ''
                if callable(url):
                    url = url()
                if str(url) == preset_url:
                    if hasattr(p, 'list_output_maps'):
                        output_maps = p.list_output_maps()
                        maps = [str(m) for m in output_maps]
                    return maps
        except Exception:
            pass

        try:
            resource = sp_export.list_resource_export_presets()
            for p in resource:
                p_url = ""
                if hasattr(p, 'resource_id'):
                    rid = p.resource_id
                    if callable(rid):
                        rid = rid()
                    rname = ""
                    ctx = ""
                    if hasattr(rid, 'name'):
                        rname = rid.name
                        rname = rname() if callable(rname) else rname
                    if hasattr(rid, 'context'):
                        ctx = rid.context
                        ctx = ctx() if callable(ctx) else ctx
                    p_url = f"resource://{ctx}/{rname}"
                if p_url == preset_url:
                    if hasattr(p, 'list_output_maps'):
                        output_maps = p.list_output_maps()
                        maps = [str(m) for m in output_maps]
                    return maps
        except Exception:
            pass

        return maps

    def export_sequence(self, frame_range=None):
        """
        执行批量导出序列帧。

        Args:
            frame_range: 帧范围元组 (start, end)，0-based 切片语义。
                         None 表示导出全部帧。
                         例: (0, 5) 表示导出前 5 帧（索引 0~4）

        逐帧切换可见性，调用 SP 导出功能，将每帧的贴图
        保存为独立文件，文件名包含帧编号。

        容错机制：
        - 单帧导出失败不中断整体流程，记录错误继续下一帧
        - 导出结束后汇报成功/失败统计
        - output_dir 创建失败时提前退出并给出清晰提示
        """
        if self._is_exporting:
            return
        if not self._frames:
            self._notify_finished(False, "没有可导出的帧")
            return

        settings = self._settings

        # 验证输出目录
        if not settings.output_dir:
            self._notify_finished(False, "未设置输出目录")
            return

        # 确保项目已打开
        if not sp_project.is_open():
            self._notify_finished(False, "没有打开的项目")
            return

        # 创建输出目录（带权限检查）
        try:
            os.makedirs(settings.output_dir, exist_ok=True)
        except OSError as e:
            self._notify_finished(
                False,
                f"无法创建输出目录:\n{settings.output_dir}\n原因: {e}")
            return

        # 写入权限测试
        test_file = os.path.join(settings.output_dir, ".export_test")
        try:
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except OSError as e:
            self._notify_finished(
                False,
                f"输出目录无写入权限:\n{settings.output_dir}\n原因: {e}")
            return

        # ======== 获取导出预设 URL ========
        if settings.export_preset_url:
            preset_url = settings.export_preset_url
        else:
            preset_url = self._resolve_export_preset_url()
        if preset_url is None:
            self._notify_finished(False, "找不到可用的导出预设，请确认项目中已配置导出预设")
            return

        print(f"[SequenceAnimation] 最终使用预设 URL: {preset_url}")

        self._is_exporting = True
        self._cancelled = False
        failed_frames = []  # 记录失败帧
        success_count = 0

        # 确定要导出的帧列表
        if frame_range is not None:
            start_idx, end_idx = frame_range
            frames_to_export = list(enumerate(self._frames))[start_idx:end_idx]
            print(f"[SequenceAnimation] 导出范围: 帧 {start_idx+1} ~ {end_idx} "
                  f"(共 {len(frames_to_export)} 帧)")
        else:
            frames_to_export = list(enumerate(self._frames))
        total = len(frames_to_export)

        if total == 0:
            self._is_exporting = False
            self._notify_finished(False, "指定范围内没有可导出的帧")
            return

        # 保存原始可见性
        self._vis_ctrl.save_original_visibility()

        # 预构建 exportList（TextureSet 列表在导出过程中不变，只需构建一次）
        export_list = self._build_export_list(preset_url)

        try:
            for progress_idx, (idx, entry) in enumerate(frames_to_export):
                # 让出控制权给 UI 事件循环，使进度条和取消按钮保持响应
                QApplication.processEvents()

                if self._cancelled:
                    self._notify_finished(False, "导出已取消")
                    break

                # 切换到当前帧（使用全局索引）
                self._vis_ctrl.show_frame(idx)

                # 构造帧编号字符串（如 "0001"）
                frame_num_str = str(entry.frame_number).zfill(
                    self._settings.padding)

                # 根据设置决定导出路径
                if self._settings.use_sub_dirs:
                    # 每帧导出到独立子目录，避免文件名覆盖
                    # 目录格式: output_dir/prefix_0001/
                    frame_dir_name = (
                        f"{self._settings.file_prefix}_{frame_num_str}"
                    )
                    frame_export_path = os.path.join(
                        settings.output_dir, frame_dir_name)

                    try:
                        os.makedirs(frame_export_path, exist_ok=True)
                    except OSError as e:
                        print(f"[SequenceAnimation] 帧 {entry.frame_number} "
                              f"创建目录失败: {e}")
                        failed_frames.append(
                            (entry.frame_number, f"创建目录失败: {e}"))
                        continue
                else:
                    # 不创建子目录，所有帧导出到同一 output_dir
                    frame_export_path = settings.output_dir

                # 构建本帧的导出配置（exportPath 指向子目录，复用预构建的 exportList）
                export_config = self._build_export_config(
                    preset_url, frame_export_path, export_list)

                print(f"[SequenceAnimation] 帧 {entry.frame_number} "
                      f"导出到: {frame_export_path}")

                # 非子目录模式下，记录导出前时间戳，用于后续识别本帧导出的文件
                timestamp_before = (
                    time.time() if not self._settings.use_sub_dirs else 0)

                # 执行导出
                try:
                    result = sp_export.export_project_textures(export_config)
                    # 探测 result 结构（仅首帧）
                    if progress_idx == 0:
                        print(f"[SequenceAnimation] 导出结果: {result}")
                        print(f"[SequenceAnimation] 结果类型: {type(result)}")
                        if hasattr(result, 'status'):
                            print(f"[SequenceAnimation] status={result.status}")
                        if hasattr(result, 'message'):
                            print(f"[SequenceAnimation] message={result.message}")
                        if hasattr(result, 'textures'):
                            print(f"[SequenceAnimation] textures={result.textures}")

                    if hasattr(result, 'status'):
                        if result.status != sp_export.ExportStatus.Success:
                            msg = ""
                            if hasattr(result, 'message'):
                                msg = str(result.message)
                            failed_frames.append(
                                (entry.frame_number,
                                 f"status={result.status} {msg}"))
                            continue

                    # 非子目录模式：导出成功后重命名文件，追加帧号后缀
                    if not self._settings.use_sub_dirs:
                        self._rename_exported_files_with_frame_suffix(
                            result, frame_export_path,
                            frame_num_str, timestamp_before)

                    success_count += 1

                except Exception as e:
                    import traceback
                    print(f"[SequenceAnimation] 帧 {entry.frame_number} "
                          f"导出失败: {e}")
                    traceback.print_exc()
                    failed_frames.append(
                        (entry.frame_number, str(e)))

                # 通知进度
                if self._on_progress:
                    self._on_progress(progress_idx + 1, total)

                # 导出完一帧后再次让出控制权，刷新进度条显示
                QApplication.processEvents()

            if not self._cancelled:
                # 构造汇报消息
                if not failed_frames:
                    self._notify_finished(
                        True,
                        f"成功导出全部 {total} 帧到\n"
                        f"{self._settings.output_dir}")
                elif success_count > 0:
                    fail_detail = "\n".join(
                        f"  帧 {fn}: {reason}"
                        for fn, reason in failed_frames[:5])
                    extra = (f"\n  ... 及其他 {len(failed_frames) - 5} 帧"
                             if len(failed_frames) > 5 else "")
                    self._notify_finished(
                        True,
                        f"导出完成: {success_count} 帧成功, "
                        f"{len(failed_frames)} 帧失败\n"
                        f"输出目录: {self._settings.output_dir}\n\n"
                        f"失败详情:\n{fail_detail}{extra}")
                else:
                    self._notify_finished(
                        False,
                        f"全部 {total} 帧导出失败，请检查导出设置和日志")

        except Exception as e:
            self._notify_finished(False, f"导出过程出错: {e}")

        finally:
            # 恢复原始可见性
            self._vis_ctrl.restore_original_visibility()
            self._is_exporting = False

    def _get_preset_url(self, preset) -> str:
        """
        从预设对象中提取 SP 可识别的 URL 字符串。

        - PredefinedExportPreset: 有 .url 属性
          如 'export-preset-generator://doc-channel-normal-no-alpha'
        - ResourceExportPreset: 有 .resource_id 属性
          需要构造 'resource://context/name' 格式
        """
        # PredefinedExportPreset → 直接用 .url
        if hasattr(preset, 'url'):
            url = preset.url
            # url 可能是属性或方法
            return url() if callable(url) else url

        # ResourceExportPreset → 从 resource_id 构造 URL
        if hasattr(preset, 'resource_id'):
            rid = preset.resource_id
            if callable(rid):
                rid = rid()

            ctx = None
            name = None

            if hasattr(rid, 'context'):
                ctx = rid.context
                if callable(ctx):
                    ctx = ctx()
            if hasattr(rid, 'name'):
                name = rid.name
                if callable(name):
                    name = name()

            if ctx and name:
                return f"resource://{ctx}/{name}"

            for attr_name in ('url', 'location', 'path'):
                if hasattr(rid, attr_name):
                    val = getattr(rid, attr_name)
                    result = val() if callable(val) else val
                    return str(result)

        # 最终回退
        return str(preset)

    def _resolve_export_preset_url(self) -> Optional[str]:
        """
        获取可用的导出预设 URL 字符串。

        优先级：
        1. 用户指定的预设名称（在两种预设列表中匹配）
        2. PredefinedExportPreset 中的 'Document channels + Normal + AO (No Alpha)'
           (通用性最强的预设)
        3. 第一个 PredefinedExportPreset
        4. 第一个 ResourceExportPreset

        Returns:
            预设 URL 字符串，或 None。
        """
        user_preset_name = self._settings.export_preset_url

        # 收集所有预设
        resource_presets = []
        predefined_presets = []

        try:
            resource_presets = sp_export.list_resource_export_presets()
        except Exception:
            pass

        try:
            predefined_presets = sp_export.list_predefined_export_presets()
        except Exception:
            pass

        # 1. 如果用户指定了预设名称，尝试匹配
        if user_preset_name:
            for p in predefined_presets:
                name = p.name if hasattr(p, 'name') else ''
                if callable(name):
                    name = name()
                if user_preset_name.lower() in str(name).lower():
                    return self._get_preset_url(p)

            for p in resource_presets:
                if user_preset_name.lower() in str(p).lower():
                    return self._get_preset_url(p)

        # 2. 优先使用 PredefinedExportPreset（它的 URL 格式是确定可用的）
        # 优先选 "Document channels" 预设（最通用）
        for p in predefined_presets:
            name = p.name if hasattr(p, 'name') else ''
            if callable(name):
                name = name()
            if 'Document channels' in str(name) and 'No Alpha' in str(name):
                return self._get_preset_url(p)

        # 3. 第一个 predefined preset
        if predefined_presets:
            return self._get_preset_url(predefined_presets[0])

        # 4. 第一个 resource preset
        if resource_presets:
            return self._get_preset_url(resource_presets[0])

        return None

    def _build_export_list(self, preset_url: str) -> list:
        """
        构建 exportList。

        根据 settings.export_current_ts_only 决定：
        - True: 仅包含当前活动 Texture Set（与帧扫描范围一致）
        - False: 包含所有 Texture Set（原始行为）

        此列表在整个导出过程中不变，仅需构建一次。

        Args:
            preset_url: 导出预设的 URL 字符串

        Returns:
            exportList 列表
        """
        if self._settings.export_current_ts_only:
            return self._build_active_ts_export_list(preset_url)
        else:
            return self._build_all_ts_export_list(preset_url)

    def _build_active_ts_export_list(self, preset_url: str) -> list:
        """
        仅构建当前活动 Texture Set 的 exportList 条目。

        Args:
            preset_url: 导出预设的 URL 字符串

        Returns:
            exportList 列表（仅含一个条目）
        """
        export_list = []
        try:
            active_stack = textureset.get_active_stack()
            if active_stack is not None:
                export_list.append({
                    "rootPath": str(active_stack),
                    "exportPreset": preset_url,
                })
                print(f"[SequenceAnimation] 仅导出当前纹理集: {active_stack}")
            else:
                print("[SequenceAnimation] 警告: 无法获取活动纹理集，回退到全部导出")
                export_list = self._build_all_ts_export_list(preset_url)
        except Exception as e:
            print(f"[SequenceAnimation] 构建活动纹理集 exportList 异常: {e}")
            export_list = self._build_all_ts_export_list(preset_url)
        return export_list

    def _build_all_ts_export_list(self, preset_url: str) -> list:
        """
        构建全部 Texture Set 的 exportList（每个 TextureSet 一个条目）。

        Args:
            preset_url: 导出预设的 URL 字符串

        Returns:
            exportList 列表
        """
        export_list = []
        try:
            all_ts = textureset.all_texture_sets()
            for ts in all_ts:
                stack = None
                if hasattr(ts, 'get_stack'):
                    stack = ts.get_stack()

                export_list.append({
                    "rootPath": str(stack) if stack else ts.name(),
                    "exportPreset": preset_url,
                })

        except Exception:
            pass

        return export_list

    def _build_export_config(self, preset_url: str,
                             export_path: str,
                             export_list: list = None) -> dict:
        """
        构建 SP 导出配置字典。

        Args:
            preset_url: 导出预设的 URL 字符串
            export_path: 本帧的导出目录路径
            export_list: 预构建的 exportList（可选，传入则复用，
                         避免每帧重复获取 TextureSet 列表）
        """
        settings = self._settings

        # 如果未传入 export_list，则构建（兼容旧调用方式）
        if export_list is None:
            export_list = self._build_export_list(preset_url)

        config = {
            "exportPath": export_path,
            "exportShaderParams": False,
            "defaultExportPreset": preset_url,
            "exportList": export_list,
            "exportParameters": [
                {
                    "parameters": {
                        "fileFormat": settings.file_format,
                        "bitDepth": str(settings.bit_depth),
                        "dithering": True,
                        "paddingAlgorithm": settings.padding_algorithm,
                        **({"dilationDistance": settings.dilation_distance}
                           if settings.padding_algorithm
                           in ExportSettings.ALGORITHMS_NEED_DILATION
                           else {}),
                        **({"sizeLog2": settings.texture_size_log2}
                           if settings.texture_size_log2 > 0 else {}),
                    }
                }
            ],
        }

        return config

    def _collect_exported_files(self, result, export_path: str,
                               timestamp_before: float) -> list:
        """
        收集本帧导出产生的文件路径列表。

        优先从 SP 导出结果的 textures 字段解析；如果获取不到，
        则回退到扫描 export_path 目录中修改时间晚于 timestamp_before 的文件。

        Args:
            result: sp_export.export_project_textures 的返回值
            export_path: 导出目录路径
            timestamp_before: 导出前记录的时间戳

        Returns:
            文件绝对路径列表
        """
        files = []

        # 策略 1: 从 result.textures 解析
        try:
            if hasattr(result, 'textures') and result.textures:
                textures = result.textures
                # textures 通常是 dict: {texture_set_name: [filepath, ...]}
                if isinstance(textures, dict):
                    for file_list in textures.values():
                        if isinstance(file_list, (list, tuple)):
                            files.extend(str(f) for f in file_list)
                elif isinstance(textures, (list, tuple)):
                    files.extend(str(f) for f in textures)

                if files:
                    # 过滤：仅保留确实存在的文件
                    files = [f for f in files if os.path.isfile(f)]
                    if files:
                        return files
        except Exception as e:
            print(f"[SequenceAnimation] 从 result.textures 解析文件列表失败: {e}")

        # 策略 2: 扫描目录，根据修改时间判断
        try:
            for fname in os.listdir(export_path):
                fpath = os.path.join(export_path, fname)
                if os.path.isfile(fpath):
                    if os.path.getmtime(fpath) >= timestamp_before:
                        files.append(fpath)
        except Exception as e:
            print(f"[SequenceAnimation] 扫描导出目录失败: {e}")

        return files

    def _rename_exported_files_with_frame_suffix(
            self, result, export_path: str,
            frame_num_str: str, timestamp_before: float) -> int:
        """
        对导出产生的文件进行重命名，在文件名末尾（扩展名之前）追加帧号后缀。

        例: DefaultMaterial_BaseColor.tga → DefaultMaterial_BaseColor_0003.tga

        Args:
            result: sp_export.export_project_textures 的返回值
            export_path: 导出目录路径
            frame_num_str: 帧号字符串（如 "0003"）
            timestamp_before: 导出前记录的时间戳

        Returns:
            成功重命名的文件数量
        """
        files = self._collect_exported_files(
            result, export_path, timestamp_before)

        if not files:
            print(f"[SequenceAnimation] 帧 {frame_num_str}: "
                  f"未找到需要重命名的导出文件")
            return 0

        renamed_count = 0
        for filepath in files:
            try:
                dir_name = os.path.dirname(filepath)
                base_name = os.path.basename(filepath)
                name, ext = os.path.splitext(base_name)
                new_name = f"{name}_{frame_num_str}{ext}"
                new_path = os.path.join(dir_name, new_name)

                os.rename(filepath, new_path)
                renamed_count += 1
            except OSError as e:
                print(f"[SequenceAnimation] 重命名失败: "
                      f"{filepath} → {e}")

        if renamed_count > 0:
            print(f"[SequenceAnimation] 帧 {frame_num_str}: "
                  f"已重命名 {renamed_count} 个文件")
        return renamed_count

    def _notify_finished(self, success: bool, message: str):
        """通知导出完成。"""
        if self._on_finished:
            self._on_finished(success, message)
