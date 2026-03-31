bl_info = {
    "name": "Modifier Sync v2 (修改器同步)",
    "author": "123木头人",
    "version": (6, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > 修改器同步",
    "description": "以修改器为核心的同步工具：每个同步组对应一个修改器，添加模型自动补齐修改器，并且可以选择控制参数",
    "category": "Object",
}

import bpy
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
    PointerProperty,
    EnumProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList

# ============================================================
#  全局状态
# ============================================================

_is_syncing = False


def _tag_redraw_sidebar():
    """强制刷新所有 3D 视图的侧边栏区域，确保 UI 立即更新。
    解决 Blender N 面板只在鼠标悬停时才重绘的问题。
    """
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()
                    elif region.type == 'WINDOW':
                        region.tag_redraw()
_modifier_snapshots = {}
_enum_items_cache = []  # 缓存 EnumProperty items，防止 Blender 乱码
_enum_pick_obj_cache = []  # 吸取功能：模型下拉缓存
_enum_pick_mod_cache = []  # 吸取功能：修改器下拉缓存
_enum_collection_cache = []  # 按集合添加：集合下拉缓存

# ---- 同步日志 ----
import time as _time

_MAX_SYNC_LOG = 20  # 最多保留的同步日志条数

class _SyncLogEntry:
    __slots__ = ('timestamp', 'source_name', 'group_name', 'target_count')
    def __init__(self, source_name, group_name, target_count):
        self.timestamp = _time.time()
        self.source_name = source_name
        self.group_name = group_name
        self.target_count = target_count

_sync_log = []  # list[_SyncLogEntry]


class MODSYNC_SyncLogItem(PropertyGroup):
    """同步日志条目（用于 UIList 显示）"""
    text: StringProperty(name="日志内容", default="")


# ============================================================
#  数据结构 (PropertyGroup)
# ============================================================

class MODSYNC_ObjectToggle(PropertyGroup):
    """同步组内一个模型的引用 + 参与同步开关"""
    obj: PointerProperty(name="Object", type=bpy.types.Object)
    enabled: BoolProperty(name="参与同步", default=True)


class MODSYNC_SyncGroup(PropertyGroup):
    """一个同步组 = 一个修改器
    组的名称就是修改器名称，mod_type 记录修改器类型。
    """
    name: StringProperty(name="Group Name", default="")
    mod_type: StringProperty(name="Modifier Type", default="")
    enabled: BoolProperty(name="同步启用", default=True)
    objects: CollectionProperty(type=MODSYNC_ObjectToggle)
    active_object_index: IntProperty(name="Active Object Index", default=0)
    expanded: BoolProperty(name="Expanded", default=False)
    params_expanded: BoolProperty(name="参数面板展开", default=True)
    source_obj: PointerProperty(
        name="锁定同步源",
        type=bpy.types.Object,
        description="指定唯一同步源模型，设置后只有该模型的修改器变化才会触发同步",
    )
    source_locked: BoolProperty(
        name="锁定同步源",
        default=False,
        description="是否锁定同步源（启用后只从指定源模型同步）",
    )
    excluded_props: StringProperty(
        name="排除属性",
        default="",
        description="不参与同步的属性列表（逗号分隔）",
    )


class MODSYNC_SceneProperties(PropertyGroup):
    """场景级别的插件属性"""
    sync_groups: CollectionProperty(type=MODSYNC_SyncGroup)
    active_group_index: IntProperty(name="Active Group Index", default=0)
    global_enabled: BoolProperty(
        name="Global Enable",
        default=False,
        description="全局启用/禁用修改器同步",
        update=lambda self, ctx: _on_global_toggle(self, ctx),
    )
    debug_mode: BoolProperty(
        name="调试模式",
        default=False,
        description="启用后在系统控制台输出详细的同步日志",
    )
    sync_log_expanded: BoolProperty(
        name="展开同步日志",
        default=False,
        description="展开/折叠同步日志面板",
    )
    sync_log_items: CollectionProperty(type=MODSYNC_SyncLogItem)
    sync_log_active_index: IntProperty(name="Active Log Index", default=0)


# ============================================================
#  辅助函数
# ============================================================

def _get_modifier_snapshot(obj):
    """获取一个模型所有修改器的参数快照。
    支持普通修改器属性 + Geometry Nodes 修改器的节点输入参数。
    """
    snapshot = {}
    if obj is None or obj.type != 'MESH':
        return snapshot
    for mod in obj.modifiers:
        props = {}
        # ---- 1) 标准属性 ----
        for prop in mod.bl_rna.properties:
            if prop.identifier == 'rna_type' or prop.is_readonly:
                continue
            try:
                val = getattr(mod, prop.identifier)
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    val = tuple(val)
                props[prop.identifier] = val
            except Exception:
                continue

        # ---- 2) Geometry Nodes 输入参数（Auto Smooth 等） ----
        if mod.type == 'NODES' and getattr(mod, 'node_group', None) is not None:
            gn_inputs = {}
            try:
                if hasattr(mod.node_group, 'interface'):
                    for item in mod.node_group.interface.items_tree:
                        if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                            sock_id = item.identifier
                            try:
                                val = mod[sock_id]
                                if hasattr(val, '__iter__') and not isinstance(val, str):
                                    val = tuple(val)
                                gn_inputs[sock_id] = val
                            except (KeyError, TypeError):
                                continue
                elif hasattr(mod.node_group, 'inputs'):
                    for inp in mod.node_group.inputs:
                        sock_id = inp.identifier
                        try:
                            val = mod[sock_id]
                            if hasattr(val, '__iter__') and not isinstance(val, str):
                                val = tuple(val)
                            gn_inputs[sock_id] = val
                        except (KeyError, TypeError):
                            continue
            except Exception:
                pass
            if gn_inputs:
                props['__gn_inputs__'] = gn_inputs

        props['__type__'] = mod.type
        snapshot[mod.name] = props
    return snapshot


def _apply_modifier_props(target_mod, source_props, excluded=None):
    """将源修改器的属性值应用到目标修改器上。
    支持普通属性 + Geometry Nodes 输入参数。
    excluded: 排除的属性集合（set of str），不为 None 时跳过这些属性。
    """
    excluded = excluded or set()

    # ---- 先保存目标模型上被排除属性的原始值 ----
    # （因为设置其他属性时 Blender 内部可能联动覆盖被排除的属性）
    excluded_backup = {}
    if excluded:
        for ex_key in excluded:
            try:
                val = getattr(target_mod, ex_key, None)
                if val is not None:
                    if hasattr(val, '__iter__') and not isinstance(val, str):
                        val = tuple(val)
                    excluded_backup[ex_key] = val
            except Exception:
                pass
        # 也做大小写不敏感的备份
        for key in source_props:
            if key.startswith('__'):
                continue
            if key not in excluded and any(key.lower() == ex.lower() for ex in excluded):
                try:
                    val = getattr(target_mod, key, None)
                    if val is not None:
                        if hasattr(val, '__iter__') and not isinstance(val, str):
                            val = tuple(val)
                        excluded_backup[key] = val
                except Exception:
                    pass

    # ---- 应用非排除属性 ----
    for key, value in source_props.items():
        if key.startswith('__'):
            continue
        if key in excluded:
            continue
        if any(key.lower() == ex.lower() for ex in excluded):
            continue
        try:
            current = getattr(target_mod, key, None)
            if current is not None and hasattr(current, '__iter__') and not isinstance(current, str):
                try:
                    for i, v in enumerate(value):
                        current[i] = v
                except Exception:
                    setattr(target_mod, key, value)
            else:
                setattr(target_mod, key, value)
        except (AttributeError, TypeError, KeyError):
            continue

    # ---- 恢复被排除属性的原始值 ----
    # Blender 内部属性联动可能在设置其他属性时改变了被排除的属性，
    # 例如设置 offset_type 可能重置 width，这里强制恢复。
    for ex_key, ex_val in excluded_backup.items():
        try:
            current = getattr(target_mod, ex_key, None)
            if current is not None and hasattr(current, '__iter__') and not isinstance(current, str):
                try:
                    for i, v in enumerate(ex_val):
                        current[i] = v
                except Exception:
                    setattr(target_mod, ex_key, ex_val)
            else:
                setattr(target_mod, ex_key, ex_val)
        except (AttributeError, TypeError, KeyError):
            continue

    # ---- 应用 Geometry Nodes 输入参数 ----
    gn_inputs = source_props.get('__gn_inputs__')
    if gn_inputs and target_mod.type == 'NODES':
        for sock_id, value in gn_inputs.items():
            try:
                current = target_mod[sock_id]
                if hasattr(current, '__iter__') and not isinstance(current, str):
                    try:
                        for i, v in enumerate(value):
                            current[i] = v
                    except Exception:
                        target_mod[sock_id] = value
                else:
                    target_mod[sock_id] = value
            except (KeyError, TypeError):
                continue


def _refresh_log_ui_items():
    """将 _sync_log 同步到场景属性的 CollectionProperty（供 UIList 使用）"""
    import datetime as _dt
    scene = getattr(bpy.context, 'scene', None)
    if scene is None:
        return
    props = getattr(scene, 'modifier_sync_v2', None)
    if props is None:
        return
    items = props.sync_log_items
    items.clear()
    for entry in reversed(_sync_log):
        item = items.add()
        ts = _dt.datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        item.text = f"[{ts}] {entry.source_name} → {entry.group_name} ×{entry.target_count}"
    # 确保 active_index 有效
    if props.sync_log_active_index >= len(items):
        props.sync_log_active_index = max(0, len(items) - 1)


def _find_changed_modifiers(obj):
    """对比快照，找到发生变化的修改器（不更新快照，由调用方统一更新）"""
    global _modifier_snapshots
    obj_name = obj.name
    current_snapshot = _get_modifier_snapshot(obj)
    old_snapshot = _modifier_snapshots.get(obj_name, {})
    changed = {}
    for mod_name, current_props in current_snapshot.items():
        old_props = old_snapshot.get(mod_name, {})
        if current_props != old_props:
            changed[mod_name] = current_props
    # 注意：不在此处更新快照，由 _sync_timer 在同步完成后统一刷新
    return changed


def _get_obj_modifier(obj, mod_name, mod_type):
    """获取模型上指定名称和类型的修改器，若不存在返回 None"""
    if obj is None:
        return None
    mod = obj.modifiers.get(mod_name)
    if mod is not None and mod.type == mod_type:
        return mod
    return None


def _is_object_valid(obj):
    """检查一个物体引用是否仍然有效（存在于当前场景中且未被删除）"""
    if obj is None:
        return False
    try:
        _ = obj.name
    except ReferenceError:
        return False
    # 必须仍在 bpy.data.objects 中
    if obj.name not in bpy.data.objects:
        return False
    # 同名但不是同一个对象（删除后新建同名物体的情况）
    if bpy.data.objects.get(obj.name) is not obj:
        return False
    # 关键：必须仍在当前场景的物体集合中
    # Blender 删除物体后，物体仍留在 bpy.data.objects 但已不在 scene.objects
    scene = getattr(bpy.context, 'scene', None)
    if scene is not None and obj.name not in scene.objects:
        return False
    return True


def _clean_invalid_references(context):
    """清理所有同步组中已失效的模型引用"""
    props = context.scene.modifier_sync_v2
    for group in props.sync_groups:
        to_remove = [i for i, item in enumerate(group.objects)
                     if not _is_object_valid(item.obj)]
        for i in reversed(to_remove):
            group.objects.remove(i)


def _refresh_all_snapshots(context):
    """刷新所有同步组内模型的快照"""
    global _modifier_snapshots
    props = context.scene.modifier_sync_v2
    for group in props.sync_groups:
        for item in group.objects:
            obj = item.obj
            if obj is not None and obj.name in bpy.data.objects:
                _modifier_snapshots[obj.name] = _get_modifier_snapshot(obj)


def _sort_group_objects(group):
    """对同步组内的模型进行物理排序（通过 CollectionProperty.move）。
    排序规则：
      0) 失效模型（obj=None）置顶
      1) 无修改器的模型置顶
      2) 同步已禁用的模型次之
      3) 正常模型按名称排序
    """
    n = len(group.objects)
    if n <= 1:
        return

    mod_name = group.name
    mod_type = group.mod_type

    def _sort_key(toggle):
        obj = toggle.obj
        if obj is None or obj.name not in bpy.data.objects:
            return (0, "")
        mod = _get_obj_modifier(obj, mod_name, mod_type)
        if mod is None:
            return (1, obj.name.lower())
        if not toggle.enabled:
            return (2, obj.name.lower())
        return (3, obj.name.lower())

    # 计算期望排序的索引映射
    # 通过冒泡排序配合 CollectionProperty.move 实现物理重排
    for i in range(n):
        for j in range(n - 1 - i):
            key_j = _sort_key(group.objects[j])
            key_j1 = _sort_key(group.objects[j + 1])
            if key_j > key_j1:
                group.objects.move(j, j + 1)

    # 重置选中索引
    group.active_object_index = min(group.active_object_index, max(0, n - 1))


def _get_representative_modifier(group):
    """获取参数面板的数据源修改器。
    - 锁定同步源时：固定展示锁定源的修改器。
    - 未锁定时：优先展示当前活动物体的修改器（前提是它在组内），
      否则回退到第一个有效物体。
    """
    # 优先使用锁定的同步源
    if group.source_locked and group.source_obj is not None:
        obj = group.source_obj
        if obj.name in bpy.data.objects:
            mod = _get_obj_modifier(obj, group.name, group.mod_type)
            if mod is not None:
                return obj, mod

    # 未锁定：优先使用活动物体
    active_obj = getattr(bpy.context, 'active_object', None)
    if active_obj is not None and active_obj.name in bpy.data.objects:
        # 检查活动物体是否在组内且已启用
        in_group = any(
            t.obj == active_obj and t.enabled
            for t in group.objects if t.obj is not None
        )
        if in_group:
            mod = _get_obj_modifier(active_obj, group.name, group.mod_type)
            if mod is not None:
                return active_obj, mod

    # 回退：第一个有效物体
    for toggle in group.objects:
        obj = toggle.obj
        if obj is None or obj.name not in bpy.data.objects:
            continue
        mod = _get_obj_modifier(obj, group.name, group.mod_type)
        if mod is not None:
            return obj, mod
    return None, None


# ---- 需要在参数面板中跳过的属性 ----
_SKIP_PROPS = {
    'rna_type', 'name', 'type', 'show_viewport', 'show_render',
    'show_in_editmode', 'show_on_cage', 'show_expanded',
    'is_active', 'is_override_data',
    'use_apply_on_spline', 'execution_time',
}


# ============================================================
#  常见修改器的原生排版绘制函数
#  参考 Blender 内置 properties_data_modifier.py，适配 3.x/4.x
# ============================================================

def _split(layout, factor=0.5):
    """兼容 Blender 3.x/4.x 的 split 调用"""
    try:
        return layout.split(factor=factor)
    except TypeError:
        return layout.split(percentage=factor)


def _safe_prop(layout, data, prop_name, **kwargs):
    """安全绘制属性，属性不存在时跳过（兼容不同 Blender 版本）"""
    if hasattr(data, prop_name):
        try:
            layout.prop(data, prop_name, **kwargs)
            return True
        except (TypeError, AttributeError):
            pass
    return False


def _safe_prop_search(layout, data, prop_name, search_data, search_prop, **kwargs):
    """安全绘制搜索属性"""
    if hasattr(data, prop_name):
        try:
            layout.prop_search(data, prop_name, search_data, search_prop, **kwargs)
            return True
        except (TypeError, AttributeError):
            pass
    return False


# ---- Mirror ----
def _draw_MIRROR(layout, ob, md):
    # 轴向 / 切分 / 翻转
    # Blender 4.x 使用 use_axis[0..2] / use_bisect_axis[0..2] / use_bisect_flip_axis[0..2]
    # Blender 3.x 使用 use_x / use_y / use_z 等
    has_new_api = hasattr(md, 'use_axis')

    if has_new_api:
        # ---- Blender 4.x 排版 ----
        col = layout.column(align=False)

        # 轴向 / 切分 / 翻转 三行紧凑排列
        header = col.row(align=True)
        header.label(text="")
        header.label(text="X")
        header.label(text="Y")
        header.label(text="Z")

        row = col.row(align=True)
        row.label(text="轴向")
        row.prop(md, "use_axis", index=0, text=" ")
        row.prop(md, "use_axis", index=1, text=" ")
        row.prop(md, "use_axis", index=2, text=" ")

        row = col.row(align=True)
        row.label(text="切分")
        row.prop(md, "use_bisect_axis", index=0, text=" ")
        row.prop(md, "use_bisect_axis", index=1, text=" ")
        row.prop(md, "use_bisect_axis", index=2, text=" ")

        row = col.row(align=True)
        row.label(text="翻转")
        row.prop(md, "use_bisect_flip_axis", index=0, text=" ")
        row.prop(md, "use_bisect_flip_axis", index=1, text=" ")
        row.prop(md, "use_bisect_flip_axis", index=2, text=" ")

        layout.separator()
        _safe_prop(layout, md, "mirror_object", text="镜像物体")

        layout.separator()
        _safe_prop(layout, md, "use_clip", text="范围限制")
        _safe_prop(layout, md, "use_mirror_merge", text="合并")
        if getattr(md, 'use_mirror_merge', False):
            _safe_prop(layout, md, "merge_threshold", text="合并距离")

        layout.separator()
        col = layout.column(align=False)
        _safe_prop(col, md, "use_mirror_vertex_groups", text="镜像顶点组")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="数据:")
        row = col.row(align=True)
        _safe_prop(row, md, "use_mirror_u", text="翻转 U")
        _safe_prop(row, md, "use_mirror_v", text="翻转 V")
        _safe_prop(col, md, "use_mirror_udim", text="翻转 UDIM")
        row = col.row(align=True)
        _safe_prop(row, md, "offset_u", text="U 偏移")
        _safe_prop(row, md, "offset_v", text="V 偏移")

    else:
        # ---- Blender 3.x 排版 ----
        split = _split(layout, factor=0.25)

        col = split.column()
        col.label(text="轴向:")
        col.prop(md, "use_x", text="X")
        col.prop(md, "use_y", text="Y")
        col.prop(md, "use_z", text="Z")

        col = split.column()
        col.label(text="选项:")
        _safe_prop(col, md, "use_mirror_merge", text="合并")
        _safe_prop(col, md, "use_clip", text="范围限制")
        _safe_prop(col, md, "use_mirror_vertex_groups", text="镜像顶点组")

        col = split.column()
        col.label(text="纹理:")
        _safe_prop(col, md, "use_mirror_u", text="U")
        _safe_prop(col, md, "use_mirror_v", text="V")

        col = layout.column()
        if getattr(md, 'use_mirror_merge', False):
            col.prop(md, "merge_threshold", text="合并距离")
        col.prop(md, "mirror_object", text="镜像物体")


# ---- Subdivision Surface ----
def _draw_SUBSURF(layout, ob, md):
    layout.row().prop(md, "subdivision_type", expand=True)

    split = _split(layout)
    col = split.column()
    col.label(text="细分级别:")
    col.prop(md, "levels", text="视口")
    col.prop(md, "render_levels", text="渲染")

    col = split.column()
    col.label(text="高级:")
    _safe_prop(col, md, "quality")
    _safe_prop(col, md, "uv_smooth")
    _safe_prop(col, md, "boundary_smooth")
    _safe_prop(col, md, "use_creases")
    _safe_prop(col, md, "use_custom_normals")


# ---- Array ----
def _draw_ARRAY(layout, ob, md):
    layout.prop(md, "fit_type", text="适配类型")

    if md.fit_type == 'FIXED_COUNT':
        layout.prop(md, "count", text="数量")
    elif md.fit_type == 'FIT_LENGTH':
        layout.prop(md, "fit_length", text="长度")
    elif md.fit_type == 'FIT_CURVE':
        layout.prop(md, "curve", text="曲线")

    layout.separator()

    split = _split(layout)

    col = split.column()
    col.prop(md, "use_constant_offset", text="恒定偏移")
    sub = col.column()
    sub.active = md.use_constant_offset
    sub.prop(md, "constant_offset_displace", text="")

    col.separator()
    col.prop(md, "use_merge_vertices", text="合并")
    sub = col.column()
    sub.active = md.use_merge_vertices
    _safe_prop(sub, md, "use_merge_vertices_cap", text="首尾")
    sub.prop(md, "merge_threshold", text="距离")

    col = split.column()
    col.prop(md, "use_relative_offset", text="相对偏移")
    sub = col.column()
    sub.active = md.use_relative_offset
    sub.prop(md, "relative_offset_displace", text="")

    col.separator()
    col.prop(md, "use_object_offset", text="物体偏移")
    sub = col.column()
    sub.active = md.use_object_offset
    sub.prop(md, "offset_object", text="")

    layout.separator()
    layout.prop(md, "start_cap", text="起始封盖")
    layout.prop(md, "end_cap", text="结束封盖")


# ---- Solidify ----
def _draw_SOLIDIFY(layout, ob, md):
    # Blender 4.x 有两种模式
    _safe_prop(layout.row(), md, "solidify_mode", expand=True)

    split = _split(layout)

    col = split.column()
    col.prop(md, "thickness", text="厚度")
    _safe_prop(col, md, "thickness_clamp", text="限制")

    col.separator()
    row = col.row(align=True)
    _safe_prop_search(row, md, "vertex_group", ob, "vertex_groups", text="")
    sub = row.row(align=True)
    sub.active = bool(md.vertex_group)
    _safe_prop(sub, md, "invert_vertex_group", text="", icon='ARROW_LEFTRIGHT')

    sub = col.row()
    sub.active = bool(md.vertex_group)
    _safe_prop(sub, md, "thickness_vertex_group", text="系数")

    col = split.column()
    col.prop(md, "offset", text="偏移")
    _safe_prop(col, md, "use_even_offset", text="等距")
    _safe_prop(col, md, "use_quality_normals", text="高质量法线")
    _safe_prop(col, md, "use_rim", text="填充边缘")
    sub = col.column()
    sub.active = getattr(md, 'use_rim', False)
    _safe_prop(sub, md, "use_rim_only", text="仅边缘")
    _safe_prop(col, md, "use_flip_normals", text="翻转法线")

    layout.separator()
    layout.label(text="材质偏移:")
    row = layout.row(align=True)
    _safe_prop(row, md, "material_offset", text="")
    sub = row.row(align=True)
    sub.active = getattr(md, 'use_rim', False)
    _safe_prop(sub, md, "material_offset_rim", text="边缘")


# ---- Bevel ----
def _draw_BEVEL(layout, ob, md):
    # 宽度类型 (Blender 4.x)
    _safe_prop(layout, md, "offset_type", text="类型")

    split = _split(layout)

    col = split.column()
    col.prop(md, "width", text="宽度")
    col.prop(md, "segments", text="段数")
    _safe_prop(col, md, "profile", text="形状")
    _safe_prop(col, md, "material", text="材质索引")

    col = split.column()
    _safe_prop(col, md, "affect", expand=True)
    _safe_prop(col, md, "use_clamp_overlap", text="限制重叠")
    _safe_prop(col, md, "loop_slide", text="环滑移")
    _safe_prop(col, md, "harden_normals", text="硬化法线")
    _safe_prop(col, md, "mark_seam", text="标记缝合边")
    _safe_prop(col, md, "mark_sharp", text="标记锐边")

    layout.separator()
    layout.label(text="限制方式:")
    _safe_prop(layout.row(), md, "limit_method", expand=True)
    if md.limit_method == 'ANGLE':
        layout.prop(md, "angle_limit", text="角度")
    elif md.limit_method == 'VGROUP':
        row = layout.row(align=True)
        _safe_prop_search(row, md, "vertex_group", ob, "vertex_groups", text="")
        _safe_prop(row, md, "invert_vertex_group", text="", icon='ARROW_LEFTRIGHT')

    # 自定义形状
    _safe_prop(layout, md, "profile_type")
    if getattr(md, 'profile_type', 'SUPERELLIPSE') == 'CUSTOM':
        _safe_prop(layout, md, "custom_profile")


# ---- Boolean ----
def _draw_BOOLEAN(layout, ob, md):
    _safe_prop(layout, md, "solver", expand=True)
    layout.separator()

    split = _split(layout)
    col = split.column()
    col.label(text="运算:")
    col.prop(md, "operation", text="")

    col = split.column()
    # Blender 4.x: operand_type 控制 object / collection
    if hasattr(md, 'operand_type'):
        col.label(text="操作对象:")
        col.prop(md, "operand_type", text="")
        if md.operand_type == 'OBJECT':
            col.prop(md, "object", text="")
        else:
            _safe_prop(col, md, "collection", text="")
    else:
        col.label(text="物体:")
        col.prop(md, "object", text="")

    # Solver 选项
    if getattr(md, 'solver', '') == 'EXACT':
        layout.separator()
        _safe_prop(layout, md, "use_self")
        _safe_prop(layout, md, "use_hole_tolerant")


# ---- Decimate ----
def _draw_DECIMATE(layout, ob, md):
    layout.row().prop(md, "decimate_type", expand=True)

    if md.decimate_type == 'COLLAPSE':
        layout.prop(md, "ratio", text="比率")
        row = layout.row(align=True)
        _safe_prop_search(row, md, "vertex_group", ob, "vertex_groups", text="")
        _safe_prop(row, md, "invert_vertex_group", text="", icon='ARROW_LEFTRIGHT')
        _safe_prop(layout, md, "use_collapse_triangulate", text="三角化")
        _safe_prop(layout, md, "use_symmetry", text="对称")
        if getattr(md, 'use_symmetry', False):
            _safe_prop(layout, md, "symmetry_axis")
    elif md.decimate_type == 'UNSUBDIV':
        layout.prop(md, "iterations", text="迭代次数")
    else:
        layout.prop(md, "angle_limit", text="角度限制")
        _safe_prop(layout, md, "use_dissolve_boundaries", text="溶解边界")
        layout.label(text="分隔:")
        _safe_prop(layout.row(), md, "delimit")

    layout.label(text=f"面数: {md.face_count}")


# ---- Smooth ----
def _draw_SMOOTH(layout, ob, md):
    split = _split(layout, factor=0.25)

    col = split.column()
    col.label(text="轴向:")
    col.prop(md, "use_x", text="X")
    col.prop(md, "use_y", text="Y")
    col.prop(md, "use_z", text="Z")

    col = split.column()
    col.prop(md, "factor", text="系数")
    col.prop(md, "iterations", text="重复")
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="顶点组")


# ---- Shrinkwrap ----
def _draw_SHRINKWRAP(layout, ob, md):
    split = _split(layout)
    col = split.column()
    col.label(text="目标:")
    col.prop(md, "target", text="")
    col = split.column()
    col.label(text="顶点组:")
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="")

    split = _split(layout)
    col = split.column()
    col.prop(md, "offset", text="偏移")
    col = split.column()
    col.label(text="模式:")
    col.prop(md, "wrap_method", text="")

    if md.wrap_method == 'PROJECT':
        split = _split(layout)
        col = split.column()
        _safe_prop(col, md, "subsurf_levels", text="细分级别")
        col = split.column()
        _safe_prop(col, md, "project_limit", text="限制")

        split = _split(layout, factor=0.25)
        col = split.column()
        col.label(text="轴向:")
        _safe_prop(col, md, "use_project_x", text="X")
        _safe_prop(col, md, "use_project_y", text="Y")
        _safe_prop(col, md, "use_project_z", text="Z")
        col = split.column()
        col.label(text="方向:")
        _safe_prop(col, md, "use_negative_direction", text="负方向")
        _safe_prop(col, md, "use_positive_direction", text="正方向")
        col = split.column()
        col.label(text="剔除面:")
        _safe_prop(col, md, "cull_face", expand=True)
        _safe_prop(layout, md, "auxiliary_target", text="辅助目标")

    elif md.wrap_method == 'NEAREST_SURFACEPOINT':
        _safe_prop(layout, md, "use_keep_above_surface", text="保持在表面上方")


# ---- Weighted Normal ----
def _draw_WEIGHTED_NORMAL(layout, ob, md):
    _safe_prop(layout, md, "mode", text="加权模式")
    _safe_prop(layout, md, "weight", text="权重")
    _safe_prop(layout, md, "thresh", text="阈值")
    _safe_prop(layout, md, "keep_sharp", text="保持锐边")
    _safe_prop(layout, md, "use_face_influence", text="面影响")
    _safe_prop_search(layout, md, "vertex_group", ob, "vertex_groups", text="顶点组")
    _safe_prop(layout, md, "invert_vertex_group", text="反转")


# ---- Screw ----
def _draw_SCREW(layout, ob, md):
    split = _split(layout)
    col = split.column()
    col.prop(md, "axis", text="轴向")
    col.prop(md, "object", text="轴向物体")
    col.prop(md, "angle", text="角度")
    col.prop(md, "steps", text="步数")
    col.prop(md, "render_steps", text="渲染步数")
    _safe_prop(col, md, "use_smooth_shade", text="平滑着色")

    col = split.column()
    row = col.row()
    row.active = (md.object is None or not getattr(md, 'use_object_screw_offset', False))
    row.prop(md, "screw_offset", text="螺旋偏移")
    row = col.row()
    row.active = (md.object is not None)
    _safe_prop(row, md, "use_object_screw_offset", text="物体偏移")
    _safe_prop(col, md, "use_normal_calculate", text="计算法线")
    _safe_prop(col, md, "use_normal_flip", text="翻转法线")
    col.prop(md, "iterations", text="迭代")
    _safe_prop(col, md, "use_stretch_u", text="拉伸 U")
    _safe_prop(col, md, "use_stretch_v", text="拉伸 V")


# ---- Wireframe ----
def _draw_WIREFRAME(layout, ob, md):
    has_vgroup = bool(md.vertex_group)
    split = _split(layout)

    col = split.column()
    col.prop(md, "thickness", text="厚度")
    row = col.row(align=True)
    _safe_prop_search(row, md, "vertex_group", ob, "vertex_groups", text="")
    sub = row.row(align=True)
    sub.active = has_vgroup
    _safe_prop(sub, md, "invert_vertex_group", text="", icon='ARROW_LEFTRIGHT')
    row = col.row(align=True)
    row.active = has_vgroup
    _safe_prop(row, md, "thickness_vertex_group", text="系数")
    _safe_prop(col, md, "use_crease", text="折痕")
    sub = col.column()
    sub.active = getattr(md, 'use_crease', False)
    _safe_prop(sub, md, "crease_weight", text="折痕权重")

    col = split.column()
    col.prop(md, "offset", text="偏移")
    _safe_prop(col, md, "use_even_offset", text="等距厚度")
    _safe_prop(col, md, "use_relative_offset", text="相对厚度")
    _safe_prop(col, md, "use_boundary", text="边界")
    _safe_prop(col, md, "use_replace", text="替换原始")
    _safe_prop(col, md, "material_offset", text="材质偏移")


# ---- Triangulate ----
def _draw_TRIANGULATE(layout, ob, md):
    row = layout.row()
    col = row.column()
    col.label(text="四边形方法:")
    col.prop(md, "quad_method", text="")
    col = row.column()
    col.label(text="多边形方法:")
    col.prop(md, "ngon_method", text="")
    _safe_prop(layout, md, "min_vertices", text="最小顶点数")
    _safe_prop(layout, md, "keep_custom_normals", text="保持自定义法线")


# ---- Simple Deform ----
def _draw_SIMPLE_DEFORM(layout, ob, md):
    layout.row().prop(md, "deform_method", expand=True)

    split = _split(layout)
    col = split.column()
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="顶点组")
    col.prop(md, "origin", text="原点")
    if md.deform_method in {'TAPER', 'STRETCH', 'TWIST'}:
        col.label(text="锁定:")
        _safe_prop(col, md, "lock_x", text="X")
        _safe_prop(col, md, "lock_y", text="Y")

    col = split.column()
    col.label(text="变形:")
    if md.deform_method in {'TAPER', 'STRETCH'}:
        col.prop(md, "factor", text="系数")
    else:
        col.prop(md, "angle", text="角度")
    col.prop(md, "limits", slider=True, text="限制")


# ---- Lattice ----
def _draw_LATTICE(layout, ob, md):
    split = _split(layout)
    col = split.column()
    col.label(text="物体:")
    col.prop(md, "object", text="")
    col = split.column()
    col.label(text="顶点组:")
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="")
    layout.separator()
    layout.prop(md, "strength", slider=True, text="强度")


# ---- Curve ----
def _draw_CURVE(layout, ob, md):
    split = _split(layout)
    col = split.column()
    col.label(text="曲线物体:")
    col.prop(md, "object", text="")
    col = split.column()
    col.label(text="顶点组:")
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="")
    layout.label(text="变形轴:")
    layout.row().prop(md, "deform_axis", expand=True)


# ---- Cast ----
def _draw_CAST(layout, ob, md):
    _split_row = _split(layout, factor=0.25)
    _split_row.label(text="类型:")
    _split_row.prop(md, "cast_type", text="")

    split = _split(layout, factor=0.25)
    col = split.column()
    col.prop(md, "use_x", text="X")
    col.prop(md, "use_y", text="Y")
    col.prop(md, "use_z", text="Z")
    col = split.column()
    col.prop(md, "factor", text="系数")
    col.prop(md, "radius", text="半径")
    col.prop(md, "size", text="大小")
    _safe_prop(col, md, "use_radius_as_size", text="用半径作大小")

    split = _split(layout)
    col = split.column()
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="顶点组")
    col = split.column()
    col.prop(md, "object", text="控制物体")
    if md.object:
        _safe_prop(col, md, "use_transform")


# ---- Displace ----
def _draw_DISPLACE(layout, ob, md):
    _safe_prop(layout, md, "texture_coords", text="纹理坐标")
    if getattr(md, 'texture_coords', '') == 'OBJECT':
        _safe_prop(layout, md, "texture_coords_object", text="物体")

    split = _split(layout)
    col = split.column()
    col.label(text="方向:")
    col.prop(md, "direction", text="")
    _safe_prop_search(col, md, "vertex_group", ob, "vertex_groups", text="顶点组")

    col = split.column()
    col.prop(md, "strength", text="强度")
    col.prop(md, "mid_level", text="中点")
    _safe_prop(col, md, "space", text="空间")


# ---- Weld ----
def _draw_WELD(layout, ob, md):
    _safe_prop(layout, md, "mode", text="模式")
    layout.prop(md, "merge_threshold", text="距离")
    _safe_prop_search(layout, md, "vertex_group", ob, "vertex_groups", text="顶点组")
    _safe_prop(layout, md, "invert_vertex_group", text="反转")


# ---- Data Transfer ----
def _draw_DATA_TRANSFER(layout, ob, md):
    _safe_prop(layout, md, "object", text="源物体")
    layout.separator()
    _safe_prop(layout, md, "use_vert_data", text="顶点数据")
    if getattr(md, 'use_vert_data', False):
        box = layout.box()
        _safe_prop(box.row(), md, "data_types_verts")
        _safe_prop(box, md, "vert_mapping", text="映射")
    _safe_prop(layout, md, "use_edge_data", text="边数据")
    if getattr(md, 'use_edge_data', False):
        box = layout.box()
        _safe_prop(box.row(), md, "data_types_edges")
        _safe_prop(box, md, "edge_mapping", text="映射")
    _safe_prop(layout, md, "use_loop_data", text="面角数据")
    if getattr(md, 'use_loop_data', False):
        box = layout.box()
        _safe_prop(box.row(), md, "data_types_loops")
        _safe_prop(box, md, "loop_mapping", text="映射")
    _safe_prop(layout, md, "use_poly_data", text="面数据")
    if getattr(md, 'use_poly_data', False):
        box = layout.box()
        _safe_prop(box.row(), md, "data_types_polys")
        _safe_prop(box, md, "poly_mapping", text="映射")
    layout.separator()
    _safe_prop(layout, md, "mix_mode", text="混合模式")
    _safe_prop(layout, md, "mix_factor", text="混合系数")


# ---- Multires ----
def _draw_MULTIRES(layout, ob, md):
    layout.row().prop(md, "subdivision_type", expand=True)
    split = _split(layout)
    col = split.column()
    col.prop(md, "levels", text="视口")
    col.prop(md, "sculpt_levels", text="雕刻")
    col.prop(md, "render_levels", text="渲染")
    col = split.column()
    _safe_prop(col, md, "quality")
    _safe_prop(col, md, "uv_smooth")
    _safe_prop(col, md, "boundary_smooth")
    _safe_prop(col, md, "use_creases")
    _safe_prop(col, md, "use_custom_normals")


# ============================================================
#  注册表：修改器类型 -> 绘制函数
# ============================================================

_MOD_DRAW_FUNCS = {
    'MIRROR': _draw_MIRROR,
    'SUBSURF': _draw_SUBSURF,
    'ARRAY': _draw_ARRAY,
    'SOLIDIFY': _draw_SOLIDIFY,
    'BEVEL': _draw_BEVEL,
    'BOOLEAN': _draw_BOOLEAN,
    'DECIMATE': _draw_DECIMATE,
    'SMOOTH': _draw_SMOOTH,
    'SHRINKWRAP': _draw_SHRINKWRAP,
    'WEIGHTED_NORMAL': _draw_WEIGHTED_NORMAL,
    'SCREW': _draw_SCREW,
    'WIREFRAME': _draw_WIREFRAME,
    'TRIANGULATE': _draw_TRIANGULATE,
    'SIMPLE_DEFORM': _draw_SIMPLE_DEFORM,
    'LATTICE': _draw_LATTICE,
    'CURVE': _draw_CURVE,
    'CAST': _draw_CAST,
    'DISPLACE': _draw_DISPLACE,
    'WELD': _draw_WELD,
    'DATA_TRANSFER': _draw_DATA_TRANSFER,
    'MULTIRES': _draw_MULTIRES,
}


def _draw_modifier_params(layout, obj, mod):
    """在给定的 layout 区域绘制修改器的所有可编辑参数。
    对常见修改器使用原生排版，其余回退到通用绘制。
    支持 Geometry Nodes 修改器。

    Parameters
    ----------
    layout : bpy.types.UILayout
    obj : bpy.types.Object  （拥有该修改器的代表模型）
    mod : bpy.types.Modifier
    """

    if mod is None:
        layout.label(text="(组内无可用修改器)", icon='INFO')
        return

    # ================================================================
    #  Geometry Nodes 修改器特殊处理
    # ================================================================
    if mod.type == 'NODES':
        layout.prop(mod, "node_group", text="节点组")

        node_group = getattr(mod, 'node_group', None)
        if node_group is None:
            layout.label(text="(未选择节点组)", icon='INFO')
            return

        drawn = False
        if hasattr(node_group, 'interface'):
            try:
                for item in node_group.interface.items_tree:
                    if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                        sock_id = item.identifier
                        if getattr(item, 'socket_type', '') == 'NodeSocketGeometry':
                            continue
                        try:
                            layout.prop(mod, f'["{sock_id}"]', text=item.name)
                            drawn = True
                        except (TypeError, KeyError):
                            continue
            except Exception:
                pass
        elif hasattr(node_group, 'inputs'):
            try:
                for inp in node_group.inputs:
                    if inp.type == 'GEOMETRY':
                        continue
                    sock_id = inp.identifier
                    try:
                        layout.prop(mod, f'["{sock_id}"]', text=inp.name)
                        drawn = True
                    except (TypeError, KeyError):
                        continue
            except Exception:
                pass

        if not drawn:
            layout.label(text="(该节点组无可编辑输入)", icon='INFO')
        return

    # ================================================================
    #  常见修改器：使用原生排版
    # ================================================================
    draw_func = _MOD_DRAW_FUNCS.get(mod.type)
    if draw_func is not None:
        try:
            draw_func(layout, obj, mod)
            return
        except Exception as e:
            # 如果原生排版出错（版本不兼容等），回退到通用绘制
            layout.label(text=f"(排版回退: {e})", icon='INFO')

    # ================================================================
    #  通用回退：遍历 bl_rna 属性逐个绘制
    # ================================================================
    drawn = False
    for prop in mod.bl_rna.properties:
        pid = prop.identifier
        if pid in _SKIP_PROPS:
            continue
        if prop.is_readonly:
            continue
        if pid.startswith('_'):
            continue
        try:
            layout.prop(mod, pid)
            drawn = True
        except (TypeError, AttributeError):
            continue

    if not drawn:
        layout.label(text="(无可编辑参数)", icon='INFO')


# ============================================================
#  同步逻辑
# ============================================================

def _sync_modifier_from_source(source_obj, mod_name, mod_type, source_props, group, log=True):
    """从源模型同步一个修改器到组内其他参与模型"""
    # 检查源模型是否在组内且参与同步
    source_in_group = False
    for toggle in group.objects:
        if toggle.obj == source_obj and toggle.enabled:
            source_in_group = True
            break
    if not source_in_group:
        return 0

    # 解析排除属性（兼容中英文逗号、全角空格）
    excluded = set()
    if group.excluded_props.strip():
        raw = group.excluded_props.replace('，', ',').replace('\u3000', ' ')
        excluded = {p.strip() for p in raw.split(',') if p.strip()}

    # 调试日志
    scene = bpy.context.scene
    debug = getattr(getattr(scene, 'modifier_sync_v2', None), 'debug_mode', False)
    if debug and excluded:
        matched = excluded & set(source_props.keys())
        unmatched = excluded - set(source_props.keys())
        print(f"[ModSync Debug] 组 '{group.name}' 排除属性: {excluded}")
        print(f"  → 匹配到的: {matched}")
        if unmatched:
            print(f"  → ⚠ 未匹配到（属性名不存在）: {unmatched}")
        print(f"  → 源属性 keys: {list(source_props.keys())}")

    synced_count = 0
    for toggle in group.objects:
        target_obj = toggle.obj
        if target_obj is None or target_obj == source_obj:
            continue
        if not toggle.enabled:
            continue
        if target_obj.name not in bpy.data.objects:
            continue
        target_mod = _get_obj_modifier(target_obj, mod_name, mod_type)
        if target_mod is None:
            continue
        _apply_modifier_props(target_mod, source_props, excluded=excluded)
        synced_count += 1

    # 记录同步日志
    if log and synced_count > 0:
        global _sync_log
        entry = _SyncLogEntry(source_obj.name, group.name, synced_count)
        _sync_log.append(entry)
        if len(_sync_log) > _MAX_SYNC_LOG:
            _sync_log = _sync_log[-_MAX_SYNC_LOG:]
        # 同步到 UIList 的 CollectionProperty
        _refresh_log_ui_items()

    return synced_count


# ============================================================
#  同步核心 (Timer 回调)
# ============================================================

def _sync_timer():
    """自动同步定时器。
    核心逻辑：
    1. 对每个同步组，找到该修改器发生了变化的**第一个**模型作为源
    2. 只有用户直接修改的源模型才会向其他模型同步
    3. 同步完成后统一刷新所有快照，避免乒乓效应
    """
    global _is_syncing
    if _is_syncing:
        return 0.1
    context = bpy.context
    scene = getattr(context, 'scene', None)
    if scene is None:
        return 0.1
    props = getattr(scene, 'modifier_sync_v2', None)
    if props is None or not props.global_enabled:
        return 0.1

    _is_syncing = True
    try:
        # 优先使用活动物体作为源（用户最可能在编辑的对象）
        active_obj = getattr(context, 'active_object', None)

        for group in props.sync_groups:
            if not group.enabled:
                continue
            mod_name = group.name
            mod_type = group.mod_type

            # ---- 同步源锁定模式 ----
            if group.source_locked and group.source_obj is not None:
                locked_obj = group.source_obj
                if locked_obj.name not in bpy.data.objects:
                    continue
                # 仅检测锁定源的变化
                changed = _find_changed_modifiers(locked_obj)
                if mod_name in changed:
                    _sync_modifier_from_source(
                        locked_obj, mod_name, mod_type, changed[mod_name], group
                    )
                continue

            # ---- 正常模式：收集组内所有发生变化的模型 ----
            changed_sources = []
            for toggle in group.objects:
                obj = toggle.obj
                if obj is None or not toggle.enabled:
                    continue
                if obj.name not in bpy.data.objects:
                    continue
                changed = _find_changed_modifiers(obj)
                if mod_name in changed:
                    changed_sources.append((obj, changed[mod_name]))

            if not changed_sources:
                continue

            # 选择同步源：优先活动对象，否则取第一个变化的
            source_obj = None
            source_props = None
            for obj, props_data in changed_sources:
                if obj == active_obj:
                    source_obj = obj
                    source_props = props_data
                    break
            if source_obj is None:
                source_obj, source_props = changed_sources[0]

            # 从源模型同步到组内其他模型
            _sync_modifier_from_source(
                source_obj, mod_name, mod_type, source_props, group
            )

        # 同步完成后统一刷新所有快照（关键！防止乒乓效应）
        _refresh_all_snapshots(context)
    except Exception as e:
        print(f"[Modifier Sync v2] Error: {e}")
    finally:
        _is_syncing = False
    return 0.1


def _on_global_toggle(self, context):
    if self.global_enabled:
        _refresh_all_snapshots(context)
        if not bpy.app.timers.is_registered(_sync_timer):
            bpy.app.timers.register(_sync_timer, first_interval=0.5)
    else:
        if bpy.app.timers.is_registered(_sync_timer):
            bpy.app.timers.unregister(_sync_timer)


# ============================================================
#  获取所有可用的修改器类型（用于新建同步组时选择）
# ============================================================

def _get_modifier_type_items(self, context):
    """动态生成修改器类型下拉菜单。
    列出 Blender 支持的所有修改器类型。
    """
    global _enum_items_cache

    # 从 bpy.types.Modifier.bl_rna.properties['type'].enum_items 获取所有类型
    try:
        enum_items = bpy.types.Modifier.bl_rna.properties['type'].enum_items
        items = []
        for i, item in enumerate(enum_items):
            items.append((item.identifier, item.name, item.description, i))
        if items:
            _enum_items_cache = items
            return _enum_items_cache
    except Exception:
        pass

    _enum_items_cache = [('NONE', "(无可用类型)", "", 0)]
    return _enum_items_cache


# ============================================================
#  操作符 — 通用
# ============================================================

class MODSYNC_OT_CleanInvalid(Operator):
    bl_idname = "modifier_sync_v2.clean_invalid"
    bl_label = "清理无效引用"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        total_removed = 0
        for group in props.sync_groups:
            to_remove = [i for i, item in enumerate(group.objects)
                         if not _is_object_valid(item.obj)]
            for idx in reversed(to_remove):
                group.objects.remove(idx)
            total_removed += len(to_remove)
            _sort_group_objects(group)

        if total_removed > 0:
            self.report({'INFO'}, f"已清理 {total_removed} 个无效引用")
        else:
            self.report({'INFO'}, "未发现无效引用（详情请查看系统控制台）")
        return {'FINISHED'}


class MODSYNC_OT_SyncNow(Operator):
    bl_idname = "modifier_sync_v2.sync_now"
    bl_label = "立即同步"
    bl_description = "以当前活动对象为源，将其修改器参数同步到同组其他模型"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _is_syncing
        props = context.scene.modifier_sync_v2
        active_obj = context.active_object
        if active_obj is None or active_obj.type != 'MESH':
            self.report({'WARNING'}, "请先选中一个网格模型")
            return {'CANCELLED'}

        _is_syncing = True
        synced = 0
        try:
            source_snapshot = _get_modifier_snapshot(active_obj)
            for group in props.sync_groups:
                if not group.enabled:
                    continue
                mod_name = group.name
                mod_type = group.mod_type
                in_group = any(
                    t.obj == active_obj and t.enabled
                    for t in group.objects if t.obj
                )
                if not in_group:
                    continue
                if mod_name in source_snapshot:
                    _sync_modifier_from_source(
                        active_obj, mod_name, mod_type,
                        source_snapshot[mod_name], group
                    )
                    synced += 1
            # 同步后对所有参与的组排序
            for group in props.sync_groups:
                _sort_group_objects(group)
            _refresh_all_snapshots(context)
        finally:
            _is_syncing = False

        self.report({'INFO'}, f"已同步 {synced} 个修改器")
        _tag_redraw_sidebar()
        return {'FINISHED'}


# ============================================================
#  操作符 — 同步组管理（新建 = 选择修改器类型）
# ============================================================

class MODSYNC_OT_AddGroup(Operator):
    """新建同步组：弹出对话框选择修改器类型"""
    bl_idname = "modifier_sync_v2.add_group"
    bl_label = "新建同步组"
    bl_description = "选择一个修改器类型来创建同步组"
    bl_options = {'REGISTER', 'UNDO'}

    modifier_type: EnumProperty(
        name="修改器类型",
        items=_get_modifier_type_items,
    )
    modifier_name: StringProperty(
        name="修改器名称",
        default="",
        description="修改器在模型上的显示名称（留空则使用默认名称）",
    )

    def execute(self, context):
        if self.modifier_type == 'NONE':
            self.report({'WARNING'}, "请选择一个修改器类型")
            return {'CANCELLED'}

        props = context.scene.modifier_sync_v2

        # 获取修改器的默认名称
        mod_type = self.modifier_type
        mod_name = self.modifier_name.strip()
        if not mod_name:
            # 使用 Blender 的默认名称
            try:
                for item in bpy.types.Modifier.bl_rna.properties['type'].enum_items:
                    if item.identifier == mod_type:
                        mod_name = item.name
                        break
            except Exception:
                mod_name = mod_type

        # 检查是否已存在同名同类型的组
        for g in props.sync_groups:
            if g.name == mod_name and g.mod_type == mod_type:
                self.report({'WARNING'}, f"已存在 {mod_name} ({mod_type}) 的同步组")
                return {'CANCELLED'}

        group = props.sync_groups.add()
        group.name = mod_name
        group.mod_type = mod_type
        group.enabled = True
        props.active_group_index = len(props.sync_groups) - 1

        _tag_redraw_sidebar()
        self.report({'INFO'}, f"已创建同步组: {mod_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "modifier_type", text="类型")
        layout.prop(self, "modifier_name", text="名称（可选）")


class MODSYNC_OT_RemoveGroup(Operator):
    bl_idname = "modifier_sync_v2.remove_group"
    bl_label = "删除同步组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if 0 <= idx < len(props.sync_groups):
            props.sync_groups.remove(idx)
            props.active_group_index = max(0, idx - 1)
        return {'FINISHED'}


# ---- 吸取修改器：枚举回调 ----

def _get_pick_obj_items(self, context):
    """列出场景中所有拥有修改器的网格模型"""
    global _enum_pick_obj_cache

    items = []
    idx = 0
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and len(obj.modifiers) > 0:
            items.append((obj.name, obj.name, f"{len(obj.modifiers)} 个修改器", idx))
            idx += 1

    if not items:
        items = [('NONE', "(场景中无可用模型)", "", 0)]

    _enum_pick_obj_cache = items
    return _enum_pick_obj_cache


def _get_pick_mod_items(self, context):
    """根据已选模型，列出其所有修改器"""
    global _enum_pick_mod_cache

    obj = bpy.data.objects.get(self.pick_object)
    if obj is None or len(obj.modifiers) == 0:
        _enum_pick_mod_cache = [('NONE', "(该模型无修改器)", "", 0)]
        return _enum_pick_mod_cache

    items = []
    for i, mod in enumerate(obj.modifiers):
        label = f"{mod.name} ({mod.type})"
        # identifier 用 "名称||类型" 格式
        identifier = f"{mod.name}||{mod.type}"
        items.append((identifier, label, "", i))

    _enum_pick_mod_cache = items
    return _enum_pick_mod_cache


class MODSYNC_OT_PickModifier(Operator):
    """从场景中某个模型上吸取一个修改器，创建同步组并将该模型加入"""
    bl_idname = "modifier_sync_v2.pick_modifier"
    bl_label = "吸取修改器"
    bl_description = "从场景中某个模型上选取一个已有的修改器来创建同步组"
    bl_options = {'REGISTER', 'UNDO'}

    pick_object: EnumProperty(
        name="选择模型",
        description="选择要吸取修改器的模型",
        items=_get_pick_obj_items,
    )
    pick_modifier: EnumProperty(
        name="选择修改器",
        description="选择该模型上的修改器",
        items=_get_pick_mod_items,
    )

    def execute(self, context):
        if self.pick_object == 'NONE':
            self.report({'WARNING'}, "场景中没有可用的模型")
            return {'CANCELLED'}
        if self.pick_modifier == 'NONE':
            self.report({'WARNING'}, "该模型没有修改器")
            return {'CANCELLED'}

        parts = self.pick_modifier.split("||")
        if len(parts) != 2:
            return {'CANCELLED'}

        mod_name, mod_type = parts[0], parts[1]
        obj = bpy.data.objects.get(self.pick_object)
        if obj is None:
            self.report({'WARNING'}, "模型不存在")
            return {'CANCELLED'}

        props = context.scene.modifier_sync_v2

        # 检查是否已存在同名同类型的组
        for g in props.sync_groups:
            if g.name == mod_name and g.mod_type == mod_type:
                # 已存在，直接把模型添加进去（如果还没在里面）
                existing = {t.obj for t in g.objects if t.obj is not None}
                if obj not in existing:
                    item = g.objects.add()
                    item.obj = obj
                    item.enabled = True
                    _refresh_all_snapshots(context)
                    self.report({'INFO'}, f"已将 {obj.name} 添加到现有同步组 {mod_name}")
                else:
                    self.report({'INFO'}, f"{obj.name} 已在同步组 {mod_name} 中")
                # 切换到该组
                for i, gg in enumerate(props.sync_groups):
                    if gg.name == mod_name and gg.mod_type == mod_type:
                        props.active_group_index = i
                        break
                _tag_redraw_sidebar()
                return {'FINISHED'}

        # 新建同步组
        group = props.sync_groups.add()
        group.name = mod_name
        group.mod_type = mod_type
        group.enabled = True
        props.active_group_index = len(props.sync_groups) - 1

        # 将源模型加入组
        item = group.objects.add()
        item.obj = obj
        item.enabled = True

        _refresh_all_snapshots(context)
        _tag_redraw_sidebar()
        self.report({'INFO'}, f"已从 {obj.name} 吸取修改器 {mod_name}，创建同步组")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 如果当前有选中的模型且该模型有修改器，自动选中它
        active_obj = context.active_object
        if active_obj is not None and active_obj.type == 'MESH' and len(active_obj.modifiers) > 0:
            self.pick_object = active_obj.name
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pick_object", text="模型")
        layout.prop(self, "pick_modifier", text="修改器")


# ============================================================
#  操作符 — 组内模型管理
# ============================================================

class MODSYNC_OT_AddSelectedObjects(Operator):
    """将选中的模型添加到当前同步组，自动为缺少修改器的模型补齐"""
    bl_idname = "modifier_sync_v2.add_selected_objects"
    bl_label = "添加选中模型"
    bl_description = "将场景中选中的模型添加到当前同步组，自动补齐修改器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if idx < 0 or idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先创建一个同步组")
            return {'CANCELLED'}
        group = props.sync_groups[idx]
        mod_name = group.name
        mod_type = group.mod_type

        existing = {item.obj for item in group.objects if item.obj is not None}

        # 找一个已有该修改器的模型作为参数源
        source_props = None
        for toggle in group.objects:
            if toggle.obj is None or toggle.obj.name not in bpy.data.objects:
                continue
            src_mod = _get_obj_modifier(toggle.obj, mod_name, mod_type)
            if src_mod is not None:
                source_props = _get_modifier_snapshot(toggle.obj).get(mod_name, {})
                break

        added = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or obj in existing:
                continue
            item = group.objects.add()
            item.obj = obj
            item.enabled = True
            added += 1

            # 自动补齐修改器
            existing_mod = _get_obj_modifier(obj, mod_name, mod_type)
            if existing_mod is None:
                new_mod = obj.modifiers.new(name=mod_name, type=mod_type)
                if new_mod is not None and source_props:
                    _apply_modifier_props(new_mod, source_props)
            else:
                # 已有修改器，若有源参数也同步一下
                if source_props is None:
                    # 这个模型本身就可以作为源
                    source_props = _get_modifier_snapshot(obj).get(mod_name, {})

        if added > 0:
            _sort_group_objects(group)
            _refresh_all_snapshots(context)
            _tag_redraw_sidebar()
            self.report({'INFO'}, f"已添加 {added} 个模型（自动补齐修改器）")
        else:
            self.report({'INFO'}, "没有新的网格模型可添加")
        return {'FINISHED'}


class MODSYNC_OT_RemoveObject(Operator):
    bl_idname = "modifier_sync_v2.remove_object"
    bl_label = "移除模型"
    bl_description = "从同步组中移除模型（不删除模型上的修改器）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            return {'CANCELLED'}
        group = props.sync_groups[g_idx]
        o_idx = group.active_object_index
        if 0 <= o_idx < len(group.objects):
            group.objects.remove(o_idx)
            group.active_object_index = max(0, o_idx - 1)
        _tag_redraw_sidebar()
        return {'FINISHED'}


class MODSYNC_OT_RemoveObjectAndMod(Operator):
    """从同步组移除模型，同时删除模型上对应的修改器"""
    bl_idname = "modifier_sync_v2.remove_object_and_mod"
    bl_label = "移除模型并删除修改器"
    bl_description = "从同步组中移除模型，并同时删除该模型上的对应修改器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            return {'CANCELLED'}
        group = props.sync_groups[g_idx]
        o_idx = group.active_object_index
        if 0 <= o_idx < len(group.objects):
            toggle = group.objects[o_idx]
            obj = toggle.obj
            if obj is not None and obj.name in bpy.data.objects:
                mod = _get_obj_modifier(obj, group.name, group.mod_type)
                if mod is not None:
                    obj.modifiers.remove(mod)
            group.objects.remove(o_idx)
            group.active_object_index = max(0, o_idx - 1)
            _refresh_all_snapshots(context)
        return {'FINISHED'}


class MODSYNC_OT_SelectObject(Operator):
    """点击组内模型名称，在视口中选中并激活该模型"""
    bl_idname = "modifier_sync_v2.select_object"
    bl_label = "选中模型"
    bl_description = "在视口中选中并激活该模型"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if obj is None:
            self.report({'WARNING'}, f"模型 '{self.object_name}' 不存在")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class MODSYNC_OT_SelectAllObjects(Operator):
    """选中当前同步组内的所有模型（不改变活动物体）"""
    bl_idname = "modifier_sync_v2.select_all_objects"
    bl_label = "全选组内模型"
    bl_description = "选中当前同步组内的所有模型（不改变活动物体）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先创建一个同步组")
            return {'CANCELLED'}

        group = props.sync_groups[g_idx]
        selected = 0
        for item in group.objects:
            obj = item.obj
            if obj is not None and obj.name in bpy.data.objects:
                obj.select_set(True)
                selected += 1

        self.report({'INFO'}, f"已选中 {selected} 个模型")
        return {'FINISHED'}


class MODSYNC_OT_RepairMissingModifiers(Operator):
    """为组内所有缺失修改器的模型自动补齐修改器并同步参数"""
    bl_idname = "modifier_sync_v2.repair_missing_modifiers"
    bl_label = "补齐缺失修改器"
    bl_description = "为组内所有缺失修改器的模型重新创建修改器，并从已有源同步参数"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先选中一个同步组")
            return {'CANCELLED'}

        group = props.sync_groups[g_idx]
        mod_name = group.name
        mod_type = group.mod_type

        # 找一个已有该修改器的模型作为参数源
        source_props = None
        for toggle in group.objects:
            obj = toggle.obj
            if obj is None or obj.name not in bpy.data.objects:
                continue
            src_mod = _get_obj_modifier(obj, mod_name, mod_type)
            if src_mod is not None:
                source_props = _get_modifier_snapshot(obj).get(mod_name, {})
                break

        repaired = 0
        for toggle in group.objects:
            obj = toggle.obj
            if obj is None or obj.name not in bpy.data.objects:
                continue
            existing_mod = _get_obj_modifier(obj, mod_name, mod_type)
            if existing_mod is not None:
                continue
            # 该模型缺少修改器，补齐
            new_mod = obj.modifiers.new(name=mod_name, type=mod_type)
            if new_mod is not None:
                if source_props:
                    _apply_modifier_props(new_mod, source_props)
                repaired += 1
                # 如果之前没有源，用刚创建的作为源
                if source_props is None:
                    source_props = _get_modifier_snapshot(obj).get(mod_name, {})

        if repaired > 0:
            _sort_group_objects(group)
            _refresh_all_snapshots(context)
            _tag_redraw_sidebar()
            self.report({'INFO'}, f"已为 {repaired} 个模型补齐修改器 {mod_name}")
        else:
            self.report({'INFO'}, "组内所有模型均已拥有该修改器")
        return {'FINISHED'}


class MODSYNC_OT_CleanMissingModifiers(Operator):
    """将组内所有缺失修改器的模型移出同步组"""
    bl_idname = "modifier_sync_v2.clean_missing_modifiers"
    bl_label = "清理无修改器模型"
    bl_description = "将组内所有缺失对应修改器的模型从同步组中移除"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先选中一个同步组")
            return {'CANCELLED'}

        group = props.sync_groups[g_idx]
        mod_name = group.name
        mod_type = group.mod_type

        to_remove = []
        for i, toggle in enumerate(group.objects):
            obj = toggle.obj
            if not _is_object_valid(obj):
                to_remove.append(i)
                continue
            existing_mod = _get_obj_modifier(obj, mod_name, mod_type)
            if existing_mod is None:
                to_remove.append(i)

        for i in reversed(to_remove):
            group.objects.remove(i)

        if to_remove:
            group.active_object_index = min(
                group.active_object_index, max(0, len(group.objects) - 1)
            )
            _sort_group_objects(group)
            _refresh_all_snapshots(context)
            self.report({'INFO'}, f"已移除 {len(to_remove)} 个无修改器/失效的模型")
        else:
            self.report({'INFO'}, "组内所有模型状态正常")
        return {'FINISHED'}


class MODSYNC_OT_SortGroupObjects(Operator):
    """手动刷新组内模型排序：无修改器/失效模型置顶"""
    bl_idname = "modifier_sync_v2.sort_group_objects"
    bl_label = "排序组内模型"
    bl_description = "按状态排序：无修改器/失效模型置顶，正常模型按名称排序"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先选中一个同步组")
            return {'CANCELLED'}
        group = props.sync_groups[g_idx]
        _sort_group_objects(group)
        self.report({'INFO'}, "已刷新排序")
        return {'FINISHED'}


# ============================================================
#  操作符 — 修改器视口可见性 / 同步开关 / 展开折叠
# ============================================================

class MODSYNC_OT_ToggleGroupSync(Operator):
    """切换同步组的同步开关"""
    bl_idname = "modifier_sync_v2.toggle_group_sync"
    bl_label = "切换组同步"
    bl_options = {'REGISTER', 'UNDO'}
    group_index: IntProperty()

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = self.group_index
        if 0 <= g_idx < len(props.sync_groups):
            props.sync_groups[g_idx].enabled = not props.sync_groups[g_idx].enabled
        return {'FINISHED'}


class MODSYNC_OT_ToggleGroupExpand(Operator):
    """展开/折叠同步组详情"""
    bl_idname = "modifier_sync_v2.toggle_expand"
    bl_label = "展开/折叠"
    bl_options = {'REGISTER', 'UNDO'}
    group_index: IntProperty()

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = self.group_index
        if 0 <= g_idx < len(props.sync_groups):
            props.sync_groups[g_idx].expanded = not props.sync_groups[g_idx].expanded
        return {'FINISHED'}


class MODSYNC_OT_ToggleObjParticipation(Operator):
    """切换组内单个模型的同步参与"""
    bl_idname = "modifier_sync_v2.toggle_obj"
    bl_label = "切换模型参与"
    bl_options = {'REGISTER', 'UNDO'}
    group_index: IntProperty()
    toggle_index: IntProperty()

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        group = props.sync_groups[self.group_index]
        toggle = group.objects[self.toggle_index]
        toggle.enabled = not toggle.enabled
        return {'FINISHED'}


class MODSYNC_OT_ToggleModViewport(Operator):
    """一键开启/关闭组内所有模型上该修改器的视口可见性"""
    bl_idname = "modifier_sync_v2.toggle_mod_viewport"
    bl_label = "切换修改器视口显示"
    bl_description = "批量开启/关闭组内模型上该修改器的视口可见性"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = self.group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            return {'CANCELLED'}
        group = props.sync_groups[g_idx]

        mods = []
        for toggle in group.objects:
            if toggle.obj is None or toggle.obj.name not in bpy.data.objects:
                continue
            mod = _get_obj_modifier(toggle.obj, group.name, group.mod_type)
            if mod is not None:
                mods.append(mod)

        if not mods:
            self.report({'INFO'}, "没有模型拥有此修改器")
            return {'CANCELLED'}

        visible_count = sum(1 for m in mods if m.show_viewport)
        new_state = visible_count <= len(mods) // 2

        for mod in mods:
            mod.show_viewport = new_state

        state_text = "开启" if new_state else "关闭"
        self.report({'INFO'}, f"已{state_text} {len(mods)} 个模型的 {group.name} 视口显示")
        return {'FINISHED'}


class MODSYNC_OT_ToggleModRender(Operator):
    """一键开启/关闭组内所有模型上该修改器的渲染可见性"""
    bl_idname = "modifier_sync_v2.toggle_mod_render"
    bl_label = "切换修改器渲染显示"
    bl_description = "批量开启/关闭组内模型上该修改器的渲染可见性"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty()

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        g_idx = self.group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            return {'CANCELLED'}
        group = props.sync_groups[g_idx]

        mods = []
        for toggle in group.objects:
            if toggle.obj is None or toggle.obj.name not in bpy.data.objects:
                continue
            mod = _get_obj_modifier(toggle.obj, group.name, group.mod_type)
            if mod is not None:
                mods.append(mod)

        if not mods:
            self.report({'INFO'}, "没有模型拥有此修改器")
            return {'CANCELLED'}

        render_count = sum(1 for m in mods if m.show_render)
        new_state = render_count <= len(mods) // 2

        for mod in mods:
            mod.show_render = new_state

        state_text = "开启" if new_state else "关闭"
        self.report({'INFO'}, f"已{state_text} {len(mods)} 个模型的 {group.name} 渲染显示")
        return {'FINISHED'}


class MODSYNC_OT_AddFromCollection(Operator):
    """从 Blender Collection 中批量添加网格模型到当前同步组"""
    bl_idname = "modifier_sync_v2.add_from_collection"
    bl_label = "按集合添加模型"
    bl_description = "选择一个 Collection，将其中所有网格模型添加到当前同步组"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(
        name="集合名称",
        default="",
    )

    def _get_collection_items(self, context):
        global _enum_collection_cache
        items = []
        for i, col in enumerate(bpy.data.collections):
            mesh_count = sum(1 for o in col.objects if o.type == 'MESH')
            if mesh_count > 0:
                items.append((col.name, f"{col.name} ({mesh_count} 个网格)", "", i))
        if not items:
            items = [('NONE', "(无可用集合)", "", 0)]
        _enum_collection_cache = items
        return _enum_collection_cache

    pick_collection: EnumProperty(
        name="选择集合",
        items=_get_collection_items,
    )
    include_children: BoolProperty(
        name="包含子集合",
        default=True,
        description="是否包含子集合中的模型",
    )

    def _collect_objects(self, collection, include_children):
        """递归收集集合中的所有网格模型"""
        objs = set()
        for obj in collection.objects:
            if obj.type == 'MESH':
                objs.add(obj)
        if include_children:
            for child in collection.children:
                objs.update(self._collect_objects(child, True))
        return objs

    def execute(self, context):
        if self.pick_collection == 'NONE':
            self.report({'WARNING'}, "场景中没有包含网格的集合")
            return {'CANCELLED'}

        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if idx < 0 or idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先创建一个同步组")
            return {'CANCELLED'}

        collection = bpy.data.collections.get(self.pick_collection)
        if collection is None:
            self.report({'WARNING'}, "集合不存在")
            return {'CANCELLED'}

        group = props.sync_groups[idx]
        mod_name = group.name
        mod_type = group.mod_type
        existing = {item.obj for item in group.objects if item.obj is not None}

        # 找一个已有该修改器的模型作为参数源
        source_props = None
        for toggle in group.objects:
            if toggle.obj is None or toggle.obj.name not in bpy.data.objects:
                continue
            src_mod = _get_obj_modifier(toggle.obj, mod_name, mod_type)
            if src_mod is not None:
                source_props = _get_modifier_snapshot(toggle.obj).get(mod_name, {})
                break

        mesh_objs = self._collect_objects(collection, self.include_children)
        added = 0
        for obj in sorted(mesh_objs, key=lambda o: o.name):
            if obj in existing:
                continue
            item = group.objects.add()
            item.obj = obj
            item.enabled = True
            added += 1

            # 自动补齐修改器
            existing_mod = _get_obj_modifier(obj, mod_name, mod_type)
            if existing_mod is None:
                new_mod = obj.modifiers.new(name=mod_name, type=mod_type)
                if new_mod is not None and source_props:
                    _apply_modifier_props(new_mod, source_props)
            else:
                if source_props is None:
                    source_props = _get_modifier_snapshot(obj).get(mod_name, {})

        if added > 0:
            _sort_group_objects(group)
            _refresh_all_snapshots(context)
            _tag_redraw_sidebar()
            self.report({'INFO'}, f"已从集合 '{self.pick_collection}' 添加 {added} 个模型")
        else:
            self.report({'INFO'}, "集合中没有新的网格模型可添加")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pick_collection", text="集合")
        layout.prop(self, "include_children")


class MODSYNC_OT_DuplicateGroup(Operator):
    """复制当前同步组的配置（修改器类型+参数），创建新组（不包含模型）"""
    bl_idname = "modifier_sync_v2.duplicate_group"
    bl_label = "复制同步组"
    bl_description = "复制当前同步组的修改器配置，创建一个新的空组"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(
        name="新组名称",
        default="",
        description="新同步组中修改器的名称（留空则自动编号）",
    )

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if idx < 0 or idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先选中一个同步组")
            return {'CANCELLED'}

        src_group = props.sync_groups[idx]
        new_name = self.new_name.strip()
        if not new_name:
            # 自动编号
            base_name = src_group.name
            counter = 2
            while True:
                candidate = f"{base_name}.{counter:03d}"
                exists = any(g.name == candidate and g.mod_type == src_group.mod_type for g in props.sync_groups)
                if not exists:
                    new_name = candidate
                    break
                counter += 1

        # 检查是否已存在
        for g in props.sync_groups:
            if g.name == new_name and g.mod_type == src_group.mod_type:
                self.report({'WARNING'}, f"已存在 {new_name} ({src_group.mod_type}) 的同步组")
                return {'CANCELLED'}

        new_group = props.sync_groups.add()
        new_group.name = new_name
        new_group.mod_type = src_group.mod_type
        new_group.enabled = src_group.enabled
        new_group.excluded_props = src_group.excluded_props
        new_group.source_locked = False
        props.active_group_index = len(props.sync_groups) - 1

        self.report({'INFO'}, f"已复制同步组: {new_name} ({src_group.mod_type})")
        return {'FINISHED'}

    def invoke(self, context, event):
        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if 0 <= idx < len(props.sync_groups):
            src = props.sync_groups[idx]
            self.new_name = f"{src.name}.001"
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name", text="新组名称")


class MODSYNC_OT_ClearSyncLog(Operator):
    """清空同步日志"""
    bl_idname = "modifier_sync_v2.clear_sync_log"
    bl_label = "清空同步日志"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _sync_log
        _sync_log.clear()
        # 同步清空 UIList 数据
        props = context.scene.modifier_sync_v2
        props.sync_log_items.clear()
        props.sync_log_active_index = 0
        self.report({'INFO'}, "已清空同步日志")
        return {'FINISHED'}


class MODSYNC_OT_ShowModProps(Operator):
    """显示当前同步组修改器的所有可用属性名（用于排除属性参考）"""
    bl_idname = "modifier_sync_v2.show_mod_props"
    bl_label = "查看可用属性名"
    bl_description = "列出当前修改器所有可同步的属性名称（用于填写排除属性）"

    def execute(self, context):
        props = context.scene.modifier_sync_v2
        idx = props.active_group_index
        if idx < 0 or idx >= len(props.sync_groups):
            self.report({'WARNING'}, "请先选中一个同步组")
            return {'CANCELLED'}

        group = props.sync_groups[idx]
        _, mod = _get_representative_modifier(group)
        if mod is None:
            self.report({'WARNING'}, "组内无可用修改器")
            return {'CANCELLED'}

        # 收集所有可同步的属性
        prop_names = []
        for prop in mod.bl_rna.properties:
            if prop.identifier == 'rna_type' or prop.is_readonly:
                continue
            prop_names.append(prop.identifier)

        # 输出到系统控制台和信息栏
        print(f"\\n[Modifier Sync] 修改器 '{group.name}' ({group.mod_type}) 可排除属性列表:")
        print(f"  {', '.join(prop_names)}")
        print(f"  (共 {len(prop_names)} 个属性)")

        # 显示在 info 中
        self.report({'INFO'}, f"属性列表已输出到系统控制台 (共 {len(prop_names)} 个): {', '.join(prop_names[:8])}...")
        return {'FINISHED'}


# ============================================================
#  UI 列表
# ============================================================

class MODSYNC_UL_SyncLogList(UIList):
    """同步日志滚动列表"""
    bl_idname = "MODSYNC_UL_SyncLogList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.text, icon='BLANK1')
        elif self.layout_type == 'GRID':
            layout.label(text="", icon='TEXT')


class MODSYNC_UL_GroupList(UIList):
    bl_idname = "MODSYNC_UL_GroupList_V2"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # 修改器图标
            row.label(text="", icon='MODIFIER')
            # 组名 = 修改器名称（不可内联编辑，用 label）
            row.label(text=f"{item.name} ({item.mod_type})")
            # 同步开关
            sync_icon = 'CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT'
            row.prop(item, "enabled", text="", icon=sync_icon, emboss=False)
            # 模型数量 + 缺失警告
            valid_count = 0
            missing_count = 0
            vis_mods = []
            for t in item.objects:
                if t.obj and t.obj.name in bpy.data.objects:
                    valid_count += 1
                    mod = _get_obj_modifier(t.obj, item.name, item.mod_type)
                    if mod is None:
                        missing_count += 1
                    elif mod is not None:
                        vis_mods.append(mod)
            if missing_count > 0:
                row.label(text=f"({valid_count} \u26a0{missing_count})", icon='ERROR')
            else:
                row.label(text=f"({valid_count})")
            # 视口可见性切换（监视器图标，与原生修改器一致）
            if vis_mods:
                vis_count = sum(1 for m in vis_mods if m.show_viewport)
                if vis_count == len(vis_mods):
                    eye_icon = 'RESTRICT_VIEW_OFF'
                elif vis_count == 0:
                    eye_icon = 'RESTRICT_VIEW_ON'
                else:
                    eye_icon = 'RESTRICT_VIEW_OFF'
            else:
                eye_icon = 'RESTRICT_VIEW_ON'
            op = row.operator("modifier_sync_v2.toggle_mod_viewport", text="", icon=eye_icon, emboss=False)
            op.group_index = index
            # 渲染可见性切换（相机图标）
            if vis_mods:
                render_count = sum(1 for m in vis_mods if m.show_render)
                if render_count == len(vis_mods):
                    cam_icon = 'RESTRICT_RENDER_OFF'
                elif render_count == 0:
                    cam_icon = 'RESTRICT_RENDER_ON'
                else:
                    cam_icon = 'RESTRICT_RENDER_OFF'
            else:
                cam_icon = 'RESTRICT_RENDER_ON'
            op = row.operator("modifier_sync_v2.toggle_mod_render", text="", icon=cam_icon, emboss=False)
            op.group_index = index
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name, icon='MODIFIER')


class MODSYNC_UL_ObjectList(UIList):
    bl_idname = "MODSYNC_UL_ObjectList_V2"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if item.obj is not None and item.obj.name in bpy.data.objects:
                group = data  # data is the SyncGroup
                mod = _get_obj_modifier(item.obj, group.name, group.mod_type)

                row = layout.row(align=True)
                # 无修改器时整行标红
                if mod is None:
                    row.alert = True

                # 可点击按钮：选中模型
                is_active = (context.view_layer.objects.active == item.obj)
                op = row.operator(
                    "modifier_sync_v2.select_object",
                    text=item.obj.name,
                    icon='OUTLINER_OB_MESH' if is_active else 'OBJECT_DATA',
                    emboss=is_active,
                )
                op.object_name = item.obj.name

                # 显示该模型上修改器状态
                if mod is not None:
                    row.label(text="", icon='CHECKMARK')
                else:
                    row.label(text="(无修改器)", icon='ERROR')

                # 同步参与勾选
                chk_icon = 'CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT'
                row.prop(item, "enabled", text="", icon=chk_icon, emboss=False)
            else:
                row = layout.row(align=True)
                row.alert = True
                row.label(text="(已失效)", icon='ERROR')


# ============================================================
#  UI 面板
# ============================================================

class MODSYNC_PT_MainPanel(Panel):
    bl_label = "修改器同步 v2"
    bl_idname = "MODSYNC_PT_MainPanel_V2"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "修改器同步"

    def draw(self, context):
        layout = self.layout
        props = context.scene.modifier_sync_v2

        # ---- 全局开关 ----
        row = layout.row(align=True)
        icon = 'PLAY' if not props.global_enabled else 'PAUSE'
        text = "启用自动同步" if not props.global_enabled else "停止自动同步"
        row.prop(props, "global_enabled", text=text, icon=icon, toggle=True)

        layout.separator()

        # ---- 同步组列表（每个组 = 一个修改器） ----
        row = layout.row()
        row.template_list(
            "MODSYNC_UL_GroupList_V2", "",
            props, "sync_groups",
            props, "active_group_index",
            rows=3,
        )
        col = row.column(align=True)
        col.operator("modifier_sync_v2.add_group", text="", icon='ADD')
        col.operator("modifier_sync_v2.remove_group", text="", icon='REMOVE')
        col.separator()
        col.operator("modifier_sync_v2.pick_modifier", text="", icon='EYEDROPPER')
        col.operator("modifier_sync_v2.duplicate_group", text="", icon='DUPLICATE')

        layout.separator()

        g_idx = props.active_group_index
        if g_idx < 0 or g_idx >= len(props.sync_groups):
            return

        group = props.sync_groups[g_idx]

        # ---- 修改器参数面板（可折叠） ----
        repr_obj, repr_mod = _get_representative_modifier(group)

        param_box = layout.box()
        param_header = param_box.row(align=True)
        expand_icon = 'TRIA_DOWN' if group.params_expanded else 'TRIA_RIGHT'
        param_header.prop(group, "params_expanded", text="", icon=expand_icon, emboss=False)
        param_header.label(text="修改器参数", icon='PREFERENCES')
        if repr_obj is not None:
            param_header.label(text=f"(源: {repr_obj.name})")
        else:
            param_header.label(text="(组内无可用修改器)")

        if group.params_expanded:
            if repr_mod is not None:
                param_col = param_box.column(align=False)
                _draw_modifier_params(param_col, repr_obj, repr_mod)
            else:
                param_box.label(text="请先添加拥有此修改器的模型", icon='INFO')

        # ---- 同步源锁定 ----
        src_box = layout.box()
        src_row = src_box.row(align=True)
        lock_icon = 'LOCKED' if group.source_locked else 'UNLOCKED'
        src_row.prop(group, "source_locked", text="", icon=lock_icon, toggle=True)
        if group.source_locked:
            src_row.prop(group, "source_obj", text="同步源")
            if group.source_obj is not None:
                src_row.label(text="", icon='CHECKMARK')
        else:
            src_row.label(text="同步源: 自动（活动物体优先）")

        # ---- 排除属性（选择性同步） ----
        excl_row = src_box.row(align=True)
        if group.excluded_props.strip():
            excl_row.label(text="排除属性:", icon='FILTER')
            excl_row.prop(group, "excluded_props", text="")
        else:
            excl_row.prop(group, "excluded_props", text="排除属性（逗号分隔）", icon='FILTER')
        excl_row.operator("modifier_sync_v2.show_mod_props", text="", icon='QUESTION')

        # ---- 组内模型 ----
        box = layout.box()
        box.label(text="组内模型:", icon='OBJECT_DATA')
        row = box.row()
        row.template_list(
            "MODSYNC_UL_ObjectList_V2", "",
            group, "objects",
            group, "active_object_index",
            rows=3,
        )
        col = row.column(align=True)
        col.operator("modifier_sync_v2.add_selected_objects", text="", icon='ADD')
        col.operator("modifier_sync_v2.add_from_collection", text="", icon='OUTLINER_COLLECTION')
        col.operator("modifier_sync_v2.remove_object", text="", icon='REMOVE')
        col.separator()
        col.operator("modifier_sync_v2.remove_object_and_mod", text="", icon='TRASH')
        col.separator()
        col.operator("modifier_sync_v2.select_all_objects", text="", icon='RESTRICT_SELECT_OFF')
        col.separator()
        col.operator("modifier_sync_v2.repair_missing_modifiers", text="", icon='TOOL_SETTINGS')
        col.operator("modifier_sync_v2.clean_missing_modifiers", text="", icon='BRUSH_DATA')
        col.separator()
        col.operator("modifier_sync_v2.sync_now", text="", icon='FILE_REFRESH')
        col.operator("modifier_sync_v2.clean_invalid", text="", icon='PANEL_CLOSE')
        col.operator("modifier_sync_v2.sort_group_objects", text="", icon='SORTALPHA')

        # ---- 状态信息 ----
        box = layout.box()
        box.label(text="状态信息:", icon='INFO')
        timer_running = bpy.app.timers.is_registered(_sync_timer)
        box.label(text=f"自动同步: {'运行中' if timer_running else '已停止'}")
        box.label(text=f"同步组数量: {len(props.sync_groups)}")
        total_objs = sum(
            sum(1 for t in g.objects if t.obj and t.obj.name in bpy.data.objects)
            for g in props.sync_groups
        )
        box.label(text=f"管理模型总数: {total_objs}")

        # ---- 同步日志（可折叠） ----
        log_box = layout.box()
        log_header = log_box.row(align=True)
        log_header.prop(
            props, "sync_log_expanded",
            text="",
            icon='TRIA_DOWN' if props.sync_log_expanded else 'TRIA_RIGHT',
            emboss=False,
        )
        log_header.label(text=f"同步日志 ({len(_sync_log)})", icon='TEXT')
        if _sync_log:
            log_header.operator("modifier_sync_v2.clear_sync_log", text="", icon='TRASH')

        if props.sync_log_expanded:
            # 调试模式开关
            log_box.prop(props, "debug_mode", text="调试模式（控制台输出）", icon='CONSOLE')

            if _sync_log:
                log_box.template_list(
                    "MODSYNC_UL_SyncLogList", "",
                    props, "sync_log_items",
                    props, "sync_log_active_index",
                    rows=5,
                    maxrows=8,
                )
            else:
                log_box.label(text="暂无同步记录", icon='BLANK1')


# ============================================================
#  注册 / 注销
# ============================================================

classes = (
    MODSYNC_ObjectToggle,
    MODSYNC_SyncGroup,
    MODSYNC_SyncLogItem,
    MODSYNC_SceneProperties,
    MODSYNC_OT_CleanInvalid,
    MODSYNC_OT_SyncNow,
    MODSYNC_OT_AddGroup,
    MODSYNC_OT_RemoveGroup,
    MODSYNC_OT_PickModifier,
    MODSYNC_OT_AddSelectedObjects,
    MODSYNC_OT_RemoveObject,
    MODSYNC_OT_RemoveObjectAndMod,
    MODSYNC_OT_SelectObject,
    MODSYNC_OT_SelectAllObjects,
    MODSYNC_OT_RepairMissingModifiers,
    MODSYNC_OT_CleanMissingModifiers,
    MODSYNC_OT_SortGroupObjects,
    MODSYNC_OT_ToggleGroupSync,
    MODSYNC_OT_ToggleGroupExpand,
    MODSYNC_OT_ToggleObjParticipation,
    MODSYNC_OT_ToggleModViewport,
    MODSYNC_OT_ToggleModRender,
    MODSYNC_OT_AddFromCollection,
    MODSYNC_OT_DuplicateGroup,
    MODSYNC_OT_ClearSyncLog,
    MODSYNC_OT_ShowModProps,
    MODSYNC_UL_SyncLogList,
    MODSYNC_UL_GroupList,
    MODSYNC_UL_ObjectList,
    MODSYNC_PT_MainPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.modifier_sync_v2 = PointerProperty(type=MODSYNC_SceneProperties)
    print("[Modifier Sync v2] 插件已启用 (v6.0)")


def unregister():
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    del bpy.types.Scene.modifier_sync_v2
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[Modifier Sync v2] 插件已禁用")


if __name__ == "__main__":
    register()
