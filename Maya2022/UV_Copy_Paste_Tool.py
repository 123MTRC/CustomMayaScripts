# -*- coding: utf-8 -*-
"""
Maya UV编辑器复制粘贴工具
功能：在UV编辑器中复制选中的UV壳，粘贴到另一个相同拓扑的UV壳上
支持：Maya 2022
作者：Custom Tools
"""

import maya.cmds as cmds
import maya.mel as mel

class UVShellCopyPasteTool:
    """UV壳复制粘贴工具类"""
    
    def __init__(self):
        self.uv_data = None
        self.source_uv_ids = []
        self.uv_positions = {}
        self.window_name = "uvShellCopyPasteWindow"
        self.status_text = None
        
    def get_selected_uv_shells(self):
        """
        获取当前选中的所有UV壳
        :return: UV壳列表（每个元素是一个UV组件，代表一个壳）
        """
        # 获取选中的UV
        selected_uvs = cmds.ls(selection=True, flatten=True)
        
        if not selected_uvs:
            return None
        
        # 过滤出UV组件
        uv_components = cmds.filterExpand(selected_uvs, selectionMask=35)  # 35 = UV
        
        if not uv_components:
            return None
        
        # 使用MEL命令获取所有选中UV所属的UV壳
        # 保存当前选择
        original_selection = cmds.ls(selection=True, flatten=True)
        
        # 存储所有UV壳
        all_uv_shells = []
        processed_uvs = set()
        
        for uv_comp in uv_components:
            # 如果这个UV已经处理过，跳过
            if uv_comp in processed_uvs:
                continue
            
            # 选择这个UV
            cmds.select(uv_comp, replace=True)
            
            # 扩展选择到整个UV壳
            mel.eval('polySelectBorderShell 0;')
            
            # 获取UV壳的所有UV
            shell_uvs = cmds.ls(selection=True, flatten=True)
            shell_uv_components = cmds.filterExpand(shell_uvs, selectionMask=35)
            
            if shell_uv_components:
                # 将这个壳的第一个UV作为代表
                all_uv_shells.append(shell_uv_components[0])
                
                # 标记这个壳的所有UV为已处理
                for uv in shell_uv_components:
                    processed_uvs.add(uv)
        
        # 恢复原始选择
        if original_selection:
            cmds.select(original_selection, replace=True)
        
        return all_uv_shells if all_uv_shells else None
    
    def get_uv_to_vertex_mapping(self, obj_name, uv_components):
        """
        获取UV点到顶点的映射关系
        :param obj_name: 对象名称
        :param uv_components: UV组件列表
        :return: UV ID到顶点ID的映射字典
        """
        uv_to_vertex = {}
        
        for uv in uv_components:
            try:
                # 获取UV ID
                uv_id = int(uv.split('[')[-1].split(']')[0])
                
                # 使用polyListComponentConversion获取UV对应的顶点
                vertices = cmds.polyListComponentConversion(uv, fromUV=True, toVertex=True)
                
                if vertices:
                    vertices_list = cmds.ls(vertices, flatten=True)
                    if vertices_list:
                        # 获取第一个顶点ID
                        vertex = vertices_list[0]
                        vertex_id = int(vertex.split('[')[-1].split(']')[0])
                        uv_to_vertex[uv_id] = vertex_id
                    else:
                        # 如果无法获取顶点，使用UV ID作为备用
                        uv_to_vertex[uv_id] = uv_id
                else:
                    uv_to_vertex[uv_id] = uv_id
            except:
                # 出错时使用UV ID作为备用
                uv_id = int(uv.split('[')[-1].split(']')[0])
                uv_to_vertex[uv_id] = uv_id
        
        return uv_to_vertex
    
    def get_uv_shell_data(self, uv_component):
        """
        获取UV壳的数据
        :param uv_component: UV组件
        :return: UV数据字典
        """
        # 选择UV组件并扩展选择到整个UV壳
        cmds.select(uv_component, replace=True)
        
        # 使用mel命令选择UV壳
        mel.eval('polySelectBorderShell 0;')
        
        # 获取选中的所有UV
        uvs = cmds.ls(selection=True, flatten=True)
        uv_components = cmds.filterExpand(uvs, selectionMask=35)
        
        if not uv_components:
            return None
        
        # 获取对象名称
        obj_name = uv_component.split('.')[0]
        
        # 存储UV ID和坐标
        uv_data = {}
        uv_ids = []
        
        for uv in uv_components:
            # 获取UV索引
            uv_id = int(uv.split('[')[-1].split(']')[0])
            uv_ids.append(uv_id)
            
            # 获取UV坐标
            uv_coords = cmds.polyEditUV(uv, query=True)
            if uv_coords and len(uv_coords) >= 2:
                uv_data[uv_id] = {
                    'u': uv_coords[0],
                    'v': uv_coords[1]
                }
        
        # 获取UV到顶点的映射关系
        uv_to_vertex = self.get_uv_to_vertex_mapping(obj_name, uv_components)
        
        # 按照顶点ID排序UV点（改进的映射方法）
        sorted_ids = sorted(uv_ids, key=lambda x: uv_to_vertex.get(x, x))
        id_map = {orig_id: idx for idx, orig_id in enumerate(sorted_ids)}
        
        return {
            'object': obj_name,
            'uv_count': len(uv_ids),
            'uv_ids': uv_ids,
            'uv_data': uv_data,
            'id_map': id_map,
            'sorted_ids': sorted_ids,
            'uv_to_vertex': uv_to_vertex  # 保存映射关系用于调试
        }
    
    def copy_uv_shell(self):
        """复制选中的UV壳"""
        # 获取选中的UV壳
        uv_shells = self.get_selected_uv_shells()
        
        if not uv_shells:
            cmds.warning("请在UV编辑器中选择UV！")
            return False
        
        # 只处理第一个UV壳
        uv_shell = uv_shells[0]
        
        # 获取UV壳数据
        self.uv_data = self.get_uv_shell_data(uv_shell)
        
        if not self.uv_data:
            cmds.warning("获取UV数据失败！")
            return False
        
        # 计算UV的中心点和相对坐标
        uv_positions = self.uv_data['uv_data']
        
        # 计算中心点
        sum_u = sum(data['u'] for data in uv_positions.values())
        sum_v = sum(data['v'] for data in uv_positions.values())
        count = len(uv_positions)
        
        center_u = sum_u / count
        center_v = sum_v / count
        
        # 存储相对坐标
        self.uv_data['center'] = {'u': center_u, 'v': center_v}
        self.uv_data['relative_coords'] = {}
        
        for uv_id, coords in uv_positions.items():
            self.uv_data['relative_coords'][uv_id] = {
                'u': coords['u'] - center_u,
                'v': coords['v'] - center_v
            }
        
        cmds.inViewMessage(
            amg='UV壳已复制！UV点数: {}'.format(self.uv_data['uv_count']),
            pos='midCenter',
            fade=True,
            fadeStayTime=1000,
            fadeOutTime=500
        )
        
        print("UV壳已复制：{}".format(self.uv_data['object']))
        print("  UV点数: {}".format(self.uv_data['uv_count']))
        print("  映射方法: 基于顶点ID排序")
        print("  提示: 可以同时选择多个UV壳进行批量粘贴")
        
        # 调试信息：显示前5个UV到顶点的映射
        if 'uv_to_vertex' in self.uv_data:
            print("  UV到顶点映射示例（前5个）:")
            for i, uv_id in enumerate(self.uv_data['sorted_ids'][:5]):
                vertex_id = self.uv_data['uv_to_vertex'].get(uv_id, 'N/A')
                print("    UV[{}] -> Vertex[{}]".format(uv_id, vertex_id))
        
        # 更新UI状态
        self.update_status("已复制UV壳 | 对象: {} | UV点数: {} | 可批量粘贴".format(
            self.uv_data['object'], 
            self.uv_data['uv_count']
        ))
        
        return True
    
    def paste_uv_shell(self, match_topology=True):
        """
        粘贴UV壳到选中的UV（支持批量粘贴）
        :param match_topology: 是否匹配拓扑结构
        """
        if not self.uv_data:
            cmds.warning("请先复制UV壳！")
            return False
        
        # 获取选中的所有UV壳
        uv_shells = self.get_selected_uv_shells()
        
        if not uv_shells:
            cmds.warning("请在UV编辑器中选择目标UV！")
            return False
        
        total_shells = len(uv_shells)
        success_count = 0
        failed_list = []
        
        print("\n" + "="*50)
        print("开始批量粘贴UV壳...")
        print("源对象: {}".format(self.uv_data['object']))
        print("目标UV壳数量: {}".format(total_shells))
        print("="*50)
        
        for idx, uv_shell in enumerate(uv_shells, 1):
            print("\n[{}/{}] 处理UV壳...".format(idx, total_shells))
            
            # 获取目标UV壳数据
            target_data = self.get_uv_shell_data(uv_shell)
            
            if not target_data:
                failed_list.append("UV壳#{} - 无法获取数据".format(idx))
                print("  ❌ 失败: 无法获取UV数据")
                continue
            
            # 检查UV数量是否匹配
            if match_topology and target_data['uv_count'] != self.uv_data['uv_count']:
                failed_msg = "UV壳#{} ({}) - UV点数不匹配: {}个 vs {}个".format(
                    idx,
                    target_data['object'],
                    target_data['uv_count'], 
                    self.uv_data['uv_count']
                )
                failed_list.append(failed_msg)
                print("  ❌ 失败: UV点数不匹配 (目标:{}个, 源:{}个)".format(
                    target_data['uv_count'], 
                    self.uv_data['uv_count']
                ))
                continue
            
            # 计算目标UV的中心点
            target_uv_positions = target_data['uv_data']
            sum_u = sum(data['u'] for data in target_uv_positions.values())
            sum_v = sum(data['v'] for data in target_uv_positions.values())
            count = len(target_uv_positions)
            
            target_center_u = sum_u / count
            target_center_v = sum_v / count
            
            # 应用UV坐标
            obj_name = target_data['object']
            target_sorted_ids = target_data['sorted_ids']
            source_sorted_ids = self.uv_data['sorted_ids']
            
            print("  目标对象: {}".format(obj_name))
            print("  目标中心: ({:.3f}, {:.3f})".format(target_center_u, target_center_v))
            
            # 按照排序后的索引进行一对一映射（基于顶点ID）
            apply_count = 0
            for i, target_uv_id in enumerate(target_sorted_ids):
                if i >= len(source_sorted_ids):
                    break
                
                source_uv_id = source_sorted_ids[i]
                
                # 获取源UV的相对坐标
                if source_uv_id in self.uv_data['relative_coords']:
                    rel_coords = self.uv_data['relative_coords'][source_uv_id]
                    
                    # 计算目标UV的新坐标（使用目标中心点）
                    new_u = target_center_u + rel_coords['u']
                    new_v = target_center_v + rel_coords['v']
                    
                    # 应用坐标
                    uv_point = "{}.map[{}]".format(obj_name, target_uv_id)
                    try:
                        cmds.polyEditUV(uv_point, u=new_u, v=new_v, relative=False)
                        apply_count += 1
                    except Exception as e:
                        print("  ⚠️  设置UV失败: {} - {}".format(uv_point, str(e)))
            
            success_count += 1
            print("  ✅ 成功: 已应用{}个UV点".format(apply_count))
        
        # 显示结果摘要
        print("\n" + "="*50)
        print("批量粘贴完成！")
        print("成功: {} 个UV壳".format(success_count))
        if failed_list:
            print("失败: {} 个UV壳".format(len(failed_list)))
            for fail_msg in failed_list:
                print("  - {}".format(fail_msg))
        print("="*50 + "\n")
        
        if success_count > 0:
            cmds.inViewMessage(
                amg='成功粘贴UV到 {} 个UV壳'.format(success_count),
                pos='midCenter',
                fade=True,
                fadeStayTime=1500,
                fadeOutTime=500
            )
            # 更新UI状态
            if failed_list:
                self.update_status("粘贴完成: 成功{}个, 失败{}个".format(
                    success_count, len(failed_list)
                ))
            else:
                self.update_status("成功粘贴UV到 {} 个UV壳".format(success_count))
            return True
        else:
            self.update_status("粘贴失败: 所有UV壳都不匹配")
        
        return False
    
    def update_status(self, message):
        """更新状态文本"""
        if self.status_text and cmds.text(self.status_text, exists=True):
            cmds.text(self.status_text, edit=True, label=message)
    
    def create_ui(self):
        """创建用户界面"""
        # 如果窗口已存在，删除它
        if cmds.window(self.window_name, exists=True):
            cmds.deleteUI(self.window_name)
        
        # 创建窗口
        window = cmds.window(
            self.window_name,
            title="UV壳复制粘贴工具",
            widthHeight=(380, 340),
            sizeable=True
        )
        
        # 创建主布局
        main_layout = cmds.columnLayout(
            adjustableColumn=True, 
            rowSpacing=8, 
            columnAttach=('both', 15)
        )
        
        # 添加顶部间距
        cmds.separator(height=10, style='none')
        
        # 标题
        cmds.text(
            label="UV壳复制粘贴工具", 
            font="boldLabelFont", 
            height=30,
            backgroundColor=(0.25, 0.25, 0.25)
        )
        
        cmds.separator(height=10, style='in')
        
        # 使用说明区域
        cmds.frameLayout(
            label="使用说明", 
            collapsable=False, 
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=10
        )
        
        cmds.columnLayout(adjustableColumn=True, rowSpacing=5)
        
        cmds.text(
            label="1. 在UV编辑器中选择源UV壳",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="2. 点击【复制UV壳】按钮",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="3. 在UV编辑器中选择目标UV壳（可多选）",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="4. 点击【粘贴UV壳】按钮",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        
        cmds.setParent('..')
        cmds.setParent('..')
        
        cmds.separator(height=10, style='none')
        
        # 按钮区域
        cmds.rowLayout(
            numberOfColumns=2, 
            columnWidth2=(165, 165), 
            columnAttach=[(1, 'both', 5), (2, 'both', 5)],
            height=50
        )
        
        cmds.button(
            label="复制UV壳",
            height=45,
            backgroundColor=(0.4, 0.6, 0.8),
            annotation="复制当前选中的UV壳",
            command=lambda x: self.copy_uv_shell()
        )
        
        cmds.button(
            label="粘贴UV壳",
            height=45,
            backgroundColor=(0.6, 0.8, 0.4),
            annotation="将UV壳粘贴到选中的目标UV壳（支持批量）",
            command=lambda x: self.paste_uv_shell()
        )
        
        cmds.setParent('..')
        
        cmds.separator(height=10, style='none')
        
        # 状态栏
        cmds.frameLayout(
            label="状态", 
            collapsable=False, 
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=8
        )
        
        self.status_text = cmds.text(
            label="就绪 - 请在UV编辑器中选择UV壳",
            align='center',
            height=25,
            font="smallPlainLabelFont",
            backgroundColor=(0.2, 0.2, 0.2)
        )
        
        cmds.setParent('..')
        
        cmds.separator(height=5, style='none')
        
        # 提示信息
        cmds.text(
            label="提示：支持批量粘贴，可同时选择多个UV壳",
            align='center',
            height=20,
            font="obliqueLabelFont",
            wordWrap=True
        )
        
        cmds.separator(height=8, style='none')
        
        # 显示窗口
        cmds.showWindow(window)
    
    def show_ui(self):
        """显示UI"""
        self.create_ui()


# 全局工具实例
uv_shell_tool = UVShellCopyPasteTool()


def copy_uv_shell():
    """复制UV壳的快捷函数"""
    return uv_shell_tool.copy_uv_shell()


def paste_uv_shell():
    """粘贴UV壳的快捷函数"""
    return uv_shell_tool.paste_uv_shell()


def show_ui():
    """显示UI窗口的快捷函数"""
    uv_shell_tool.show_ui()


# 主函数
if __name__ == "__main__":
    show_ui()
