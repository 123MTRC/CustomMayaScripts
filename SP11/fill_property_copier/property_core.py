# -*- coding: utf-8 -*-
"""
Fill Property Copier - Core Logic
核心逻辑模块：读取和应用图层/Mask 的填充属性（映射方式、UV Wrap、平铺、旋转、偏移、
3D 映射设置等），以及 BaseColor 纯色颜色值的读取与应用。
支持不同映射模式之间的智能适配。
"""

import substance_painter.layerstack as sp_layerstack
import substance_painter.textureset as sp_textureset
import substance_painter.project as sp_project
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field


# ============================================================
# 应用结果数据结构
# ============================================================

@dataclass
class ApplyResult:
    """单个图层的应用结果，包含详细的应用/跳过信息。"""
    layer_name: str = ""
    success: bool = False
    applied: List[str] = field(default_factory=list)   # 成功应用的参数名列表
    skipped: List[str] = field(default_factory=list)    # 因不兼容而跳过的参数名列表
    errors: List[str] = field(default_factory=list)     # 出错的参数名列表


# ============================================================
# 属性数据结构
# ============================================================

class FillProperties:
    """存储填充图层/效果的投射与 UV 变换属性，支持 UV 映射和 3D 映射两套参数。"""

    def __init__(self):
        # ---- 映射模式 ----
        self.projection_mode: Optional[Any] = None
        self.projection_mode_name: str = ""

        # ---- UV 转换参数（所有映射模式共有）----
        self.uv_scale: Optional[list] = None       # [u, v] 平铺比例
        self.uv_rotation: Optional[float] = None    # 旋转角度
        self.uv_offset: Optional[list] = None       # [u, v] 偏移（仅 UV 映射有）

        # ---- UV Wrap 模式（仅 UV 映射有）----
        self.uv_wrap: Optional[Any] = None
        self.uv_wrap_name: str = ""

        # ---- 3D 映射设置（仅 Tri-planar / Planar 等有，来自 projection_3d 子对象）----
        self.has_3d_params: bool = False
        self.offset_3d: Optional[list] = None       # [x, y, z]
        self.rotation_3d: Optional[list] = None     # [x, y, z]
        self.scale_3d: Optional[list] = None        # [x, y, z]

        # ---- Tri-planar 额外参数 ----
        self.filtering_mode: Optional[Any] = None
        self.filtering_mode_name: str = ""
        self.hardness: Optional[float] = None
        self.shape_crop_mode: Optional[Any] = None
        self.shape_crop_mode_name: str = ""

        # ---- 源信息 ----
        self.source_layer_name: str = ""
        self.source_type: str = ""

        # ---- 完整投射参数对象（用于精确复制）----
        self._raw_projection_params: Optional[Any] = None

    def is_valid(self) -> bool:
        """检查是否已记录有效的属性。"""
        return self._raw_projection_params is not None

    def is_uv_mode(self) -> bool:
        """判断源映射模式是否为 UV 映射（无 3D 参数）。"""
        return not self.has_3d_params

    def is_3d_mode(self) -> bool:
        """判断源映射模式是否具有 3D 映射参数（Tri-planar / Planar 等）。"""
        return self.has_3d_params

    def to_display_dict(self) -> Dict[str, str]:
        """返回用于 UI 显示的属性字典，按区域分组。"""
        info = {}
        info["来源图层"] = self.source_layer_name
        info["来源类型"] = self.source_type
        info["映射模式"] = self.projection_mode_name or "未知"

        # -- UV Wrap (仅 UV 映射) --
        if self.uv_wrap is not None:
            info["UV Wrap"] = self.uv_wrap_name or "未知"

        # -- UV 转换 --
        info["--- UV 转换 ---"] = ""

        if self.uv_scale is not None:
            info["UV 平铺"] = f"U={self.uv_scale[0]:.4f}, V={self.uv_scale[1]:.4f}"
        else:
            info["UV 平铺"] = "N/A"

        if self.uv_rotation is not None:
            info["UV 旋转"] = f"{self.uv_rotation:.2f}°"
        else:
            info["UV 旋转"] = "N/A"

        if self.uv_offset is not None:
            info["UV 偏移"] = f"U={self.uv_offset[0]:.4f}, V={self.uv_offset[1]:.4f}"
        else:
            info["UV 偏移"] = "N/A"

        # -- 3D 映射设置 --
        if self.has_3d_params:
            info["--- 3D 映射设置 ---"] = ""

            if self.offset_3d is not None:
                info["3D 偏移"] = (
                    f"X={self.offset_3d[0]:.4f}, "
                    f"Y={self.offset_3d[1]:.4f}, "
                    f"Z={self.offset_3d[2]:.4f}"
                )
            else:
                info["3D 偏移"] = "N/A"

            if self.rotation_3d is not None:
                info["3D 旋转"] = (
                    f"X={self.rotation_3d[0]:.2f}°, "
                    f"Y={self.rotation_3d[1]:.2f}°, "
                    f"Z={self.rotation_3d[2]:.2f}°"
                )
            else:
                info["3D 旋转"] = "N/A"

            if self.scale_3d is not None:
                info["3D 比例"] = (
                    f"X={self.scale_3d[0]:.4f}, "
                    f"Y={self.scale_3d[1]:.4f}, "
                    f"Z={self.scale_3d[2]:.4f}"
                )
            else:
                info["3D 比例"] = "N/A"

        # -- Tri-planar 额外参数 --
        if self.filtering_mode is not None or self.hardness is not None or self.shape_crop_mode is not None:
            info["--- Tri-planar 设置 ---"] = ""

            if self.filtering_mode is not None:
                info["过滤模式"] = self.filtering_mode_name or "未知"

            if self.hardness is not None:
                info["硬度"] = f"{self.hardness:.4f}"

            if self.shape_crop_mode is not None:
                info["裁剪模式"] = self.shape_crop_mode_name or "未知"

        return info

    def __repr__(self):
        parts = [
            f"FillProperties(layer='{self.source_layer_name}'",
            f"type='{self.source_type}'",
            f"projection='{self.projection_mode_name}'",
        ]
        if self.uv_wrap is not None:
            parts.append(f"wrap='{self.uv_wrap_name}'")
        parts.append(f"scale={self.uv_scale}")
        parts.append(f"rotation={self.uv_rotation}")
        if self.uv_offset is not None:
            parts.append(f"offset={self.uv_offset}")
        if self.has_3d_params:
            parts.append(f"3d_offset={self.offset_3d}")
            parts.append(f"3d_rotation={self.rotation_3d}")
            parts.append(f"3d_scale={self.scale_3d}")
        if self.filtering_mode is not None:
            parts.append(f"filtering='{self.filtering_mode_name}'")
        if self.hardness is not None:
            parts.append(f"hardness={self.hardness:.4f}")
        if self.shape_crop_mode is not None:
            parts.append(f"crop='{self.shape_crop_mode_name}'")
        return ", ".join(parts) + ")"


# ============================================================
# 辅助：枚举转名称
# ============================================================

def _get_projection_mode_name(mode) -> str:
    try:
        return mode.name
    except AttributeError:
        return str(mode)


def _get_uv_wrap_name(wrap) -> str:
    try:
        return wrap.name
    except AttributeError:
        return str(wrap)


# ============================================================
# 辅助：获取图层类型名称
# ============================================================

def _get_node_type_name(layer) -> str:
    try:
        node_type = layer.get_type()
        return node_type.name
    except Exception:
        return "Unknown"


# ============================================================
# 辅助：安全读取 3 分量向量
# ============================================================

def _read_vec3(obj) -> Optional[list]:
    """从对象中尝试读取 [x, y, z] 三维向量。"""
    if obj is None:
        return None
    # 可能是 list/tuple
    if isinstance(obj, (list, tuple)):
        return [float(v) for v in obj[:3]]
    # 可能是有 x/y/z 属性的对象
    if hasattr(obj, 'x') and hasattr(obj, 'y') and hasattr(obj, 'z'):
        return [float(obj.x), float(obj.y), float(obj.z)]
    # 可能可以直接迭代
    try:
        vals = list(obj)
        if len(vals) >= 3:
            return [float(v) for v in vals[:3]]
    except (TypeError, ValueError):
        pass
    return None


def _read_vec2(obj) -> Optional[list]:
    """从对象中尝试读取 [u, v] 二维向量。"""
    if obj is None:
        return None
    if isinstance(obj, (list, tuple)):
        return [float(v) for v in obj[:2]]
    if hasattr(obj, 'x') and hasattr(obj, 'y'):
        return [float(obj.x), float(obj.y)]
    try:
        vals = list(obj)
        if len(vals) >= 2:
            return [float(v) for v in vals[:2]]
    except (TypeError, ValueError):
        pass
    return None


# ============================================================
# 辅助：判断是否为填充类型
# ============================================================

_FILL_TYPES = None


def _get_fill_types():
    global _FILL_TYPES
    if _FILL_TYPES is None:
        _FILL_TYPES = set()
        for type_name in ["FillLayer", "FillEffect"]:
            if hasattr(sp_layerstack.NodeType, type_name):
                _FILL_TYPES.add(getattr(sp_layerstack.NodeType, type_name))
    return _FILL_TYPES


def is_fill_node(layer) -> bool:
    try:
        return layer.get_type() in _get_fill_types()
    except Exception:
        return False


# ============================================================
# 辅助：检测目标图层的映射模式是否有 3D 参数
# ============================================================

def _target_has_3d_params(target_params) -> bool:
    """检查目标图层的投射参数中是否包含 3D 映射设置。"""
    # 检查多种可能的属性名
    for attr_name in ('offset_3d', 'position', 'offset',
                      'rotation_3d', 'scale_3d',
                      'translation'):
        if hasattr(target_params, attr_name):
            # offset 也可能是 UV 的 2D offset，需要看是否是 3 分量
            val = getattr(target_params, attr_name)
            vec = _read_vec3(val)
            if vec is not None:
                return True
    return False


def _target_has_uv_wrap(target_params) -> bool:
    """检查目标图层的投射参数中是否包含 UV Wrap。"""
    return hasattr(target_params, 'uv_wrap') or hasattr(target_params, 'texture_wrap')


# ============================================================
# 核心：读取图层填充属性
# ============================================================

def read_fill_properties(layer) -> Optional[FillProperties]:
    """
    从指定图层或效果节点读取填充属性（包含 UV 转换和 3D 映射设置）。

    Args:
        layer: substance_painter.layerstack 节点对象

    Returns:
        FillProperties 对象，读取失败则返回 None
    """
    if not sp_project.is_open():
        print("[FillPropertyCopier] 没有打开的项目")
        return None

    props = FillProperties()
    props.source_layer_name = layer.get_name()
    props.source_type = _get_node_type_name(layer)

    try:
        # ---- 映射模式 ----
        proj_mode = layer.get_projection_mode()
        props.projection_mode = proj_mode
        props.projection_mode_name = _get_projection_mode_name(proj_mode)

        # ---- 投射参数 ----
        proj_params = layer.get_projection_parameters()
        props._raw_projection_params = proj_params

        # ---- UV 转换 ----
        if hasattr(proj_params, 'uv_transformation'):
            uv_xform = proj_params.uv_transformation

            # 平铺比例 (Scale)
            if hasattr(uv_xform, 'scale'):
                scale = uv_xform.scale
                vec = _read_vec2(scale)
                if vec is not None:
                    props.uv_scale = vec
                else:
                    props.uv_scale = [float(scale), float(scale)]

            # 旋转
            if hasattr(uv_xform, 'rotation'):
                props.uv_rotation = float(uv_xform.rotation)

            # UV 偏移（2D）
            if hasattr(uv_xform, 'offset'):
                offset = uv_xform.offset
                vec = _read_vec2(offset)
                if vec is not None:
                    props.uv_offset = vec
                else:
                    props.uv_offset = [float(offset), float(offset)]

        # ---- UV Wrap ----
        if hasattr(proj_params, 'uv_wrap'):
            props.uv_wrap = proj_params.uv_wrap
            props.uv_wrap_name = _get_uv_wrap_name(proj_params.uv_wrap)
        elif hasattr(proj_params, 'texture_wrap'):
            props.uv_wrap = proj_params.texture_wrap
            props.uv_wrap_name = _get_uv_wrap_name(proj_params.texture_wrap)

        # ---- 3D 映射设置 ----
        _read_3d_params(proj_params, props)

        print(f"[FillPropertyCopier] 已读取属性: {props}")
        return props

    except Exception as e:
        print(f"[FillPropertyCopier] 读取属性失败 ({props.source_layer_name}): {e}")
        import traceback
        traceback.print_exc()
        return None


def _read_3d_params(proj_params, props: FillProperties):
    """从投射参数中提取 3D 映射设置（偏移/旋转/比例 XYZ）及额外参数。

    Substance Painter 的 TriplanarProjectionParams 结构：
        proj_params.projection_3d  →  Projection3DParams
            .offset   = [x, y, z]
            .rotation = [x, y, z]
            .scale    = [x, y, z]
        proj_params.filtering_mode   →  FilteringMode 枚举
        proj_params.hardness         →  float
        proj_params.shape_crop_mode  →  ShapeCropMode 枚举
    """
    found_any = False

    # ---- 3D 映射设置（通过 projection_3d 子对象）----
    proj_3d = getattr(proj_params, 'projection_3d', None)
    if proj_3d is not None:
        # 3D 偏移
        for attr_name in ('offset', 'offset_3d', 'position', 'translation'):
            if hasattr(proj_3d, attr_name):
                vec = _read_vec3(getattr(proj_3d, attr_name))
                if vec is not None:
                    props.offset_3d = vec
                    found_any = True
                    break

        # 3D 旋转
        for attr_name in ('rotation', 'rotation_3d'):
            if hasattr(proj_3d, attr_name):
                vec = _read_vec3(getattr(proj_3d, attr_name))
                if vec is not None:
                    props.rotation_3d = vec
                    found_any = True
                    break

        # 3D 比例
        for attr_name in ('scale', 'scale_3d'):
            if hasattr(proj_3d, attr_name):
                vec = _read_vec3(getattr(proj_3d, attr_name))
                if vec is not None:
                    props.scale_3d = vec
                    found_any = True
                    break
    else:
        # 兼容：某些映射模式可能 3D 参数直接在 proj_params 顶层
        for attr_name in ('offset_3d', 'position', 'translation'):
            if hasattr(proj_params, attr_name):
                vec = _read_vec3(getattr(proj_params, attr_name))
                if vec is not None:
                    props.offset_3d = vec
                    found_any = True
                    break

        for attr_name in ('rotation_3d',):
            if hasattr(proj_params, attr_name):
                vec = _read_vec3(getattr(proj_params, attr_name))
                if vec is not None:
                    props.rotation_3d = vec
                    found_any = True
                    break

        for attr_name in ('scale_3d',):
            if hasattr(proj_params, attr_name):
                vec = _read_vec3(getattr(proj_params, attr_name))
                if vec is not None:
                    props.scale_3d = vec
                    found_any = True
                    break

    props.has_3d_params = found_any

    # ---- Tri-planar 额外参数 ----
    # 过滤模式
    if hasattr(proj_params, 'filtering_mode'):
        props.filtering_mode = proj_params.filtering_mode
        try:
            props.filtering_mode_name = proj_params.filtering_mode.name
        except AttributeError:
            props.filtering_mode_name = str(proj_params.filtering_mode)

    # 硬度
    if hasattr(proj_params, 'hardness'):
        try:
            props.hardness = float(proj_params.hardness)
        except (TypeError, ValueError):
            pass

    # 裁剪模式
    if hasattr(proj_params, 'shape_crop_mode'):
        props.shape_crop_mode = proj_params.shape_crop_mode
        try:
            props.shape_crop_mode_name = proj_params.shape_crop_mode.name
        except AttributeError:
            props.shape_crop_mode_name = str(proj_params.shape_crop_mode)


# ============================================================
# 核心：应用填充属性到目标图层（智能适配版）
# ============================================================

def apply_fill_properties(layer, props: FillProperties,
                          apply_projection_mode: bool = True,
                          apply_uv_scale: bool = True,
                          apply_uv_rotation: bool = True,
                          apply_uv_offset: bool = True,
                          apply_uv_wrap: bool = True,
                          apply_3d_offset: bool = True,
                          apply_3d_rotation: bool = True,
                          apply_3d_scale: bool = True,
                          apply_filtering_mode: bool = True,
                          apply_hardness: bool = True,
                          apply_shape_crop_mode: bool = True) -> ApplyResult:
    """
    将记录的填充属性智能应用到指定图层。
    会自动检测目标图层支持的参数，跳过不兼容的部分并详细报告。

    Returns:
        ApplyResult 对象，包含 applied/skipped/errors 详情
    """
    result = ApplyResult()
    result.layer_name = layer.get_name()

    if not props.is_valid():
        result.errors.append("没有有效的属性数据")
        return result

    try:
        # ======== 1) 应用映射模式 ========
        if apply_projection_mode and props.projection_mode is not None:
            try:
                layer.set_projection_mode(props.projection_mode)
                result.applied.append("映射模式")
            except Exception as e:
                result.errors.append(f"映射模式: {e}")

        # 切换模式后重新获取目标参数（参数结构可能已改变）
        target_params = layer.get_projection_parameters()
        modified = False

        # ======== 2) UV 转换参数 ========
        if hasattr(target_params, 'uv_transformation'):
            uv_xform = target_params.uv_transformation

            # -- UV 平铺 --
            if apply_uv_scale and props.uv_scale is not None:
                if hasattr(uv_xform, 'scale'):
                    try:
                        uv_xform.scale = props.uv_scale
                        result.applied.append("UV 平铺")
                        modified = True
                    except Exception as e:
                        result.errors.append(f"UV 平铺: {e}")
                else:
                    result.skipped.append("UV 平铺（目标不支持）")

            # -- UV 旋转 --
            if apply_uv_rotation and props.uv_rotation is not None:
                if hasattr(uv_xform, 'rotation'):
                    try:
                        uv_xform.rotation = props.uv_rotation
                        result.applied.append("UV 旋转")
                        modified = True
                    except Exception as e:
                        result.errors.append(f"UV 旋转: {e}")
                else:
                    result.skipped.append("UV 旋转（目标不支持）")

            # -- UV 偏移 --
            if apply_uv_offset and props.uv_offset is not None:
                if hasattr(uv_xform, 'offset'):
                    try:
                        uv_xform.offset = props.uv_offset
                        result.applied.append("UV 偏移")
                        modified = True
                    except Exception as e:
                        result.errors.append(f"UV 偏移: {e}")
                else:
                    result.skipped.append("UV 偏移（目标不支持）")

        # ======== 3) UV Wrap ========
        if apply_uv_wrap and props.uv_wrap is not None:
            if hasattr(target_params, 'uv_wrap'):
                try:
                    target_params.uv_wrap = props.uv_wrap
                    result.applied.append("UV Wrap")
                    modified = True
                except Exception as e:
                    result.errors.append(f"UV Wrap: {e}")
            elif hasattr(target_params, 'texture_wrap'):
                try:
                    target_params.texture_wrap = props.uv_wrap
                    result.applied.append("UV Wrap")
                    modified = True
                except Exception as e:
                    result.errors.append(f"UV Wrap: {e}")
            else:
                result.skipped.append("UV Wrap（目标映射模式不支持）")

        # ======== 4) 3D 映射设置（通过 projection_3d 子对象）========
        target_proj_3d = getattr(target_params, 'projection_3d', None)

        # -- 3D 偏移 --
        if apply_3d_offset and props.offset_3d is not None:
            applied_3d_offset = False
            if target_proj_3d is not None:
                for attr_name in ('offset', 'offset_3d', 'position', 'translation'):
                    if hasattr(target_proj_3d, attr_name):
                        try:
                            setattr(target_proj_3d, attr_name, props.offset_3d)
                            result.applied.append("3D 偏移")
                            modified = True
                            applied_3d_offset = True
                        except Exception as e:
                            result.errors.append(f"3D 偏移: {e}")
                        break
            # 兼容：顶层属性
            if not applied_3d_offset and target_proj_3d is None:
                for attr_name in ('offset_3d', 'position', 'translation'):
                    if hasattr(target_params, attr_name):
                        try:
                            setattr(target_params, attr_name, props.offset_3d)
                            result.applied.append("3D 偏移")
                            modified = True
                            applied_3d_offset = True
                        except Exception as e:
                            result.errors.append(f"3D 偏移: {e}")
                        break
            if not applied_3d_offset and not any("3D 偏移" in e for e in result.errors):
                result.skipped.append("3D 偏移（目标映射模式不支持）")

        # -- 3D 旋转 --
        if apply_3d_rotation and props.rotation_3d is not None:
            applied_3d_rotation = False
            if target_proj_3d is not None:
                for attr_name in ('rotation', 'rotation_3d'):
                    if hasattr(target_proj_3d, attr_name):
                        try:
                            setattr(target_proj_3d, attr_name, props.rotation_3d)
                            result.applied.append("3D 旋转")
                            modified = True
                            applied_3d_rotation = True
                        except Exception as e:
                            result.errors.append(f"3D 旋转: {e}")
                        break
            if not applied_3d_rotation and target_proj_3d is None:
                for attr_name in ('rotation_3d',):
                    if hasattr(target_params, attr_name):
                        val = getattr(target_params, attr_name)
                        if _read_vec3(val) is not None:
                            try:
                                setattr(target_params, attr_name, props.rotation_3d)
                                result.applied.append("3D 旋转")
                                modified = True
                                applied_3d_rotation = True
                            except Exception as e:
                                result.errors.append(f"3D 旋转: {e}")
                            break
            if not applied_3d_rotation and not any("3D 旋转" in e for e in result.errors):
                result.skipped.append("3D 旋转（目标映射模式不支持）")

        # -- 3D 比例 --
        if apply_3d_scale and props.scale_3d is not None:
            applied_3d_scale = False
            if target_proj_3d is not None:
                for attr_name in ('scale', 'scale_3d'):
                    if hasattr(target_proj_3d, attr_name):
                        try:
                            setattr(target_proj_3d, attr_name, props.scale_3d)
                            result.applied.append("3D 比例")
                            modified = True
                            applied_3d_scale = True
                        except Exception as e:
                            result.errors.append(f"3D 比例: {e}")
                        break
            if not applied_3d_scale and target_proj_3d is None:
                for attr_name in ('scale_3d',):
                    if hasattr(target_params, attr_name):
                        val = getattr(target_params, attr_name)
                        if _read_vec3(val) is not None:
                            try:
                                setattr(target_params, attr_name, props.scale_3d)
                                result.applied.append("3D 比例")
                                modified = True
                                applied_3d_scale = True
                            except Exception as e:
                                result.errors.append(f"3D 比例: {e}")
                            break
            if not applied_3d_scale and not any("3D 比例" in e for e in result.errors):
                result.skipped.append("3D 比例（目标映射模式不支持）")

        # ======== 5) Tri-planar 额外参数 ========
        # -- 过滤模式 --
        if apply_filtering_mode and props.filtering_mode is not None:
            if hasattr(target_params, 'filtering_mode'):
                try:
                    target_params.filtering_mode = props.filtering_mode
                    result.applied.append("过滤模式")
                    modified = True
                except Exception as e:
                    result.errors.append(f"过滤模式: {e}")
            else:
                result.skipped.append("过滤模式（目标映射模式不支持）")

        # -- 硬度 --
        if apply_hardness and props.hardness is not None:
            if hasattr(target_params, 'hardness'):
                try:
                    target_params.hardness = props.hardness
                    result.applied.append("硬度")
                    modified = True
                except Exception as e:
                    result.errors.append(f"硬度: {e}")
            else:
                result.skipped.append("硬度（目标映射模式不支持）")

        # -- 裁剪模式 --
        if apply_shape_crop_mode and props.shape_crop_mode is not None:
            if hasattr(target_params, 'shape_crop_mode'):
                try:
                    target_params.shape_crop_mode = props.shape_crop_mode
                    result.applied.append("裁剪模式")
                    modified = True
                except Exception as e:
                    result.errors.append(f"裁剪模式: {e}")
            else:
                result.skipped.append("裁剪模式（目标映射模式不支持）")

        # ======== 6) 写回参数 ========
        if modified:
            layer.set_projection_parameters(target_params)

        result.success = len(result.errors) == 0
        status_parts = []
        if result.applied:
            status_parts.append(f"应用 {len(result.applied)} 项")
        if result.skipped:
            status_parts.append(f"跳过 {len(result.skipped)} 项")
        if result.errors:
            status_parts.append(f"失败 {len(result.errors)} 项")
        print(f"[FillPropertyCopier] {result.layer_name}: {', '.join(status_parts)}")

        return result

    except Exception as e:
        print(f"[FillPropertyCopier] 应用属性失败 ({result.layer_name}): {e}")
        import traceback
        traceback.print_exc()
        result.errors.append(str(e))
        return result


# ============================================================
# 辅助：获取当前活跃的 NodeStack
# ============================================================

def _get_active_stack():
    """获取当前活跃 Texture Set 的 Stack。"""
    try:
        active_stack = sp_textureset.get_active_stack()
        if active_stack is not None:
            return active_stack
    except Exception:
        pass

    try:
        all_ts = sp_textureset.all_texture_sets()
        if all_ts:
            return all_ts[0].get_stack()
    except Exception:
        pass

    return None


# ============================================================
# 获取选中的图层节点
# ============================================================

def get_selected_nodes() -> list:
    """获取当前选中的图层节点列表。"""
    if not sp_project.is_open():
        return []

    try:
        stack = _get_active_stack()
        if stack is None:
            print("[FillPropertyCopier] 无法获取当前活跃的图层堆栈")
            return []

        selected = sp_layerstack.get_selected_nodes(stack)
        return list(selected) if selected else []
    except Exception as e:
        print(f"[FillPropertyCopier] 获取选中节点失败: {e}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================
# 批量应用到选中的图层
# ============================================================

def apply_to_selected(props: FillProperties,
                      apply_projection_mode: bool = True,
                      apply_uv_scale: bool = True,
                      apply_uv_rotation: bool = True,
                      apply_uv_offset: bool = True,
                      apply_uv_wrap: bool = True,
                      apply_3d_offset: bool = True,
                      apply_3d_rotation: bool = True,
                      apply_3d_scale: bool = True,
                      apply_filtering_mode: bool = True,
                      apply_hardness: bool = True,
                      apply_shape_crop_mode: bool = True) -> List[ApplyResult]:
    """
    将属性应用到所有选中的图层节点。

    Returns:
        ApplyResult 列表
    """
    results = []
    selected = get_selected_nodes()

    if not selected:
        print("[FillPropertyCopier] 没有选中的图层")
        return results

    try:
        with sp_layerstack.ScopedModification("填充属性复制"):
            for node in selected:
                r = apply_fill_properties(
                    node, props,
                    apply_projection_mode=apply_projection_mode,
                    apply_uv_scale=apply_uv_scale,
                    apply_uv_rotation=apply_uv_rotation,
                    apply_uv_offset=apply_uv_offset,
                    apply_uv_wrap=apply_uv_wrap,
                    apply_3d_offset=apply_3d_offset,
                    apply_3d_rotation=apply_3d_rotation,
                    apply_3d_scale=apply_3d_scale,
                    apply_filtering_mode=apply_filtering_mode,
                    apply_hardness=apply_hardness,
                    apply_shape_crop_mode=apply_shape_crop_mode,
                )
                results.append(r)
    except Exception as e:
        print(f"[FillPropertyCopier] 批量应用失败: {e}")
        import traceback
        traceback.print_exc()

    return results


# ============================================================
# 递归获取图层信息（用于调试/预览）
# ============================================================

def get_layer_info(layer, depth: int = 0) -> str:
    """获取图层的简要信息字符串。"""
    indent = "  " * depth
    name = layer.get_name()
    node_type = _get_node_type_name(layer)
    return f"{indent}[{node_type}] {name}"


# ============================================================
# BaseColor 纯色 - 数据结构
# ============================================================

@dataclass
class BaseColorData:
    """存储 BaseColor 纯色颜色数据。"""
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0
    source_layer_name: str = ""
    channel_name: str = "BaseColor"
    valid: bool = False

    # 探测信息（调试用）
    api_method: str = ""   # 记录使用了哪种 API 方法读取

    def to_rgb_tuple(self) -> Tuple[float, float, float]:
        return (self.r, self.g, self.b)

    def to_rgba_tuple(self) -> Tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)

    def to_rgb_int(self) -> Tuple[int, int, int]:
        return (
            max(0, min(255, int(self.r * 255 + 0.5))),
            max(0, min(255, int(self.g * 255 + 0.5))),
            max(0, min(255, int(self.b * 255 + 0.5))),
        )

    def to_hex(self) -> str:
        r, g, b = self.to_rgb_int()
        return f"#{r:02X}{g:02X}{b:02X}"

    def to_display_dict(self) -> Dict[str, str]:
        info = {}
        info["来源图层"] = self.source_layer_name
        info["通道"] = self.channel_name
        r, g, b = self.to_rgb_int()
        info["颜色 (RGB)"] = f"R={r}, G={g}, B={b}"
        info["颜色 (HEX)"] = self.to_hex()
        info["颜色 (Float)"] = f"R={self.r:.4f}, G={self.g:.4f}, B={self.b:.4f}"
        if self.api_method:
            info["API 方法"] = self.api_method
        return info

    def __repr__(self):
        return (
            f"BaseColorData(r={self.r:.4f}, g={self.g:.4f}, b={self.b:.4f}, "
            f"a={self.a:.4f}, layer='{self.source_layer_name}', "
            f"method='{self.api_method}')"
        )


# ============================================================
# BaseColor - 辅助：获取 BaseColor 通道类型
# ============================================================

def _get_basecolor_channel_type():
    """获取 BaseColor 对应的 ChannelType 枚举值。"""
    # 不同 SP 版本可能有不同的属性名
    for attr_name in ("BaseColor", "basecolor", "Diffuse", "diffuse",
                      "Color", "color", "Albedo", "albedo"):
        if hasattr(sp_textureset.ChannelType, attr_name):
            return getattr(sp_textureset.ChannelType, attr_name)
    return None


def _get_channel_type_by_name(name: str):
    """根据通道名称获取 ChannelType 枚举值。"""
    if hasattr(sp_textureset.ChannelType, name):
        return getattr(sp_textureset.ChannelType, name)
    return None


# ============================================================
# BaseColor - 探测函数（在 SP 中运行可获取 API 细节）
# ============================================================

def probe_layer_api(layer) -> str:
    """
    探测图层对象的可用 API 方法，返回详细报告。
    可在 SP Python 控制台中运行：
        from fill_property_copier.property_core import probe_layer_api, get_selected_nodes
        nodes = get_selected_nodes()
        if nodes: print(probe_layer_api(nodes[0]))
    """
    lines = []
    lines.append(f"=== 图层 API 探测报告 ===")
    lines.append(f"图层名称: {layer.get_name()}")
    lines.append(f"图层类型: {_get_node_type_name(layer)}")
    lines.append("")

    # 1. 列出所有公共方法/属性
    lines.append("--- 图层对象属性和方法 ---")
    for attr in sorted(dir(layer)):
        if attr.startswith('_'):
            continue
        try:
            val = getattr(layer, attr)
            val_type = type(val).__name__
            if callable(val):
                lines.append(f"  {attr}()  [callable]")
            else:
                lines.append(f"  {attr} = {val!r}  [{val_type}]")
        except Exception as e:
            lines.append(f"  {attr}  [ERROR: {e}]")

    # 2. 尝试 source_mode / active_channels
    lines.append("")
    lines.append("--- Source 相关 ---")
    if hasattr(layer, 'source_mode'):
        try:
            lines.append(f"  source_mode = {layer.source_mode!r}")
        except Exception as e:
            lines.append(f"  source_mode ERROR: {e}")

    if hasattr(layer, 'active_channels'):
        try:
            channels = layer.active_channels
            lines.append(f"  active_channels = {channels!r}")
            for ch in channels:
                lines.append(f"    channel: {ch!r}")
                # 尝试 get_source(ch)
                if hasattr(layer, 'get_source'):
                    try:
                        src = layer.get_source(ch)
                        lines.append(f"      get_source({ch!r}) = {src!r}")
                        lines.append(f"      type = {type(src).__name__}")
                        for sattr in sorted(dir(src)):
                            if sattr.startswith('_'):
                                continue
                            try:
                                sval = getattr(src, sattr)
                                lines.append(f"        {sattr} = {sval!r}")
                            except Exception as e2:
                                lines.append(f"        {sattr} ERROR: {e2}")
                    except Exception as e3:
                        lines.append(f"      get_source ERROR: {e3}")
        except Exception as e:
            lines.append(f"  active_channels ERROR: {e}")

    # 3. 尝试 get_source() 无参数
    if hasattr(layer, 'get_source'):
        try:
            src = layer.get_source()
            lines.append(f"  get_source() = {src!r}")
            lines.append(f"  type = {type(src).__name__}")
            for sattr in sorted(dir(src)):
                if sattr.startswith('_'):
                    continue
                try:
                    sval = getattr(src, sattr)
                    lines.append(f"    {sattr} = {sval!r}")
                except Exception as e2:
                    lines.append(f"    {sattr} ERROR: {e2}")
        except Exception as e:
            lines.append(f"  get_source() ERROR: {e}")

    # 4. 尝试 get_property_value / set_property_value
    lines.append("")
    lines.append("--- Property Value 相关 ---")
    for method_name in ('get_property_value', 'set_property_value',
                        'get_channel_color', 'set_channel_color',
                        'get_uniform_color', 'set_uniform_color',
                        'get_channel_source', 'set_channel_source'):
        if hasattr(layer, method_name):
            lines.append(f"  ✓ 有方法: {method_name}")
        else:
            lines.append(f"  ✗ 无方法: {method_name}")

    # 5. ChannelType 可用值
    lines.append("")
    lines.append("--- ChannelType 枚举 ---")
    for attr in sorted(dir(sp_textureset.ChannelType)):
        if attr.startswith('_'):
            continue
        try:
            val = getattr(sp_textureset.ChannelType, attr)
            lines.append(f"  {attr} = {val!r}")
        except Exception:
            pass

    # 6. SourceType / SourceMode 枚举（如果有）
    lines.append("")
    lines.append("--- SourceType / SourceMode 枚举 ---")
    for enum_name in ('SourceType', 'SourceMode', 'FillSourceType'):
        if hasattr(sp_layerstack, enum_name):
            enum_cls = getattr(sp_layerstack, enum_name)
            lines.append(f"  {enum_name}:")
            for attr in sorted(dir(enum_cls)):
                if attr.startswith('_'):
                    continue
                try:
                    val = getattr(enum_cls, attr)
                    lines.append(f"    {attr} = {val!r}")
                except Exception:
                    pass
        else:
            lines.append(f"  ✗ 无枚举: {enum_name}")

    report = "\n".join(lines)
    print(report)
    return report


# ============================================================
# BaseColor - 颜色值提取（多种 fallback 策略）
# ============================================================

def _extract_color_from_value(val) -> Optional[Tuple[float, float, float, float]]:
    """
    从任意颜色值对象中提取 (r, g, b, a)。
    支持多种可能的数据格式。
    """
    if val is None:
        return None

    # 1. 元组/列表
    if isinstance(val, (list, tuple)):
        if len(val) >= 4:
            return (float(val[0]), float(val[1]), float(val[2]), float(val[3]))
        elif len(val) >= 3:
            return (float(val[0]), float(val[1]), float(val[2]), 1.0)

    # 2. 有 r/g/b 属性
    if hasattr(val, 'r') and hasattr(val, 'g') and hasattr(val, 'b'):
        a = float(val.a) if hasattr(val, 'a') else 1.0
        return (float(val.r), float(val.g), float(val.b), a)

    # 3. 有 x/y/z 属性（某些 API 中颜色用 xyz 表示）
    if hasattr(val, 'x') and hasattr(val, 'y') and hasattr(val, 'z'):
        w = float(val.w) if hasattr(val, 'w') else 1.0
        return (float(val.x), float(val.y), float(val.z), w)

    # 4. 有 red/green/blue 属性
    if hasattr(val, 'red') and hasattr(val, 'green') and hasattr(val, 'blue'):
        a = float(val.alpha) if hasattr(val, 'alpha') else 1.0
        return (float(val.red), float(val.green), float(val.blue), a)

    # 5. 可迭代
    try:
        vals = list(val)
        if len(vals) >= 3:
            a = float(vals[3]) if len(vals) >= 4 else 1.0
            return (float(vals[0]), float(vals[1]), float(vals[2]), a)
    except (TypeError, ValueError):
        pass

    # 6. 单值（灰度）
    try:
        f = float(val)
        return (f, f, f, 1.0)
    except (TypeError, ValueError):
        pass

    return None


# ============================================================
# BaseColor - 读取纯色颜色值
# ============================================================

def read_basecolor(layer, channel_name: str = "BaseColor") -> Optional[BaseColorData]:
    """
    从填充图层读取指定通道的纯色颜色值。

    采用多种 fallback 策略尝试不同的 API 方法：
    1. get_source(channel) → source.color / source.uniform_color
    2. get_property_value("basecolor") 或类似
    3. get_channel_color(channel)
    4. get_uniform_color(channel)

    Args:
        layer: substance_painter.layerstack 节点对象
        channel_name: 通道名称，默认 "BaseColor"

    Returns:
        BaseColorData 对象，读取失败返回 None
    """
    if not sp_project.is_open():
        print("[FillPropertyCopier] 没有打开的项目")
        return None

    data = BaseColorData()
    data.source_layer_name = layer.get_name()
    data.channel_name = channel_name

    # 获取 ChannelType 枚举值
    ch_type = _get_channel_type_by_name(channel_name)
    if ch_type is None:
        ch_type = _get_basecolor_channel_type()
    if ch_type is not None:
        print(f"[FillPropertyCopier] 使用通道类型: {ch_type!r}")

    # ---- 策略 1: get_source(channel) ----
    color = _try_read_via_get_source(layer, ch_type)
    if color is not None:
        data.r, data.g, data.b, data.a = color
        data.valid = True
        data.api_method = "get_source(channel)"
        print(f"[FillPropertyCopier] BaseColor 读取成功 (策略1 get_source): {data}")
        return data

    # ---- 策略 2: get_property_value ----
    color = _try_read_via_property_value(layer, channel_name)
    if color is not None:
        data.r, data.g, data.b, data.a = color
        data.valid = True
        data.api_method = "get_property_value"
        print(f"[FillPropertyCopier] BaseColor 读取成功 (策略2 property_value): {data}")
        return data

    # ---- 策略 3: get_channel_color ----
    color = _try_read_via_channel_color(layer, ch_type)
    if color is not None:
        data.r, data.g, data.b, data.a = color
        data.valid = True
        data.api_method = "get_channel_color"
        print(f"[FillPropertyCopier] BaseColor 读取成功 (策略3 channel_color): {data}")
        return data

    # ---- 策略 4: get_uniform_color ----
    color = _try_read_via_uniform_color(layer, ch_type)
    if color is not None:
        data.r, data.g, data.b, data.a = color
        data.valid = True
        data.api_method = "get_uniform_color"
        print(f"[FillPropertyCopier] BaseColor 读取成功 (策略4 uniform_color): {data}")
        return data

    # ---- 策略 5: 遍历 active_channels 尝试匹配 ----
    color = _try_read_via_active_channels(layer, channel_name)
    if color is not None:
        data.r, data.g, data.b, data.a = color
        data.valid = True
        data.api_method = "active_channels scan"
        print(f"[FillPropertyCopier] BaseColor 读取成功 (策略5 active_channels): {data}")
        return data

    print(f"[FillPropertyCopier] 无法从 '{data.source_layer_name}' 读取 BaseColor 颜色。"
          f"请在 SP 控制台运行 probe_layer_api() 获取 API 详情。")
    return None


def _extract_from_color_object(color_obj) -> Optional[Tuple[float, float, float, float]]:
    """
    从 substance_painter.colormanagement.Color 对象中提取 RGBA。

    已知 Color 对象的属性/方法:
      - value: 当前色彩空间下的值（可能是 list/tuple）
      - value_raw: 原始值
      - color_space: 色彩空间标识
      - convert(space): 转换到指定色彩空间
      - sRGB: 获取/创建 sRGB 色彩空间的 Color（可能是属性或方法）
      - working: 获取/创建工作色彩空间的 Color（可能是属性或方法）
    """
    if color_obj is None:
        return None

    obj_type = type(color_obj).__name__
    print(f"[FillPropertyCopier]     Color 对象探测 (type={obj_type}):")

    # 列出对象的所有非下划线属性/方法，辅助调试
    attrs = [a for a in dir(color_obj) if not a.startswith('_')]
    print(f"[FillPropertyCopier]     可用属性/方法: {attrs}")

    # ---- 1. 优先尝试 .value 属性（最直接）----
    if hasattr(color_obj, 'value'):
        try:
            val = color_obj.value
            print(f"[FillPropertyCopier]     → .value = {val!r} (type={type(val).__name__})")
            if callable(val):
                val = val()
                print(f"[FillPropertyCopier]     → .value() = {val!r}")
            extracted = _extract_color_from_value(val)
            if extracted is not None:
                print(f"[FillPropertyCopier]     → 从 .value 提取成功: {extracted}")
                return extracted
        except Exception as e:
            print(f"[FillPropertyCopier]     → .value 异常: {e}")

    # ---- 2. 尝试 .value_raw 属性 ----
    if hasattr(color_obj, 'value_raw'):
        try:
            val = color_obj.value_raw
            print(f"[FillPropertyCopier]     → .value_raw = {val!r} (type={type(val).__name__})")
            if callable(val):
                val = val()
                print(f"[FillPropertyCopier]     → .value_raw() = {val!r}")
            extracted = _extract_color_from_value(val)
            if extracted is not None:
                print(f"[FillPropertyCopier]     → 从 .value_raw 提取成功: {extracted}")
                return extracted
        except Exception as e:
            print(f"[FillPropertyCopier]     → .value_raw 异常: {e}")

    # ---- 3. 尝试 .sRGB（可能是属性返回另一个 Color，再取 value）----
    if hasattr(color_obj, 'sRGB'):
        try:
            srgb_val = color_obj.sRGB
            print(f"[FillPropertyCopier]     → .sRGB = {srgb_val!r} (type={type(srgb_val).__name__})")
            if callable(srgb_val):
                srgb_val = srgb_val()
                print(f"[FillPropertyCopier]     → .sRGB() = {srgb_val!r} (type={type(srgb_val).__name__})")

            # sRGB 可能直接返回 list/tuple
            extracted = _extract_color_from_value(srgb_val)
            if extracted is not None:
                print(f"[FillPropertyCopier]     → 从 .sRGB 直接提取成功: {extracted}")
                return extracted

            # sRGB 可能返回另一个 Color 对象，取其 .value
            if hasattr(srgb_val, 'value'):
                inner_val = srgb_val.value
                if callable(inner_val):
                    inner_val = inner_val()
                print(f"[FillPropertyCopier]     → .sRGB.value = {inner_val!r}")
                extracted = _extract_color_from_value(inner_val)
                if extracted is not None:
                    print(f"[FillPropertyCopier]     → 从 .sRGB.value 提取成功: {extracted}")
                    return extracted
        except Exception as e:
            print(f"[FillPropertyCopier]     → .sRGB 异常: {e}")

    # ---- 4. 尝试 .working（工作色彩空间）----
    if hasattr(color_obj, 'working'):
        try:
            work_val = color_obj.working
            print(f"[FillPropertyCopier]     → .working = {work_val!r} (type={type(work_val).__name__})")
            if callable(work_val):
                work_val = work_val()
                print(f"[FillPropertyCopier]     → .working() = {work_val!r} (type={type(work_val).__name__})")

            extracted = _extract_color_from_value(work_val)
            if extracted is not None:
                print(f"[FillPropertyCopier]     → 从 .working 直接提取成功: {extracted}")
                return extracted

            if hasattr(work_val, 'value'):
                inner_val = work_val.value
                if callable(inner_val):
                    inner_val = inner_val()
                print(f"[FillPropertyCopier]     → .working.value = {inner_val!r}")
                extracted = _extract_color_from_value(inner_val)
                if extracted is not None:
                    print(f"[FillPropertyCopier]     → 从 .working.value 提取成功: {extracted}")
                    return extracted
        except Exception as e:
            print(f"[FillPropertyCopier]     → .working 异常: {e}")

    # ---- 5. 尝试 .convert() 方法 ----
    if hasattr(color_obj, 'convert') and callable(getattr(color_obj, 'convert')):
        # 先尝试获取 color_space 属性来了解可用的色彩空间
        if hasattr(color_obj, 'color_space'):
            try:
                cs = color_obj.color_space
                print(f"[FillPropertyCopier]     → .color_space = {cs!r}")
            except Exception as e:
                print(f"[FillPropertyCopier]     → .color_space 异常: {e}")

        # 尝试传不同参数给 convert
        for space_name in ('sRGB', 'srgb', 'linear', 'scene_linear', 'display'):
            try:
                converted = color_obj.convert(space_name)
                print(f"[FillPropertyCopier]     → .convert({space_name!r}) = {converted!r}")
                extracted = _extract_color_from_value(converted)
                if extracted is not None:
                    return extracted
                # 如果 convert 返回的也是 Color 对象，取 value
                if hasattr(converted, 'value'):
                    inner = converted.value
                    if callable(inner):
                        inner = inner()
                    extracted = _extract_color_from_value(inner)
                    if extracted is not None:
                        print(f"[FillPropertyCopier]     → .convert().value 提取成功: {extracted}")
                        return extracted
            except Exception as e:
                print(f"[FillPropertyCopier]     → .convert({space_name!r}) 异常: {e}")

    # ---- 6. 直接 r/g/b 属性 ----
    if hasattr(color_obj, 'r') and hasattr(color_obj, 'g') and hasattr(color_obj, 'b'):
        try:
            r_val = color_obj.r
            g_val = color_obj.g
            b_val = color_obj.b
            if not callable(r_val):
                a_val = color_obj.a if (hasattr(color_obj, 'a') and not callable(getattr(color_obj, 'a', None))) else 1.0
                result = (float(r_val), float(g_val), float(b_val), float(a_val))
                print(f"[FillPropertyCopier]     → .r/.g/.b 属性: {result}")
                return result
        except Exception as e:
            print(f"[FillPropertyCopier]     → .r/.g/.b 异常: {e}")

    # ---- 7. 索引访问 [0][1][2] ----
    try:
        r_val = color_obj[0]
        g_val = color_obj[1]
        b_val = color_obj[2]
        a_val = color_obj[3] if len(color_obj) >= 4 else 1.0
        result = (float(r_val), float(g_val), float(b_val), float(a_val))
        print(f"[FillPropertyCopier]     → 索引访问: {result}")
        return result
    except (TypeError, IndexError, KeyError) as e:
        print(f"[FillPropertyCopier]     → 索引访问不支持: {e}")

    # ---- 8. 可迭代 ----
    try:
        vals = list(color_obj)
        print(f"[FillPropertyCopier]     → list(color_obj) = {vals}")
        if len(vals) >= 3:
            a = float(vals[3]) if len(vals) >= 4 else 1.0
            return (float(vals[0]), float(vals[1]), float(vals[2]), a)
    except (TypeError, ValueError) as e:
        print(f"[FillPropertyCopier]     → list() 不支持: {e}")

    # ---- 9. 尝试 red/green/blue 属性 ----
    if hasattr(color_obj, 'red') and hasattr(color_obj, 'green') and hasattr(color_obj, 'blue'):
        try:
            r_val = color_obj.red
            g_val = color_obj.green
            b_val = color_obj.blue
            if not callable(r_val):
                a_val = color_obj.alpha if hasattr(color_obj, 'alpha') else 1.0
                result = (float(r_val), float(g_val), float(b_val), float(a_val))
                print(f"[FillPropertyCopier]     → .red/.green/.blue 属性: {result}")
                return result
        except Exception as e:
            print(f"[FillPropertyCopier]     → .red/.green/.blue 异常: {e}")

    # ---- 10. 数值属性扫描 ----
    numeric_vals = []
    for attr in attrs:
        try:
            v = getattr(color_obj, attr)
            if not callable(v) and isinstance(v, (int, float)):
                numeric_vals.append((attr, float(v)))
        except Exception:
            pass
    if len(numeric_vals) >= 3:
        print(f"[FillPropertyCopier]     → 数值属性: {numeric_vals}")
        vals = [nv[1] for nv in numeric_vals]
        a = vals[3] if len(vals) >= 4 else 1.0
        return (vals[0], vals[1], vals[2], a)

    # 注意：不再使用 str() 解析，因为内存地址会被误解析为颜色值
    print(f"[FillPropertyCopier]     → 无法从 Color 对象提取颜色值")
    return None


def _try_read_color_from_source(source) -> Optional[Tuple[float, float, float, float]]:
    """从 source 对象中尝试提取颜色值（先方法后属性）。"""
    if source is None:
        return None

    src_type = type(source).__name__
    print(f"[FillPropertyCopier]   source 类型: {src_type}")

    # ── 优先：调用 get_color() 等方法（SP 实际 API 使用此方式）──
    for method_name in ('get_color', 'get_value', 'get_uniform_color'):
        if hasattr(source, method_name) and callable(getattr(source, method_name)):
            try:
                val = getattr(source, method_name)()
                print(f"[FillPropertyCopier]   {method_name}() = {val!r} (type={type(val).__name__})")

                # 先尝试标准提取
                color = _extract_color_from_value(val)
                if color is not None:
                    return color

                # 如果标准提取失败，可能是 Color 管理对象，深度探测
                color = _extract_from_color_object(val)
                if color is not None:
                    return color
            except Exception as e:
                print(f"[FillPropertyCopier]   {method_name}() 异常: {e}")

    # ── 备选：读取属性 ──
    for color_attr in ('color', 'uniform_color', 'value',
                       'color_value', 'uniform_value'):
        if hasattr(source, color_attr):
            try:
                val = getattr(source, color_attr)
                # 跳过 callable（方法已在上面尝试过）
                if callable(val):
                    continue
                print(f"[FillPropertyCopier]   source.{color_attr} = {val!r}")
                color = _extract_color_from_value(val)
                if color is not None:
                    return color
                color = _extract_from_color_object(val)
                if color is not None:
                    return color
            except Exception as e:
                print(f"[FillPropertyCopier]   source.{color_attr} 异常: {e}")

    return None


def _try_read_via_get_source(layer, ch_type) -> Optional[Tuple[float, float, float, float]]:
    """策略1: 通过 get_source(channel) 读取颜色。"""
    if not hasattr(layer, 'get_source'):
        return None

    # 先尝试带通道参数的 get_source(ch_type)
    if ch_type is not None:
        try:
            source = layer.get_source(ch_type)
            print(f"[FillPropertyCopier] get_source({ch_type!r}) = {source!r}")
            color = _try_read_color_from_source(source)
            if color is not None:
                return color
        except Exception as e:
            print(f"[FillPropertyCopier] get_source(ch_type) 失败: {e}")

    # 再尝试不带参数的 get_source()
    try:
        source = layer.get_source()
        print(f"[FillPropertyCopier] get_source() = {source!r}")
        color = _try_read_color_from_source(source)
        if color is not None:
            return color
    except Exception as e:
        print(f"[FillPropertyCopier] get_source() 失败: {e}")

    return None


def _try_read_via_property_value(layer, channel_name: str) -> Optional[Tuple[float, float, float, float]]:
    """策略2: 通过 get_property_value 读取颜色。"""
    if not hasattr(layer, 'get_property_value'):
        return None

    # 尝试多种属性名
    prop_names = [
        channel_name.lower(),
        channel_name,
        f"{channel_name.lower()}_color",
        "basecolor", "base_color", "color",
        "diffuse", "albedo",
    ]
    for pname in prop_names:
        try:
            val = layer.get_property_value(pname)
            color = _extract_color_from_value(val)
            if color is not None:
                return color
        except Exception:
            pass

    return None


def _try_read_via_channel_color(layer, ch_type) -> Optional[Tuple[float, float, float, float]]:
    """策略3: 通过 get_channel_color 读取颜色。"""
    if not hasattr(layer, 'get_channel_color'):
        return None

    try:
        if ch_type is not None:
            val = layer.get_channel_color(ch_type)
        else:
            val = layer.get_channel_color()
        color = _extract_color_from_value(val)
        if color is not None:
            return color
    except Exception:
        pass

    return None


def _try_read_via_uniform_color(layer, ch_type) -> Optional[Tuple[float, float, float, float]]:
    """策略4: 通过 get_uniform_color 读取颜色。"""
    if not hasattr(layer, 'get_uniform_color'):
        return None

    try:
        if ch_type is not None:
            val = layer.get_uniform_color(ch_type)
        else:
            val = layer.get_uniform_color()
        color = _extract_color_from_value(val)
        if color is not None:
            return color
    except Exception:
        pass

    return None


def _try_read_via_active_channels(layer, channel_name: str) -> Optional[Tuple[float, float, float, float]]:
    """策略5: 遍历 active_channels 尝试匹配通道并读取颜色。"""
    if not hasattr(layer, 'active_channels'):
        return None

    try:
        channels = layer.active_channels
        for ch in channels:
            ch_str = str(ch).lower()
            if channel_name.lower() in ch_str or "base" in ch_str or "color" in ch_str:
                if hasattr(layer, 'get_source'):
                    try:
                        source = layer.get_source(ch)
                        color = _try_read_color_from_source(source)
                        if color is not None:
                            return color
                    except Exception:
                        pass
    except Exception:
        pass

    return None


# ============================================================
# BaseColor - 应用纯色颜色值
# ============================================================

def apply_basecolor(layer, color_data: BaseColorData,
                    channel_name: str = "BaseColor") -> ApplyResult:
    """
    将 BaseColor 纯色颜色值应用到指定填充图层。

    Args:
        layer: 目标节点对象
        color_data: BaseColorData 颜色数据
        channel_name: 目标通道名称

    Returns:
        ApplyResult 对象
    """
    result = ApplyResult()
    result.layer_name = layer.get_name()

    if not color_data.valid:
        result.errors.append("颜色数据无效")
        return result

    ch_type = _get_channel_type_by_name(channel_name)
    if ch_type is None:
        ch_type = _get_basecolor_channel_type()

    color_tuple = color_data.to_rgba_tuple()
    color_rgb = color_data.to_rgb_tuple()

    # 策略1: set_source / source.color
    ok = _try_apply_via_set_source(layer, ch_type, color_tuple, color_rgb)
    if ok:
        result.applied.append(f"{channel_name} 颜色")
        result.success = True
        print(f"[FillPropertyCopier] 已通过 set_source 应用颜色到 {result.layer_name}")
        return result

    # 策略2: set_property_value
    ok = _try_apply_via_property_value(layer, channel_name, color_tuple, color_rgb)
    if ok:
        result.applied.append(f"{channel_name} 颜色")
        result.success = True
        print(f"[FillPropertyCopier] 已通过 set_property_value 应用颜色到 {result.layer_name}")
        return result

    # 策略3: set_channel_color
    ok = _try_apply_via_channel_color(layer, ch_type, color_tuple, color_rgb)
    if ok:
        result.applied.append(f"{channel_name} 颜色")
        result.success = True
        print(f"[FillPropertyCopier] 已通过 set_channel_color 应用颜色到 {result.layer_name}")
        return result

    # 策略4: set_uniform_color
    ok = _try_apply_via_uniform_color(layer, ch_type, color_tuple, color_rgb)
    if ok:
        result.applied.append(f"{channel_name} 颜色")
        result.success = True
        print(f"[FillPropertyCopier] 已通过 set_uniform_color 应用颜色到 {result.layer_name}")
        return result

    result.errors.append(f"无法应用 {channel_name} 颜色（所有 API 策略均失败）")
    return result


def _try_apply_color_to_source(source, color_rgba, color_rgb) -> bool:
    """向 source 对象写入颜色（先方法后属性）。"""
    if source is None:
        return False

    src_type = type(source).__name__
    print(f"[FillPropertyCopier]   应用目标 source 类型: {src_type}")

    # 准备多种颜色格式候选值
    color_candidates = [color_rgba, color_rgb,
                        list(color_rgba), list(color_rgb)]

    # 尝试构建 colormanagement.Color 对象（如果可用）
    # 已知 Color 对象有 sRGB / working / value / value_raw 等属性
    try:
        import substance_painter.colormanagement as sp_cm
        if hasattr(sp_cm, 'Color'):
            # 尝试多种构造方式
            constructor_attempts = [
                # 传入 RGB float 元组
                (color_rgb,),
                # 传入 RGBA float 元组
                (color_rgba,),
                # 传入 list
                (list(color_rgb),),
                (list(color_rgba),),
                # 传入 3 个分开的 float
                (color_rgb[0], color_rgb[1], color_rgb[2]),
                # 传入 4 个分开的 float
                (color_rgba[0], color_rgba[1], color_rgba[2], color_rgba[3]),
            ]
            for args in constructor_attempts:
                try:
                    cm_color = sp_cm.Color(*args)
                    color_candidates.insert(0, cm_color)  # 优先尝试
                    print(f"[FillPropertyCopier]   构建 Color 对象成功: {cm_color!r}")
                    # 如果 Color 有 sRGB 属性, 也尝试
                    if hasattr(cm_color, 'sRGB'):
                        try:
                            srgb_color = cm_color.sRGB
                            if callable(srgb_color):
                                srgb_color = srgb_color()
                            print(f"[FillPropertyCopier]   Color.sRGB = {srgb_color!r}")
                        except Exception:
                            pass
                    break
                except Exception as e:
                    print(f"[FillPropertyCopier]   构建 Color({args}) 失败: {e}")
    except ImportError:
        pass

    # ── 优先：调用 set_color() 等方法 ──
    for method_name in ('set_color', 'set_value', 'set_uniform_color'):
        if hasattr(source, method_name) and callable(getattr(source, method_name)):
            for val in color_candidates:
                try:
                    getattr(source, method_name)(val)
                    print(f"[FillPropertyCopier]   {method_name}({val!r}) 成功")
                    return True
                except Exception as e:
                    print(f"[FillPropertyCopier]   {method_name}({type(val).__name__}) 失败: {e}")

    # ── 备选：设置属性 ──
    for color_attr in ('color', 'uniform_color', 'value', 'color_value'):
        if hasattr(source, color_attr):
            try:
                old_val = getattr(source, color_attr)
                # 跳过 callable（方法已在上面尝试过）
                if callable(old_val):
                    continue
                # 尝试用与原值相同格式的数据设置
                if isinstance(old_val, (list, tuple)):
                    if len(old_val) >= 4:
                        setattr(source, color_attr, list(color_rgba))
                    else:
                        setattr(source, color_attr, list(color_rgb))
                elif hasattr(old_val, 'r'):
                    old_val.r = color_rgba[0]
                    old_val.g = color_rgba[1]
                    old_val.b = color_rgba[2]
                    if hasattr(old_val, 'a'):
                        old_val.a = color_rgba[3]
                    setattr(source, color_attr, old_val)
                else:
                    setattr(source, color_attr, list(color_rgba))
                print(f"[FillPropertyCopier]   设置 source.{color_attr} 成功")
                return True
            except Exception as e:
                print(f"[FillPropertyCopier]   设置 source.{color_attr} 失败: {e}")

    return False


def _try_apply_via_set_source(layer, ch_type, color_rgba, color_rgb) -> bool:
    """策略1: 通过 get_source → 修改 source 颜色 → (可能需要 set_source)。"""
    if not hasattr(layer, 'get_source'):
        return False

    # 先尝试带通道参数
    source = None
    if ch_type is not None:
        try:
            source = layer.get_source(ch_type)
            print(f"[FillPropertyCopier] apply: get_source({ch_type!r}) = {source!r}")
        except Exception as e:
            print(f"[FillPropertyCopier] apply: get_source(ch_type) 失败: {e}")

    # 再尝试不带参数
    if source is None:
        try:
            source = layer.get_source()
            print(f"[FillPropertyCopier] apply: get_source() = {source!r}")
        except Exception:
            return False

    if source is None:
        return False

    ok = _try_apply_color_to_source(source, color_rgba, color_rgb)
    if not ok:
        return False

    # 某些 API 可能需要显式写回 source
    if hasattr(layer, 'set_source'):
        try:
            if ch_type is not None:
                layer.set_source(ch_type, source)
            else:
                layer.set_source(source)
            print("[FillPropertyCopier]   set_source 写回成功")
        except Exception as e:
            # 不一定需要写回，忽略即可
            print(f"[FillPropertyCopier]   set_source 写回跳过: {e}")

    return True


def _try_apply_via_property_value(layer, channel_name: str, color_rgba, color_rgb) -> bool:
    """策略2: 通过 set_property_value 设置颜色。"""
    if not hasattr(layer, 'set_property_value'):
        return False

    prop_names = [
        channel_name.lower(),
        channel_name,
        f"{channel_name.lower()}_color",
        "basecolor", "base_color", "color",
    ]
    for pname in prop_names:
        for val in (list(color_rgba), list(color_rgb)):
            try:
                layer.set_property_value(pname, val)
                return True
            except Exception:
                pass

    return False


def _try_apply_via_channel_color(layer, ch_type, color_rgba, color_rgb) -> bool:
    """策略3: 通过 set_channel_color 设置颜色。"""
    if not hasattr(layer, 'set_channel_color'):
        return False

    for val in (color_rgba, color_rgb, list(color_rgba), list(color_rgb)):
        try:
            if ch_type is not None:
                layer.set_channel_color(ch_type, val)
            else:
                layer.set_channel_color(val)
            return True
        except Exception:
            pass

    return False


def _try_apply_via_uniform_color(layer, ch_type, color_rgba, color_rgb) -> bool:
    """策略4: 通过 set_uniform_color 设置颜色。"""
    if not hasattr(layer, 'set_uniform_color'):
        return False

    for val in (color_rgba, color_rgb, list(color_rgba), list(color_rgb)):
        try:
            if ch_type is not None:
                layer.set_uniform_color(ch_type, val)
            else:
                layer.set_uniform_color(val)
            return True
        except Exception:
            pass

    return False


# ============================================================
# BaseColor - 批量应用到选中图层
# ============================================================

def apply_basecolor_to_selected(color_data: BaseColorData,
                                channel_name: str = "BaseColor") -> List[ApplyResult]:
    """
    将 BaseColor 颜色应用到所有选中的图层节点。

    Returns:
        ApplyResult 列表
    """
    results = []
    selected = get_selected_nodes()

    if not selected:
        print("[FillPropertyCopier] 没有选中的图层")
        return results

    try:
        with sp_layerstack.ScopedModification("BaseColor 颜色应用"):
            for node in selected:
                r = apply_basecolor(node, color_data, channel_name)
                results.append(r)
    except Exception as e:
        print(f"[FillPropertyCopier] 批量应用 BaseColor 失败: {e}")
        import traceback
        traceback.print_exc()

    return results
