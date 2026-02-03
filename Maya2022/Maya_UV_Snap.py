# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel
import math

# 全局变量存储吸附阈值
snap_threshold = 0.01  # 默认阈值(缩小一个量级)

def snap_uv_to_nearest(*args):
    """
    将选中的UV点吸附到目标UV块上最近的UV点(在阈值范围内)
    """
    global snap_threshold
    # 获取当前选中的UV点
    selected_uvs = cmds.ls(sl=True, fl=True, type="float2")
    if not selected_uvs:
        cmds.warning("请先选择一些UV点")
        return
    
    # 分离源UV点和目标UV点 - 目标UV点是最后选中的那个UV点
    if len(selected_uvs) < 2:
        cmds.warning("需要选择至少2个UV点：要移动的UV点和目标UV点")
        return
    
    # 改进的选择顺序处理
    # 使用选择历史记录获取最后操作的UV点
    selection_history = cmds.undoInfo(query=True, undoName=True)
    if not selection_history or "select" not in selection_history.lower():
        cmds.warning("无法确定最后选择的UV点")
        return
    
    # 解析最后的选择操作
    if "select -tgl" in selection_history:
        # 从toggle操作中提取目标UV点
        target_uv = selection_history.split()[-1].rstrip(";")
        if not cmds.objExists(target_uv):
            cmds.warning(f"无法找到目标UV点: {target_uv}")
            return
    else:
        cmds.warning("请最后使用select -tgl单独选择目标UV点")
        return
    
    # 源点是之前选中的所有点（排除目标点）
    source_uvs = [uv for uv in selected_uvs if uv != target_uv]
    
    if not source_uvs:
        cmds.warning("请先选择要移动的源UV点")
        return
    
    # 确保选择顺序不影响吸附方向
    # 我们需要明确：源UV点应该吸附到目标UV点所在的UV块
    
    # 获取目标UV块的所有UV点
    cmds.select(target_uv)
    mel.eval('polySelectBorderShell 0')
    target_uvs = cmds.ls(sl=True, fl=True)
    
    if not target_uvs:
        cmds.warning("无法确定目标UV块")
        return
    
    # 恢复原始选择
    cmds.select(selected_uvs)
    
    # 改进的UV块检查逻辑
    # 获取目标UV块
    cmds.select(target_uv)
    mel.eval('polySelectBorderShell 0')
    target_uvs = cmds.ls(sl=True, fl=True)
    
    # 获取源UV块（取第一个源UV点测试）
    cmds.select(source_uvs[0])
    mel.eval('polySelectBorderShell 0')
    source_uvs_shell = cmds.ls(sl=True, fl=True)
    
    # 检查两个UV块是否有交集
    common_uvs = set(target_uvs) & set(source_uvs_shell)
    if common_uvs:
        cmds.warning(f"源UV块和目标UV块有 {len(common_uvs)} 个共同UV点，请选择完全独立的UV块")
        cmds.select(selected_uvs)
        return
    
    # 恢复原始选择
    cmds.select(selected_uvs)
    
    # 收集目标UV点的坐标
    target_points = []
    for uv in target_uvs:
        u, v = cmds.polyEditUV(uv, q=True)
        target_points.append((u, v))
    
    # 对每个源UV点找到最近的目标UV点并吸附
    # 确保只移动源UV块的点，不移动目标UV块的点
    for uv in source_uvs:
        # 检查当前UV点是否属于目标UV块
        if uv in target_uvs:
            continue  # 跳过目标UV块的点
            
        u, v = cmds.polyEditUV(uv, q=True)
        min_dist = float('inf')
        nearest_point = None
        
        # 寻找最近的目标UV点
        for target_u, target_v in target_points:
            dist = math.sqrt((u - target_u)**2 + (v - target_v)**2)
            if dist < min_dist:
                min_dist = dist
                nearest_point = (target_u, target_v)
        
        # 移动源UV点到最近的目标点(在阈值范围内)
        if nearest_point and min_dist <= snap_threshold:
            cmds.polyEditUV(uv, r=False)  # 确保使用绝对坐标模式
            cmds.polyEditUV(uv, u=nearest_point[0], v=nearest_point[1], r=False)
            print(f"UV点 {uv} 已吸附到 ({nearest_point[0]:.3f}, {nearest_point[1]:.3f})，距离: {min_dist:.3f}")
        elif nearest_point:
            print(f"UV点 {uv} 距离 {min_dist:.3f} 超过阈值 {snap_threshold:.3f}，未吸附")

# 创建UI按钮
def create_snap_uv_button():
    """
    创建一个可停靠的UV吸附工具窗口
    """
    # 清理所有可能残留的UI元素
    ui_elements = ["snapUVDock", "snapUVWindow", "thresholdSlider"]
    for element in ui_elements:
        if cmds.workspaceControl(element, exists=True):
            cmds.deleteUI(element)
        if cmds.window(element, exists=True):
            cmds.deleteUI(element)
        if cmds.dockControl(element, exists=True):
            cmds.deleteUI(element)
    
    # 只创建workspaceControl，不再创建window
    workspace = cmds.workspaceControl("snapUVDock",
                                    label="UV吸附工具",
                                    initialWidth=200,
                                    minimumWidth=True,
                                    floating=True)
    
    # 在workspaceControl内创建布局和内容
    cmds.columnLayout(adjustableColumn=True, rowSpacing=10, parent="snapUVDock")
    
    # 使用说明部分
    cmds.frameLayout(label="使用说明", collapsable=True, collapse=False, 
                     marginWidth=10, marginHeight=5)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=5)
    cmds.text(label="1. 在UV编辑器中选择源UV点", align="left")
    cmds.text(label="2. 最后单独选择目标UV点", align="left")
    cmds.text(label="3. 调整吸附阈值", align="left")
    cmds.text(label="4. 点击吸附按钮", align="left")
    cmds.text(label="注意：源UV块和目标UV块", align="left")
    cmds.text(label="必须是完全独立的UV块", align="left")
    cmds.setParent('..')
    cmds.setParent('..')
    
    # 尝试附加到UV编辑器(如果有)
    try:
        uv_editor = cmds.getPanel(scriptType="polyTexturePlacementPanel")[0]  # 取第一个
        cmds.workspaceControl("snapUVDock", e=True, tabToControl=(uv_editor, -1))
    except:
        pass  # 附加失败则保持浮动状态

    # 添加阈值控制滑块
    cmds.text("吸附阈值:")
    cmds.floatSliderGrp("thresholdSlider", 
                       min=0.001,  # 最小值缩小一个量级
                       max=0.1,   # 最大值缩小一个量级
                       value=0.01, # 默认值缩小一个量级
                       step=0.001, # 步长缩小一个量级
                       columnWidth3=[60, 100, 40],
                       dragCommand=lambda *args: update_snap_threshold())
    
    cmds.button(label="吸附到最近UV点", command=lambda *args: snap_uv_to_nearest())
    cmds.showWindow()

def update_snap_threshold():
    """
    更新吸附阈值
    """
    global snap_threshold
    snap_threshold = cmds.floatSliderGrp("thresholdSlider", q=True, value=True)

# 执行创建UI
create_snap_uv_button()
