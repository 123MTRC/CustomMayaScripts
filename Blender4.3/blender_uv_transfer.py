"""
1U to 2U - Blender UV Transfer Tool
将UV0的贴图转烘到UV1上

功能：
- 支持将模型第一套UV的贴图转烘到第二套UV
- 可自由选择源UV和目标UV通道
- 支持批量处理多个选中的物体
- 支持批量处理多张贴图（BaseColor, Normal, Roughness等）
- 自定义输出分辨率（512~8192）
- 多种输出格式（PNG/TIFF/JPEG/TGA/BMP/EXR）
- 边缘扩展（Margin）避免接缝
- 完成后自动预览结果

使用方法：
1. 安装：编辑 > 偏好设置 > 插件 > 安装，选择此文件
2. 启用：搜索 "1U to 2U" 并勾选启用
3. 打开面板：3D视图侧边栏(N) > "1U to 2U" 标签页
4. 选择模型，设置参数，点击"开始转烘"

作者：123木头人
日期：2026-03-30
版本：1.3 (独立UV传递、打开输出目录)
"""

bl_info = {
    "name": "1U to 2U - UV贴图转烘工具",
    "author": "AI Assistant",
    "version": (1, 3, 0),
    "blender": (2, 83, 0),
    "location": "View3D > Sidebar > 1U to 2U",
    "description": "将UV0的贴图转烘到UV1上，支持单模型双UV和双模型模式，独立UV传递",
    "category": "UV",
}

import bpy
import os
import time
from bpy.props import (
    StringProperty,
    EnumProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
    IntVectorProperty,
)
from bpy.types import (
    Operator,
    Panel,
    PropertyGroup,
    UIList,
)


# ============================================================
# 工具函数
# ============================================================

def get_uv_layers(obj):
    """获取物体的所有UV层名称"""
    if obj and obj.type == 'MESH' and obj.data.uv_layers:
        return [(uv.name, uv.name, f"UV通道: {uv.name}") for uv in obj.data.uv_layers]
    return []


def get_uv_layers_callback(self, context):
    """动态获取UV层列表的回调"""
    obj = context.active_object
    items = get_uv_layers(obj)
    if not items:
        return [("NONE", "无UV", "没有可用的UV通道")]
    return items


def get_mesh_objects_callback(self, context):
    """获取场景中所有网格物体（用于双模型模式的源/目标选择器）"""
    items = []
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            items.append((obj.name, obj.name, f"网格物体: {obj.name}"))
    if not items:
        items.append(("NONE", "无网格物体", "场景中没有网格物体"))
    return items


def get_source_obj_uv_callback(self, context):
    """动态获取双模型模式下源模型的UV层列表"""
    props = context.scene.uv_transfer_props
    src_obj = bpy.data.objects.get(props.dual_source_object) if props.dual_source_object else None
    if src_obj and src_obj.type == 'MESH' and src_obj.data.uv_layers:
        return [(uv.name, uv.name, f"UV通道: {uv.name}") for uv in src_obj.data.uv_layers]
    return [("NONE", "无UV", "源模型没有UV通道")]


def get_target_obj_uv_callback(self, context):
    """动态获取双模型模式下目标模型的UV层列表"""
    props = context.scene.uv_transfer_props
    tgt_obj = bpy.data.objects.get(props.dual_target_object) if props.dual_target_object else None
    if tgt_obj and tgt_obj.type == 'MESH' and tgt_obj.data.uv_layers:
        return [(uv.name, uv.name, f"UV通道: {uv.name}") for uv in tgt_obj.data.uv_layers]
    return [("NONE", "无UV", "目标模型没有UV通道")]


def check_topology_match(src_obj, tgt_obj):
    """
    检查两个模型的拓扑是否一致。

    Returns:
        (bool, str): (是否一致, 详细信息)
    """
    src_mesh = src_obj.data
    tgt_mesh = tgt_obj.data

    src_verts = len(src_mesh.vertices)
    tgt_verts = len(tgt_mesh.vertices)
    src_faces = len(src_mesh.polygons)
    tgt_faces = len(tgt_mesh.polygons)
    src_loops = len(src_mesh.loops)
    tgt_loops = len(tgt_mesh.loops)

    info_lines = []
    info_lines.append(f"源 [{src_obj.name}]: 顶点={src_verts}, 面={src_faces}, Loop={src_loops}")
    info_lines.append(f"目标 [{tgt_obj.name}]: 顶点={tgt_verts}, 面={tgt_faces}, Loop={tgt_loops}")

    match = True
    if src_verts != tgt_verts:
        info_lines.append(f"✘ 顶点数不匹配: {src_verts} vs {tgt_verts}")
        match = False
    if src_faces != tgt_faces:
        info_lines.append(f"✘ 面数不匹配: {src_faces} vs {tgt_faces}")
        match = False
    if src_loops != tgt_loops:
        info_lines.append(f"✘ Loop数不匹配: {src_loops} vs {tgt_loops}")
        match = False

    if match:
        for i, (sp, tp) in enumerate(zip(src_mesh.polygons, tgt_mesh.polygons)):
            if sp.loop_total != tp.loop_total:
                info_lines.append(f"✘ 面 {i} 的顶点数不同: {sp.loop_total} vs {tp.loop_total}")
                match = False
                break

        if match:
            info_lines.append("✔ 拓扑完全一致，可以拷贝UV")

    return match, "\n".join(info_lines)


def copy_uv_between_objects(src_obj, tgt_obj, src_uv_name, tgt_uv_name):
    """
    将源模型的UV数据逐loop拷贝到目标模型。

    Returns:
        (bool, str): (是否成功, 信息)
    """
    src_mesh = src_obj.data
    tgt_mesh = tgt_obj.data

    if src_uv_name not in src_mesh.uv_layers:
        return False, f"源模型没有UV层: {src_uv_name}"

    src_uv_layer = src_mesh.uv_layers[src_uv_name]

    # 在目标模型上创建或获取目标UV层
    if tgt_uv_name in tgt_mesh.uv_layers:
        tgt_uv_layer = tgt_mesh.uv_layers[tgt_uv_name]
    else:
        tgt_uv_layer = tgt_mesh.uv_layers.new(name=tgt_uv_name)

    if tgt_uv_layer is None:
        return False, f"无法在目标模型上创建UV层: {tgt_uv_name}"

    src_uv_data = src_uv_layer.data
    tgt_uv_data = tgt_uv_layer.data

    loop_count = len(src_uv_data)
    if loop_count != len(tgt_uv_data):
        return False, f"UV数据长度不匹配: 源={loop_count}, 目标={len(tgt_uv_data)}"

    # 批量拷贝（foreach_get/foreach_set 高效）
    uv_coords = [0.0] * (loop_count * 2)
    src_uv_data.foreach_get("uv", uv_coords)
    tgt_uv_data.foreach_set("uv", uv_coords)

    tgt_mesh.update()

    return True, f"成功拷贝 {loop_count} 个UV坐标"


def log_message(context, message, level="INFO"):
    """添加日志消息到属性中"""
    props = context.scene.uv_transfer_props
    # 添加到日志列表
    item = props.log_items.add()
    item.message = f"[{level}] {message}"
    item.level = level
    # 自动滚动到最新
    props.log_index = len(props.log_items) - 1
    # 同时打印到控制台
    print(f"[1U2U][{level}] {message}")


# ============================================================
# 贴图列表相关 PropertyGroup
# ============================================================

class UV_TRANSFER_TextureItem(PropertyGroup):
    """贴图列表项"""
    filepath: StringProperty(
        name="贴图路径",
        description="源贴图文件路径",
        subtype='FILE_PATH',
        default=""
    )
    enabled: BoolProperty(
        name="启用",
        description="是否处理此贴图",
        default=True
    )
    name: StringProperty(
        name="名称",
        description="贴图名称（用于显示）",
        default=""
    )
    status: StringProperty(
        name="状态",
        description="处理状态",
        default="待处理"
    )
    is_data: BoolProperty(
        name="非颜色数据",
        description="该贴图是否为非颜色数据（如Normal Map、Roughness等）。\n"
                    "勾选后将使用Non-Color空间处理，避免gamma校正",
        default=False
    )


class UV_TRANSFER_LogItem(PropertyGroup):
    """日志列表项"""
    message: StringProperty(name="消息", default="")
    level: StringProperty(name="级别", default="INFO")


# ============================================================
# 贴图列表 UIList
# ============================================================

class UV_TRANSFER_UL_TextureList(UIList):
    """贴图文件列表UI"""
    bl_idname = "UV_TRANSFER_UL_TextureList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")

            # 显示文件名
            if item.filepath:
                filename = os.path.basename(bpy.path.abspath(item.filepath))
                row.label(text=filename, icon='TEXTURE')
            else:
                row.label(text="(未选择)", icon='ERROR')

            # 非颜色数据标记
            row.prop(item, "is_data", text="Data", toggle=True)

            # 状态标志
            status_icon = 'CHECKBOX_DEHLT'
            if item.status == "完成":
                status_icon = 'CHECKMARK'
            elif item.status == "失败":
                status_icon = 'ERROR'
            elif item.status == "处理中":
                status_icon = 'TIME'
            row.label(text="", icon=status_icon)

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='TEXTURE')


# ============================================================
# 主属性组
# ============================================================

class UV_TRANSFER_Properties(PropertyGroup):
    """UV转烘工具属性"""

    # ---- 工作模式 ----
    work_mode: EnumProperty(
        name="工作模式",
        description="选择转烘模式",
        items=[
            ("SINGLE", "单模型", "同一模型上两套UV之间转烘"),
            ("DUAL", "双模型", "从源模型拷贝UV到目标模型后转烘（需拓扑一致）"),
        ],
        default="SINGLE",
    )

    # ---- 单模型模式：源UV / 目标UV ----
    # 源UV通道
    source_uv: EnumProperty(
        name="源UV",
        description="源贴图使用的UV通道",
        items=get_uv_layers_callback,
    )

    # 目标UV通道
    target_uv: EnumProperty(
        name="目标UV",
        description="转烘目标UV通道",
        items=get_uv_layers_callback,
    )

    # ---- 双模型模式属性 ----
    dual_source_object: EnumProperty(
        name="源模型",
        description="提供UV和贴图的源模型",
        items=get_mesh_objects_callback,
    )

    dual_target_object: EnumProperty(
        name="目标模型",
        description="接收转烘结果的目标模型",
        items=get_mesh_objects_callback,
    )

    dual_source_uv: EnumProperty(
        name="源模型UV",
        description="源模型上的UV层（贴图对应的UV）",
        items=get_source_obj_uv_callback,
    )

    dual_target_uv: EnumProperty(
        name="目标模型UV",
        description="目标模型上要烘焙到的UV层",
        items=get_target_obj_uv_callback,
    )

    # 传递UV目标层名（独立UV传递时使用）
    transfer_uv_name: StringProperty(
        name="目标UV层名",
        description="传递到目标模型上的UV层名称",
        default="TransferredUV",
    )

    # 保留临时UV层
    keep_temp_uv: BoolProperty(
        name="保留临时UV层",
        description="转烘完成后是否保留拷贝过来的临时UV层（默认清理）",
        default=False,
    )

    # 拓扑检测结果
    topo_check_result: StringProperty(
        name="拓扑检测结果",
        default="",
    )
    topo_match: BoolProperty(
        name="拓扑匹配",
        default=False,
    )

    # 输出分辨率
    resolution: EnumProperty(
        name="输出分辨率",
        description="输出贴图的分辨率",
        items=[
            ("512", "512 x 512", ""),
            ("1024", "1024 x 1024", ""),
            ("2048", "2048 x 2048", ""),
            ("4096", "4096 x 4096", ""),
            ("8192", "8192 x 8192", ""),
        ],
        default="2048",
    )

    # 输出格式
    output_format: EnumProperty(
        name="输出格式",
        description="输出贴图的格式",
        items=[
            ("PNG", "PNG", "PNG格式（无损，支持Alpha）"),
            ("TIFF", "TIFF", "TIFF格式（无损）"),
            ("JPEG", "JPEG", "JPEG格式（有损，不支持Alpha）"),
            ("TARGA", "TGA", "TGA格式（支持Alpha）"),
            ("BMP", "BMP", "BMP格式"),
            ("OPEN_EXR", "EXR", "OpenEXR格式（HDR）"),
        ],
        default="PNG",
    )

    # 输出目录
    output_dir: StringProperty(
        name="输出目录",
        description="输出贴图的保存目录（留空则保存到源贴图同目录）",
        subtype='DIR_PATH',
        default="",
    )

    # 输出文件名后缀
    output_suffix: StringProperty(
        name="输出后缀",
        description="输出文件名后缀",
        default="_UV1",
    )

    # 边缘扩展（Margin）
    margin: IntProperty(
        name="边缘扩展",
        description="烘焙时的边缘扩展像素数（Margin），防止UV接缝处出现间隙",
        default=16,
        min=0,
        max=128,
        subtype='PIXEL',
    )

    # 是否启用边缘扩展
    use_margin: BoolProperty(
        name="启用边缘扩展",
        description="烘焙时进行边缘扩展，减少UV接缝可见度",
        default=True,
    )

    # 自动预览
    auto_preview: BoolProperty(
        name="完成后自动预览",
        description="转烘完成后自动将结果贴图应用到模型上预览",
        default=True,
    )

    # 是否批量处理所有选中物体
    batch_objects: BoolProperty(
        name="批量处理选中物体",
        description="对所有选中的网格物体执行转烘",
        default=False,
    )

    # 采样数
    samples: IntProperty(
        name="采样数",
        description="Cycles烘焙采样数（越高质量越好，速度越慢）",
        default=1,
        min=1,
        max=128,
    )

    # 贴图文件列表
    texture_items: CollectionProperty(type=UV_TRANSFER_TextureItem)
    texture_index: IntProperty(name="贴图索引", default=0)

    # 日志
    log_items: CollectionProperty(type=UV_TRANSFER_LogItem)
    log_index: IntProperty(name="日志索引", default=0)

    # 进度
    progress: IntProperty(
        name="进度",
        default=0,
        min=0,
        max=100,
        subtype='PERCENTAGE',
    )
    is_baking: BoolProperty(
        name="正在烘焙",
        default=False,
    )


# ============================================================
# 操作器：添加/删除贴图
# ============================================================

class UV_TRANSFER_OT_AddTexture(Operator):
    """添加贴图到列表"""
    bl_idname = "uv_transfer.add_texture"
    bl_label = "添加贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tga;*.tiff;*.tif;*.bmp;*.exr",
        options={'HIDDEN'},
    )

    # 支持多选
    files: CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
    )
    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        props = context.scene.uv_transfer_props
        if self.files:
            for f in self.files:
                full_path = os.path.join(self.directory, f.name)
                item = props.texture_items.add()
                item.filepath = full_path
                item.name = os.path.splitext(f.name)[0]
                item.status = "待处理"
            log_message(context, f"已添加 {len(self.files)} 张贴图", "INFO")
        else:
            item = props.texture_items.add()
            item.filepath = self.filepath
            item.name = os.path.splitext(os.path.basename(self.filepath))[0]
            item.status = "待处理"
            log_message(context, f"已添加贴图: {item.name}", "INFO")

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class UV_TRANSFER_OT_RemoveTexture(Operator):
    """从列表中移除选中的贴图"""
    bl_idname = "uv_transfer.remove_texture"
    bl_label = "移除贴图"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.uv_transfer_props
        if props.texture_items and 0 <= props.texture_index < len(props.texture_items):
            name = props.texture_items[props.texture_index].name
            props.texture_items.remove(props.texture_index)
            props.texture_index = min(props.texture_index, len(props.texture_items) - 1)
            log_message(context, f"已移除贴图: {name}", "INFO")
        return {'FINISHED'}


class UV_TRANSFER_OT_ClearTextures(Operator):
    """清空贴图列表"""
    bl_idname = "uv_transfer.clear_textures"
    bl_label = "清空列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.uv_transfer_props
        props.texture_items.clear()
        props.texture_index = 0
        log_message(context, "已清空贴图列表", "INFO")
        return {'FINISHED'}


class UV_TRANSFER_OT_ClearLog(Operator):
    """清空日志"""
    bl_idname = "uv_transfer.clear_log"
    bl_label = "清空日志"

    def execute(self, context):
        props = context.scene.uv_transfer_props
        props.log_items.clear()
        props.log_index = 0
        return {'FINISHED'}


class UV_TRANSFER_OT_CheckTopology(Operator):
    """检测双模型模式下源模型和目标模型的拓扑一致性"""
    bl_idname = "uv_transfer.check_topology"
    bl_label = "检测拓扑一致性"
    bl_description = "检查源模型和目标模型的拓扑是否匹配"

    def execute(self, context):
        props = context.scene.uv_transfer_props

        src_obj = bpy.data.objects.get(props.dual_source_object)
        tgt_obj = bpy.data.objects.get(props.dual_target_object)

        if not src_obj or src_obj.type != 'MESH':
            props.topo_check_result = "错误：无效的源模型"
            props.topo_match = False
            self.report({'ERROR'}, "无效的源模型")
            return {'CANCELLED'}

        if not tgt_obj or tgt_obj.type != 'MESH':
            props.topo_check_result = "错误：无效的目标模型"
            props.topo_match = False
            self.report({'ERROR'}, "无效的目标模型")
            return {'CANCELLED'}

        if src_obj == tgt_obj:
            props.topo_check_result = "错误：源模型和目标模型不能是同一个物体"
            props.topo_match = False
            self.report({'ERROR'}, "源模型和目标模型不能是同一个物体")
            return {'CANCELLED'}

        match, info = check_topology_match(src_obj, tgt_obj)
        props.topo_check_result = info
        props.topo_match = match

        if match:
            self.report({'INFO'}, "拓扑一致，可以拷贝UV并转烘")
            log_message(context, f"拓扑检测通过: {src_obj.name} ↔ {tgt_obj.name}", "SUCCESS")
        else:
            self.report({'WARNING'}, "拓扑不一致，无法使用双模型模式")
            log_message(context, f"拓扑不一致: {src_obj.name} ↔ {tgt_obj.name}", "WARNING")

        return {'FINISHED'}


class UV_TRANSFER_OT_SetFromActive(Operator):
    """用当前激活物体设为源/目标模型"""
    bl_idname = "uv_transfer.set_from_active"
    bl_label = "使用当前激活物体"
    bl_options = {'REGISTER'}

    target_prop: StringProperty(default="source")  # "source" 或 "target"

    def execute(self, context):
        props = context.scene.uv_transfer_props
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "当前没有激活的网格物体")
            return {'CANCELLED'}

        if self.target_prop == "source":
            props.dual_source_object = obj.name
            self.report({'INFO'}, f"源模型已设为: {obj.name}")
        else:
            props.dual_target_object = obj.name
            self.report({'INFO'}, f"目标模型已设为: {obj.name}")

        return {'FINISHED'}


class UV_TRANSFER_OT_TransferUV(Operator):
    """独立执行UV传递：将源模型的UV拷贝到目标模型上"""
    bl_idname = "uv_transfer.transfer_uv"
    bl_label = "传递UV"
    bl_description = "将源模型的UV拷贝到目标模型（不执行转烘）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.uv_transfer_props

        src_obj = bpy.data.objects.get(props.dual_source_object)
        tgt_obj = bpy.data.objects.get(props.dual_target_object)

        if not src_obj or src_obj.type != 'MESH':
            self.report({'ERROR'}, "无效的源模型")
            return {'CANCELLED'}

        if not tgt_obj or tgt_obj.type != 'MESH':
            self.report({'ERROR'}, "无效的目标模型")
            return {'CANCELLED'}

        if src_obj == tgt_obj:
            self.report({'ERROR'}, "源模型和目标模型不能是同一个物体")
            return {'CANCELLED'}

        # 拓扑检测
        match, info = check_topology_match(src_obj, tgt_obj)
        if not match:
            self.report({'ERROR'}, "拓扑不一致，无法传递UV")
            log_message(context, f"拓扑不一致:\n{info}", "ERROR")
            return {'CANCELLED'}

        src_uv = props.dual_source_uv
        if src_uv == "NONE":
            self.report({'ERROR'}, "源模型没有可用的UV层")
            return {'CANCELLED'}

        tgt_uv_name = props.transfer_uv_name.strip()
        if not tgt_uv_name:
            tgt_uv_name = src_uv  # 如果没有指定名称，使用源UV同名

        log_message(context, f"开始独立UV传递...", "INFO")
        log_message(context, f"源: {src_obj.name} [{src_uv}] → 目标: {tgt_obj.name} [{tgt_uv_name}]", "INFO")

        success, msg = copy_uv_between_objects(src_obj, tgt_obj, src_uv, tgt_uv_name)
        if not success:
            self.report({'ERROR'}, f"UV传递失败: {msg}")
            log_message(context, f"UV传递失败: {msg}", "ERROR")
            return {'CANCELLED'}

        log_message(context, f"UV传递成功: {msg}", "SUCCESS")
        self.report({'INFO'}, f"UV传递完成: {src_obj.name} → {tgt_obj.name} [{tgt_uv_name}]")
        return {'FINISHED'}

    @classmethod
    def poll(cls, context):
        props = context.scene.uv_transfer_props
        src_obj = bpy.data.objects.get(props.dual_source_object) if props.dual_source_object else None
        tgt_obj = bpy.data.objects.get(props.dual_target_object) if props.dual_target_object else None
        return (
            src_obj is not None and src_obj.type == 'MESH'
            and tgt_obj is not None and tgt_obj.type == 'MESH'
            and src_obj != tgt_obj
        )


class UV_TRANSFER_OT_OpenOutputDir(Operator):
    """打开输出目录"""
    bl_idname = "uv_transfer.open_output_dir"
    bl_label = "打开输出目录"
    bl_description = "在文件管理器中打开贴图输出目录"

    def execute(self, context):
        props = context.scene.uv_transfer_props
        import subprocess
        import platform

        # 确定输出目录
        output_dir = ""
        if props.output_dir:
            output_dir = bpy.path.abspath(props.output_dir)

        if not output_dir or not os.path.isdir(output_dir):
            # 如果输出目录为空或不存在，尝试从贴图列表获取
            enabled_textures = [t for t in props.texture_items if t.enabled and t.filepath]
            if enabled_textures:
                first_tex_path = bpy.path.abspath(enabled_textures[0].filepath)
                output_dir = os.path.dirname(first_tex_path)

        if not output_dir or not os.path.isdir(output_dir):
            output_dir = os.path.expanduser("~")
            log_message(context, f"未设置输出目录，将打开用户主目录", "WARNING")

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(output_dir)
            elif system == "Darwin":
                subprocess.Popen(["open", output_dir])
            else:
                subprocess.Popen(["xdg-open", output_dir])

            log_message(context, f"已打开目录: {output_dir}", "INFO")
            self.report({'INFO'}, f"已打开: {output_dir}")
        except Exception as e:
            log_message(context, f"打开目录失败: {str(e)}", "ERROR")
            self.report({'ERROR'}, f"打开目录失败: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}


# ============================================================
# 核心操作器：执行转烘
# ============================================================

class UV_TRANSFER_OT_Bake(Operator):
    """执行UV贴图转烘"""
    bl_idname = "uv_transfer.bake"
    bl_label = "开始转烘"
    bl_description = "将源UV通道的贴图转烘到目标UV通道"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.uv_transfer_props
        props.is_baking = True
        props.progress = 0

        try:
            result = self._do_bake(context)
            return result
        except Exception as e:
            log_message(context, f"错误: {str(e)}", "ERROR")
            import traceback
            log_message(context, traceback.format_exc(), "ERROR")
            self.report({'ERROR'}, f"转烘失败: {str(e)}")
            return {'CANCELLED'}
        finally:
            props.is_baking = False

    def _do_bake(self, context):
        props = context.scene.uv_transfer_props

        # ---- 验证 ----
        log_message(context, "=" * 50, "INFO")
        log_message(context, "开始UV贴图转烘...", "INFO")

        is_dual_mode = (props.work_mode == 'DUAL')

        if is_dual_mode:
            log_message(context, "模式: 双模型 (跨模型UV转烘)", "INFO")
        else:
            log_message(context, "模式: 单模型 (同模型双UV转烘)", "INFO")

        # ---- 获取物体和UV信息 ----
        temp_uv_name = None  # 双模型模式下创建的临时UV层名称
        cleanup_temp_uv_objects = []  # 需要清理临时UV的物体列表

        if is_dual_mode:
            # 双模型模式验证
            src_obj = bpy.data.objects.get(props.dual_source_object)
            tgt_obj = bpy.data.objects.get(props.dual_target_object)

            if not src_obj or src_obj.type != 'MESH':
                self.report({'ERROR'}, "无效的源模型")
                log_message(context, "错误：无效的源模型", "ERROR")
                return {'CANCELLED'}

            if not tgt_obj or tgt_obj.type != 'MESH':
                self.report({'ERROR'}, "无效的目标模型")
                log_message(context, "错误：无效的目标模型", "ERROR")
                return {'CANCELLED'}

            if src_obj == tgt_obj:
                self.report({'ERROR'}, "源模型和目标模型不能是同一个物体")
                log_message(context, "错误：源模型和目标模型不能是同一个物体", "ERROR")
                return {'CANCELLED'}

            dual_src_uv = props.dual_source_uv
            dual_tgt_uv = props.dual_target_uv

            if dual_src_uv == "NONE":
                self.report({'ERROR'}, "源模型没有可用的UV层")
                log_message(context, "错误：源模型没有可用的UV层", "ERROR")
                return {'CANCELLED'}

            if dual_tgt_uv == "NONE":
                self.report({'ERROR'}, "目标模型没有可用的UV层")
                log_message(context, "错误：目标模型没有可用的UV层", "ERROR")
                return {'CANCELLED'}

            # 拓扑检测
            match, info = check_topology_match(src_obj, tgt_obj)
            if not match:
                self.report({'ERROR'}, "拓扑不一致，无法使用双模型模式")
                log_message(context, f"拓扑不一致:\n{info}", "ERROR")
                return {'CANCELLED'}

            log_message(context, f"源模型: {src_obj.name} (UV: {dual_src_uv})", "INFO")
            log_message(context, f"目标模型: {tgt_obj.name} (UV: {dual_tgt_uv})", "INFO")

            # 将源模型的UV拷贝到目标模型上作为临时UV层
            temp_uv_name = f"_1u2u_temp_{dual_src_uv}"
            log_message(context, f"正在拷贝源UV到目标模型 (临时层: {temp_uv_name})...", "INFO")

            success, msg = copy_uv_between_objects(src_obj, tgt_obj, dual_src_uv, temp_uv_name)
            if not success:
                self.report({'ERROR'}, f"UV拷贝失败: {msg}")
                log_message(context, f"UV拷贝失败: {msg}", "ERROR")
                return {'CANCELLED'}
            log_message(context, msg, "SUCCESS")
            cleanup_temp_uv_objects.append(tgt_obj)

            # 双模型模式下：在目标模型上执行转烘
            # 源UV = 拷贝过来的临时UV层，目标UV = 目标模型上的目标UV
            objects = [tgt_obj]
            source_uv = temp_uv_name
            target_uv = dual_tgt_uv
        else:
            # 单模型模式（原有逻辑）
            if props.batch_objects:
                objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
            else:
                if not context.active_object or context.active_object.type != 'MESH':
                    self.report({'ERROR'}, "请先选择一个网格物体")
                    log_message(context, "错误：请先选择一个网格物体", "ERROR")
                    return {'CANCELLED'}
                objects = [context.active_object]

            if not objects:
                self.report({'ERROR'}, "没有选择有效的网格物体")
                log_message(context, "错误：没有选择有效的网格物体", "ERROR")
                return {'CANCELLED'}

            source_uv = props.source_uv
            target_uv = props.target_uv

        # 验证UV通道
        if source_uv == "NONE" or target_uv == "NONE":
            self.report({'ERROR'}, "模型没有足够的UV通道")
            log_message(context, "错误：模型没有足够的UV通道", "ERROR")
            return {'CANCELLED'}

        if source_uv == target_uv:
            self.report({'ERROR'}, "源UV和目标UV不能相同")
            log_message(context, "错误：源UV和目标UV不能相同", "ERROR")
            return {'CANCELLED'}

        # 验证贴图列表
        enabled_textures = [t for t in props.texture_items if t.enabled and t.filepath]
        if not enabled_textures:
            self.report({'ERROR'}, "请至少添加一张源贴图")
            log_message(context, "错误：请至少添加一张源贴图", "ERROR")
            return {'CANCELLED'}

        # 验证文件存在
        for tex_item in enabled_textures:
            abs_path = bpy.path.abspath(tex_item.filepath)
            if not os.path.exists(abs_path):
                self.report({'ERROR'}, f"贴图文件不存在: {abs_path}")
                log_message(context, f"错误：贴图文件不存在: {abs_path}", "ERROR")
                return {'CANCELLED'}

        resolution = int(props.resolution)
        margin = props.margin if props.use_margin else 0
        output_format = props.output_format
        samples = props.samples

        log_message(context, f"物体数量: {len(objects)}", "INFO")
        log_message(context, f"贴图数量: {len(enabled_textures)}", "INFO")
        log_message(context, f"源UV: {source_uv} -> 目标UV: {target_uv}", "INFO")
        log_message(context, f"分辨率: {resolution}x{resolution}", "INFO")
        log_message(context, f"格式: {output_format}, 采样: {samples}", "INFO")
        log_message(context, f"边缘扩展: {margin} px", "INFO")

        # ---- 保存当前状态 ----
        original_engine = context.scene.render.engine
        original_active = context.view_layer.objects.active
        original_samples = 1
        if hasattr(context.scene, 'cycles'):
            original_samples = context.scene.cycles.samples

        # 保存颜色管理设置
        original_view_transform = context.scene.view_settings.view_transform
        original_look = context.scene.view_settings.look
        original_exposure = context.scene.view_settings.exposure
        original_gamma = context.scene.view_settings.gamma

        # 格式后缀映射
        format_ext_map = {
            "PNG": ".png",
            "TIFF": ".tiff",
            "JPEG": ".jpg",
            "TARGA": ".tga",
            "BMP": ".bmp",
            "OPEN_EXR": ".exr",
        }

        total_tasks = len(objects) * len(enabled_textures)
        completed = 0
        success_count = 0
        fail_count = 0

        try:
            # ---- 切换到 Cycles 引擎 ----
            context.scene.render.engine = 'CYCLES'
            context.scene.cycles.samples = samples
            # 使用 CPU 以兼容所有环境（用户可自行切换 GPU）
            context.scene.cycles.device = 'CPU'

            # 设置烘焙类型为 Emit（发光）— 适合颜色贴图的平面烘焙
            context.scene.cycles.bake_type = 'EMIT'

            # **关键修复**：将场景颜色管理设为 Raw，避免烘焙时的色调映射
            # 这确保 Cycles 烘焙输出的是未经视图变换的原始线性数据
            try:
                context.scene.view_settings.view_transform = 'Raw'
            except TypeError:
                # 某些 Blender 版本中可能叫 'Standard'
                try:
                    context.scene.view_settings.view_transform = 'Standard'
                except TypeError:
                    log_message(context, "警告：无法设置Raw视图变换", "WARNING")
            context.scene.view_settings.look = 'None'
            context.scene.view_settings.exposure = 0.0
            context.scene.view_settings.gamma = 1.0

            for obj in objects:
                log_message(context, f"--- 处理物体: {obj.name} ---", "INFO")

                # 验证该物体有对应的UV层
                mesh = obj.data
                if source_uv not in mesh.uv_layers:
                    log_message(context, f"警告：物体 {obj.name} 没有UV层 '{source_uv}'，跳过", "WARNING")
                    for tex_item in enabled_textures:
                        tex_item.status = "跳过"
                        completed += 1
                    continue
                if target_uv not in mesh.uv_layers:
                    log_message(context, f"警告：物体 {obj.name} 没有UV层 '{target_uv}'，跳过", "WARNING")
                    for tex_item in enabled_textures:
                        tex_item.status = "跳过"
                        completed += 1
                    continue

                # 选中并激活该物体
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                context.view_layer.objects.active = obj

                for tex_item in enabled_textures:
                    tex_item.status = "处理中"
                    abs_tex_path = bpy.path.abspath(tex_item.filepath)
                    tex_name = os.path.splitext(os.path.basename(abs_tex_path))[0]
                    log_message(context, f"处理贴图: {tex_name}", "INFO")

                    try:
                        # 执行单次转烘
                        output_path = self._bake_single(
                            context, obj, abs_tex_path,
                            source_uv, target_uv,
                            resolution, margin, output_format,
                            format_ext_map, tex_name,
                            is_data=tex_item.is_data,
                        )

                        tex_item.status = "完成"
                        success_count += 1
                        log_message(context, f"成功: {os.path.basename(output_path)}", "SUCCESS")

                        # 自动预览（仅最后一张贴图）
                        if props.auto_preview:
                            self._apply_preview(context, obj, output_path, target_uv)

                    except Exception as e:
                        tex_item.status = "失败"
                        fail_count += 1
                        log_message(context, f"失败: {str(e)}", "ERROR")

                    completed += 1
                    props.progress = int(100 * completed / total_tasks)

        finally:
            # ---- 恢复原始状态 ----
            context.scene.render.engine = original_engine
            if hasattr(context.scene, 'cycles'):
                context.scene.cycles.samples = original_samples

            # 恢复颜色管理设置
            try:
                context.scene.view_settings.view_transform = original_view_transform
                context.scene.view_settings.look = original_look
                context.scene.view_settings.exposure = original_exposure
                context.scene.view_settings.gamma = original_gamma
            except Exception:
                pass

            if original_active:
                try:
                    context.view_layer.objects.active = original_active
                except Exception:
                    pass

            # 双模型模式：根据设置决定是否清理临时UV层
            if temp_uv_name:
                if props.keep_temp_uv:
                    for cleanup_obj in cleanup_temp_uv_objects:
                        log_message(context, f"已保留临时UV层: {temp_uv_name} (物体: {cleanup_obj.name})", "INFO")
                else:
                    for cleanup_obj in cleanup_temp_uv_objects:
                        mesh = cleanup_obj.data
                        if temp_uv_name in mesh.uv_layers:
                            mesh.uv_layers.remove(mesh.uv_layers[temp_uv_name])
                            log_message(context, f"已清理临时UV层: {temp_uv_name} (物体: {cleanup_obj.name})", "INFO")

        # ---- 报告结果 ----
        props.progress = 100
        log_message(context, "=" * 50, "INFO")
        log_message(context, f"转烘完成！成功: {success_count}, 失败: {fail_count}", "SUCCESS")

        if fail_count > 0:
            self.report({'WARNING'}, f"转烘完成（{success_count}成功 / {fail_count}失败）")
        else:
            self.report({'INFO'}, f"转烘完成！共 {success_count} 张贴图")

        return {'FINISHED'}

    def _bake_single(self, context, obj, source_tex_path, source_uv, target_uv,
                     resolution, margin, output_format, format_ext_map, tex_name,
                     is_data=False):
        """
        执行单个贴图的转烘。

        核心流程：
        1. 保存原始材质
        2. 创建临时材质：Image Texture (源贴图, 使用源UV) → Emission → Material Output
        3. 创建目标烘焙图像，挂在一个额外的 Image Texture 节点上并设为 Active
        4. 设置活动 UV 为目标 UV
        5. Cycles Bake (Emit)
        6. 保存结果图像
        7. 恢复原始材质

        颜色空间策略：
        - 颜色贴图(BaseColor等)：源贴图 sRGB → 目标图像 sRGB
        - 数据贴图(Normal/Roughness等)：源贴图 Non-Color → 目标图像 Non-Color
        - 使用 image.save() 而非 save_render()，避免场景颜色管理的二次gamma编码
        """
        mesh = obj.data

        # --- 保存原始状态 ---
        original_materials = [slot.material for slot in obj.material_slots]
        original_active_uv = mesh.uv_layers.active.name if mesh.uv_layers.active else None

        # --- 确定颜色空间 ---
        # Non-Color 的名称在不同 Blender 版本可能是 "Non-Color" 或 "Non-Color Data"
        # 我们尝试检测可用的名称
        non_color_name = "Non-Color"

        if is_data:
            src_colorspace = non_color_name
            log_message(context, f"  颜色空间: Non-Color (数据贴图)", "INFO")
        else:
            src_colorspace = "sRGB"
            log_message(context, f"  颜色空间: sRGB (颜色贴图)", "INFO")

        # --- 加载源贴图到 Blender ---
        # 检查是否已有同名图像
        src_img_name = f"_1u2u_src_{tex_name}"
        if src_img_name in bpy.data.images:
            src_img = bpy.data.images[src_img_name]
            src_img.filepath = source_tex_path
            src_img.reload()
        else:
            src_img = bpy.data.images.load(source_tex_path)
            src_img.name = src_img_name

        # 设置源贴图的颜色空间
        try:
            src_img.colorspace_settings.name = src_colorspace
        except TypeError:
            # 如果 "Non-Color" 不被支持，尝试 "Non-Color Data"（旧版本Blender）
            if is_data:
                try:
                    src_img.colorspace_settings.name = "Non-Color Data"
                except TypeError:
                    log_message(context, "  警告：无法设置Non-Color颜色空间，使用默认", "WARNING")

        # --- 创建目标烘焙图像 ---
        props = context.scene.uv_transfer_props
        bake_img_name = f"_1u2u_bake_{tex_name}_{obj.name}"
        if bake_img_name in bpy.data.images:
            bake_img = bpy.data.images[bake_img_name]
            # 重新生成尺寸
            if bake_img.size[0] != resolution or bake_img.size[1] != resolution:
                bpy.data.images.remove(bake_img)
                bake_img = bpy.data.images.new(
                    bake_img_name, resolution, resolution,
                    alpha=(output_format not in ('JPEG', 'BMP')),
                    float_buffer=(output_format == 'OPEN_EXR'),
                )
            else:
                # 清空现有像素
                bake_img.pixels[:] = [0.0] * (resolution * resolution * 4)
        else:
            bake_img = bpy.data.images.new(
                bake_img_name, resolution, resolution,
                alpha=(output_format not in ('JPEG', 'BMP')),
                float_buffer=(output_format == 'OPEN_EXR'),
            )

        # **关键修复**：设置目标图像的颜色空间与源贴图一致
        # 这样 Cycles 烘焙写入的线性数据在保存时会正确编码
        try:
            bake_img.colorspace_settings.name = src_colorspace
        except TypeError:
            if is_data:
                try:
                    bake_img.colorspace_settings.name = "Non-Color Data"
                except TypeError:
                    pass

        try:
            # --- 创建临时材质 ---
            temp_mat = bpy.data.materials.new(name="_1u2u_temp_material")
            temp_mat.use_nodes = True
            nodes = temp_mat.node_tree.nodes
            links = temp_mat.node_tree.links

            # 清空默认节点
            nodes.clear()

            # Material Output
            output_node = nodes.new(type='ShaderNodeOutputMaterial')
            output_node.location = (400, 0)

            # Emission 节点（Cycles Bake Emit 模式会烘焙 Emission 的颜色）
            emission_node = nodes.new(type='ShaderNodeEmission')
            emission_node.location = (200, 0)
            links.new(emission_node.outputs['Emission'], output_node.inputs['Surface'])

            # 源贴图 Image Texture 节点
            src_tex_node = nodes.new(type='ShaderNodeTexImage')
            src_tex_node.location = (-200, 0)
            src_tex_node.image = src_img
            src_tex_node.interpolation = 'Linear'
            links.new(src_tex_node.outputs['Color'], emission_node.inputs['Color'])

            # UV Map 节点 → 使用源UV采样
            uv_map_node = nodes.new(type='ShaderNodeUVMap')
            uv_map_node.location = (-500, 0)
            uv_map_node.uv_map = source_uv
            links.new(uv_map_node.outputs['UV'], src_tex_node.inputs['Vector'])

            # 目标烘焙图像节点（仅用于指定烘焙输出，不连接到任何东西）
            bake_tex_node = nodes.new(type='ShaderNodeTexImage')
            bake_tex_node.location = (-200, -300)
            bake_tex_node.image = bake_img
            # **关键**：设为 Active 节点，Cycles 会将烘焙结果写入此图像
            nodes.active = bake_tex_node

            # --- 将临时材质赋予物体 ---
            # 先清空所有材质槽
            obj.data.materials.clear()
            obj.data.materials.append(temp_mat)

            # --- 设置活动UV为目标UV ---
            # Cycles 烘焙会使用活动 UV 层作为烘焙的 UV 坐标
            target_uv_layer = mesh.uv_layers[target_uv]
            mesh.uv_layers.active = target_uv_layer
            # 同时设置 render UV
            target_uv_layer.active_render = True

            # --- 执行烘焙 ---
            log_message(context, "正在烘焙...", "INFO")

            bpy.ops.object.bake(
                type='EMIT',
                margin=margin,
                use_clear=True,
                margin_type='EXTEND',
            )

            # --- 保存结果 ---
            output_dir = bpy.path.abspath(props.output_dir) if props.output_dir else os.path.dirname(source_tex_path)
            if not output_dir:
                output_dir = os.path.expanduser("~")

            os.makedirs(output_dir, exist_ok=True)

            ext = format_ext_map.get(output_format, ".png")
            # 如果批量物体，文件名加上物体名
            if props.batch_objects and len([o for o in context.selected_objects if o.type == 'MESH']) > 1:
                output_filename = f"{tex_name}{props.output_suffix}_{obj.name}{ext}"
            else:
                output_filename = f"{tex_name}{props.output_suffix}{ext}"

            output_path = os.path.join(output_dir, output_filename)

            # **关键修复**：使用 image.save() 而非 save_render()
            # save_render() 会经过场景的颜色管理（View Transform / Look），
            # 对已经正确编码的烘焙结果再做一次色彩变换，导致 double gamma（偏灰）。
            # image.save() 则直接按照图像自身的颜色空间设置保存原始像素数据。
            bake_img.filepath_raw = output_path
            bake_img.file_format = output_format

            # 设置色深
            if output_format == 'OPEN_EXR':
                bake_img.use_half_precision = True  # 16-bit float EXR
            elif output_format in ('PNG', 'TIFF'):
                # PNG/TIFF 默认 8-bit 即可，如需16-bit可调整
                pass

            bake_img.save()

            return output_path

        finally:
            # --- 恢复原始材质 ---
            obj.data.materials.clear()
            for mat in original_materials:
                obj.data.materials.append(mat)

            # 如果原来没有材质，就不需要恢复
            if not original_materials:
                pass  # 保持清空状态

            # 恢复活动UV
            if original_active_uv and original_active_uv in mesh.uv_layers:
                mesh.uv_layers.active = mesh.uv_layers[original_active_uv]

            # 清理临时材质
            if temp_mat.users == 0:
                bpy.data.materials.remove(temp_mat)

            # 清理临时源图像（保留烘焙图像供预览）
            if src_img.users == 0:
                bpy.data.images.remove(src_img)

    def _apply_preview(self, context, obj, output_path, target_uv):
        """将烘焙结果贴图应用到模型上预览"""
        try:
            # 加载结果图像
            result_img = bpy.data.images.load(output_path)

            # 获取或创建预览材质
            preview_mat_name = f"_1u2u_preview_{obj.name}"
            if preview_mat_name in bpy.data.materials:
                preview_mat = bpy.data.materials[preview_mat_name]
            else:
                preview_mat = bpy.data.materials.new(name=preview_mat_name)
                preview_mat.use_nodes = True

            nodes = preview_mat.node_tree.nodes
            links = preview_mat.node_tree.links
            nodes.clear()

            # Principled BSDF
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)

            # Material Output
            output_node = nodes.new(type='ShaderNodeOutputMaterial')
            output_node.location = (300, 0)
            links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

            # Image Texture
            tex_node = nodes.new(type='ShaderNodeTexImage')
            tex_node.location = (-300, 0)
            tex_node.image = result_img
            links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])

            # UV Map → 使用目标UV
            uv_node = nodes.new(type='ShaderNodeUVMap')
            uv_node.location = (-600, 0)
            uv_node.uv_map = target_uv
            links.new(uv_node.outputs['UV'], tex_node.inputs['Vector'])

            # 应用材质
            if not obj.material_slots:
                obj.data.materials.append(preview_mat)
            else:
                obj.material_slots[0].material = preview_mat

            log_message(context, f"已应用预览材质到 {obj.name}", "INFO")

        except Exception as e:
            log_message(context, f"应用预览失败: {str(e)}", "WARNING")

    @classmethod
    def poll(cls, context):
        props = context.scene.uv_transfer_props
        if props.is_baking:
            return False

        if props.work_mode == 'DUAL':
            # 双模型模式：只需要源模型和目标模型存在
            src_obj = bpy.data.objects.get(props.dual_source_object)
            tgt_obj = bpy.data.objects.get(props.dual_target_object)
            return (
                src_obj is not None and src_obj.type == 'MESH'
                and tgt_obj is not None and tgt_obj.type == 'MESH'
                and src_obj != tgt_obj
            )
        else:
            # 单模型模式：需要当前模型至少2套UV
            return (
                context.active_object is not None
                and context.active_object.type == 'MESH'
                and len(context.active_object.data.uv_layers) >= 2
            )


# ============================================================
# 快速检测操作器
# ============================================================

class UV_TRANSFER_OT_DetectUV(Operator):
    """检测选中物体的UV信息"""
    bl_idname = "uv_transfer.detect_uv"
    bl_label = "检测UV"
    bl_description = "检测当前选中物体的UV通道信息"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            log_message(context, "请先选择一个网格物体", "WARNING")
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}

        mesh = obj.data
        uv_layers = mesh.uv_layers
        log_message(context, f"物体: {obj.name}", "INFO")
        log_message(context, f"顶点数: {len(mesh.vertices)}, 面数: {len(mesh.polygons)}", "INFO")
        log_message(context, f"UV通道数: {len(uv_layers)}", "INFO")

        for i, uv_layer in enumerate(uv_layers):
            active_mark = " (活动)" if uv_layer.active else ""
            render_mark = " (渲染)" if uv_layer.active_render else ""
            log_message(context, f"  UV{i}: {uv_layer.name}{active_mark}{render_mark}", "INFO")

        if len(uv_layers) < 2:
            log_message(context, "警告：需要至少2套UV才能进行转烘", "WARNING")
            self.report({'WARNING'}, "需要至少2套UV才能进行转烘")
        else:
            log_message(context, "UV通道充足，可以进行转烘", "SUCCESS")
            self.report({'INFO'}, f"检测到 {len(uv_layers)} 套UV")

        return {'FINISHED'}


# ============================================================
# UI 面板
# ============================================================

class UV_TRANSFER_PT_MainPanel(Panel):
    """UV贴图转烘工具 - 主面板"""
    bl_label = "1U to 2U - UV贴图转烘"
    bl_idname = "UV_TRANSFER_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props
        obj = context.active_object

        # ========== 工作模式 ==========
        box = layout.box()
        row = box.row(align=True)
        row.label(text="工作模式", icon='TOOL_SETTINGS')
        row.prop(props, "work_mode", expand=True)

        if props.work_mode == 'SINGLE':
            # ========== 单模型模式：显示当前物体信息 ==========
            box = layout.box()
            box.label(text="模型信息", icon='MESH_DATA')

            if obj and obj.type == 'MESH':
                mesh = obj.data
                uv_count = len(mesh.uv_layers)

                row = box.row()
                row.label(text=f"物体: {obj.name}", icon='OBJECT_DATA')

                row = box.row()
                if uv_count >= 2:
                    row.label(text=f"UV通道: {uv_count} 套", icon='CHECKMARK')
                elif uv_count == 1:
                    row.label(text=f"UV通道: {uv_count} 套 (需要至少2套)", icon='ERROR')
                else:
                    row.label(text="无UV通道", icon='ERROR')

                if uv_count > 0:
                    uv_names = ", ".join([uv.name for uv in mesh.uv_layers])
                    row = box.row()
                    row.label(text=f"  [{uv_names}]")
            else:
                box.label(text="请选择一个网格物体", icon='ERROR')

            box.operator("uv_transfer.detect_uv", text="刷新检测", icon='FILE_REFRESH')

        else:
            # ========== 双模型模式：源模型和目标模型选择 ==========
            # 源模型
            box = layout.box()
            box.label(text="源模型 (提供UV)", icon='EXPORT')

            row = box.row(align=True)
            row.prop(props, "dual_source_object", text="")
            op = row.operator("uv_transfer.set_from_active", text="", icon='EYEDROPPER')
            op.target_prop = "source"

            src_obj = bpy.data.objects.get(props.dual_source_object)
            if src_obj and src_obj.type == 'MESH':
                src_mesh = src_obj.data
                info_row = box.row()
                info_row.label(
                    text=f"顶点: {len(src_mesh.vertices)} | 面: {len(src_mesh.polygons)} | UV: {len(src_mesh.uv_layers)}",
                    icon='INFO'
                )

            # 目标模型
            box = layout.box()
            box.label(text="目标模型 (接收转烘)", icon='IMPORT')

            row = box.row(align=True)
            row.prop(props, "dual_target_object", text="")
            op = row.operator("uv_transfer.set_from_active", text="", icon='EYEDROPPER')
            op.target_prop = "target"

            tgt_obj = bpy.data.objects.get(props.dual_target_object)
            if tgt_obj and tgt_obj.type == 'MESH':
                tgt_mesh = tgt_obj.data
                info_row = box.row()
                info_row.label(
                    text=f"顶点: {len(tgt_mesh.vertices)} | 面: {len(tgt_mesh.polygons)} | UV: {len(tgt_mesh.uv_layers)}",
                    icon='INFO'
                )

            # 同一物体警告
            if (props.dual_source_object and props.dual_target_object
                    and props.dual_source_object == props.dual_target_object):
                layout.label(text="⚠ 源和目标不能是同一物体!", icon='ERROR')

            # 拓扑检测
            box = layout.box()
            box.label(text="拓扑检测", icon='VIEWZOOM')
            box.operator("uv_transfer.check_topology", text="检测拓扑一致性", icon='FILE_REFRESH')

            if props.topo_check_result:
                result_box = box.box()
                for line in props.topo_check_result.split("\n"):
                    if line.strip():
                        if "✔" in line:
                            result_box.label(text=line, icon='CHECKMARK')
                        elif "✘" in line:
                            result_box.label(text=line, icon='ERROR')
                        elif "错误" in line or "失败" in line:
                            result_box.label(text=line, icon='ERROR')
                        else:
                            result_box.label(text=line, icon='DOT')

            # 独立UV传递
            box = layout.box()
            box.label(text="独立UV传递", icon='UV_SYNC_SELECT')

            row = box.row(align=True)
            row.label(text="源UV")
            row.prop(props, "dual_source_uv", text="")

            row = box.row(align=True)
            row.label(text="目标层名")
            row.prop(props, "transfer_uv_name", text="")

            row = box.row(align=True)
            row.scale_y = 1.3
            row.operator("uv_transfer.transfer_uv", text="传递UV", icon='PASTEDOWN')


class UV_TRANSFER_PT_TexturePanel(Panel):
    """UV贴图转烘工具 - 贴图列表面板"""
    bl_label = "源贴图"
    bl_idname = "UV_TRANSFER_PT_TexturePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"
    bl_parent_id = "UV_TRANSFER_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props

        # 贴图列表
        row = layout.row()
        row.template_list(
            "UV_TRANSFER_UL_TextureList", "",
            props, "texture_items",
            props, "texture_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("uv_transfer.add_texture", icon='ADD', text="")
        col.operator("uv_transfer.remove_texture", icon='REMOVE', text="")
        col.separator()
        col.operator("uv_transfer.clear_textures", icon='TRASH', text="")

        # 选中项的详细路径
        if props.texture_items and 0 <= props.texture_index < len(props.texture_items):
            item = props.texture_items[props.texture_index]
            box = layout.box()
            box.prop(item, "filepath", text="路径")
            box.prop(item, "is_data", text="非颜色数据 (Normal/Roughness等)")
            box.label(text=f"状态: {item.status}")


class UV_TRANSFER_PT_SettingsPanel(Panel):
    """UV贴图转烘工具 - 设置面板"""
    bl_label = "转烘设置"
    bl_idname = "UV_TRANSFER_PT_SettingsPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"
    bl_parent_id = "UV_TRANSFER_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props
        obj = context.active_object

        # UV通道选择
        box = layout.box()
        box.label(text="UV通道", icon='GROUP_UVS')

        if props.work_mode == 'SINGLE':
            # 单模型模式：从同一模型上选择两套UV
            row = box.row(align=True)
            row.label(text="从")
            row.prop(props, "source_uv", text="")
            row.label(text="→")
            row.prop(props, "target_uv", text="")

            # 检查是否相同
            if obj and obj.type == 'MESH' and props.source_uv == props.target_uv and props.source_uv != "NONE":
                box.label(text="⚠ 源UV和目标UV不能相同!", icon='ERROR')
        else:
            # 双模型模式：分别从源模型和目标模型选择UV
            row = box.row(align=True)
            row.label(text="源UV")
            row.prop(props, "dual_source_uv", text="")

            row = box.row(align=True)
            row.label(text="目标UV")
            row.prop(props, "dual_target_uv", text="")

        layout.separator()

        # 输出设置
        box = layout.box()
        box.label(text="输出设置", icon='OUTPUT')
        box.prop(props, "resolution")
        box.prop(props, "output_format")
        box.prop(props, "output_dir")
        box.prop(props, "output_suffix")
        box.operator("uv_transfer.open_output_dir", text="打开输出目录", icon='FILEBROWSER')


class UV_TRANSFER_PT_AdvancedPanel(Panel):
    """UV贴图转烘工具 - 高级设置面板"""
    bl_label = "高级选项"
    bl_idname = "UV_TRANSFER_PT_AdvancedPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"
    bl_parent_id = "UV_TRANSFER_PT_MainPanel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props

        # 边缘扩展
        box = layout.box()
        row = box.row()
        row.prop(props, "use_margin")
        if props.use_margin:
            row = box.row()
            row.prop(props, "margin")

        layout.separator()

        # 其他选项
        layout.prop(props, "samples")
        layout.prop(props, "auto_preview")
        # 批量物体仅在单模型模式下可用
        if props.work_mode == 'SINGLE':
            layout.prop(props, "batch_objects")
        # 保留临时UV仅在双模型模式下显示
        if props.work_mode == 'DUAL':
            layout.prop(props, "keep_temp_uv")


class UV_TRANSFER_PT_ActionPanel(Panel):
    """UV贴图转烘工具 - 执行面板"""
    bl_label = "执行"
    bl_idname = "UV_TRANSFER_PT_ActionPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"
    bl_parent_id = "UV_TRANSFER_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props

        # 进度条
        if props.is_baking:
            layout.prop(props, "progress", text="进度")

        # 开始按钮
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("uv_transfer.bake", text="开始转烘", icon='RENDER_STILL')


class UV_TRANSFER_PT_LogPanel(Panel):
    """UV贴图转烘工具 - 日志面板"""
    bl_label = "执行日志"
    bl_idname = "UV_TRANSFER_PT_LogPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "1U to 2U"
    bl_parent_id = "UV_TRANSFER_PT_MainPanel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_transfer_props

        # 清空按钮
        layout.operator("uv_transfer.clear_log", text="清空日志", icon='TRASH')

        # 日志内容
        box = layout.box()
        if props.log_items:
            # 显示最近的日志（最多20条）
            start = max(0, len(props.log_items) - 20)
            for i in range(start, len(props.log_items)):
                item = props.log_items[i]
                icon = 'INFO'
                if item.level == "ERROR":
                    icon = 'ERROR'
                elif item.level == "WARNING":
                    icon = 'QUESTION'
                elif item.level == "SUCCESS":
                    icon = 'CHECKMARK'
                box.label(text=item.message, icon=icon)
        else:
            box.label(text="暂无日志", icon='INFO')


# ============================================================
# 注册
# ============================================================

classes = (
    UV_TRANSFER_TextureItem,
    UV_TRANSFER_LogItem,
    UV_TRANSFER_UL_TextureList,
    UV_TRANSFER_Properties,
    UV_TRANSFER_OT_AddTexture,
    UV_TRANSFER_OT_RemoveTexture,
    UV_TRANSFER_OT_ClearTextures,
    UV_TRANSFER_OT_ClearLog,
    UV_TRANSFER_OT_CheckTopology,
    UV_TRANSFER_OT_SetFromActive,
    UV_TRANSFER_OT_TransferUV,
    UV_TRANSFER_OT_OpenOutputDir,
    UV_TRANSFER_OT_Bake,
    UV_TRANSFER_OT_DetectUV,
    UV_TRANSFER_PT_MainPanel,
    UV_TRANSFER_PT_TexturePanel,
    UV_TRANSFER_PT_SettingsPanel,
    UV_TRANSFER_PT_AdvancedPanel,
    UV_TRANSFER_PT_ActionPanel,
    UV_TRANSFER_PT_LogPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uv_transfer_props = bpy.props.PointerProperty(type=UV_TRANSFER_Properties)
    print("[1U to 2U] 插件已注册")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.uv_transfer_props
    print("[1U to 2U] 插件已注销")


if __name__ == "__main__":
    register()
