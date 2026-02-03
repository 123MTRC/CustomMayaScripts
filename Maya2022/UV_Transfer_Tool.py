# -*- coding: utf-8 -*-
"""
Maya UV传递工具
功能：在完整模型之间传递UV数据
适用场景：两个拓扑完全一致的模型，需要复制UV
支持：Maya 2022
作者：Custom Tools
"""

import maya.cmds as cmds
import maya.mel as mel

class UVTransferTool:
    """UV传递工具类"""
    
    def __init__(self):
        self.uv_data = None
        self.window_name = "uvTransferWindow"
        self.status_text = None
        
    def get_mesh_from_selection(self):
        """
        从选择中获取网格对象（使用完整路径避免重名问题）
        :return: mesh shape节点的完整路径名称
        """
        # 使用long=True获取完整路径，避免重名问题
        selection = cmds.ls(selection=True, type='transform', long=True)
        
        if not selection:
            # 尝试直接获取shape节点
            selection = cmds.ls(selection=True, type='mesh', long=True)
            if selection:
                return selection[0]
            return None
        
        # 获取第一个选中对象的shape节点（使用fullPath获取完整路径）
        shapes = cmds.listRelatives(selection[0], shapes=True, type='mesh', fullPath=True)
        if shapes:
            return shapes[0]
        
        return None
    
    def get_uv_to_vertex_mapping(self, mesh):
        """
        获取UV点到顶点的映射关系
        :param mesh: mesh节点名称（完整路径）
        :return: UV ID到顶点ID的映射字典
        """
        uv_to_vertex = {}
        
        # 获取所有UV
        uv_count = cmds.polyEvaluate(mesh, uvcoord=True)
        
        # 获取短名称用于显示，但使用完整路径进行操作
        short_name = mesh.split('|')[-1]
        
        for uv_id in range(uv_count):
            # 使用完整路径构建UV组件名称
            uv_component = "{}.map[{}]".format(mesh, uv_id)
            
            try:
                # 获取UV对应的顶点
                vertices = cmds.polyListComponentConversion(
                    uv_component, 
                    fromUV=True, 
                    toVertex=True
                )
                
                if vertices:
                    vertices_list = cmds.ls(vertices, flatten=True)
                    if vertices_list:
                        vertex = vertices_list[0]
                        vertex_id = int(vertex.split('[')[-1].split(']')[0])
                        uv_to_vertex[uv_id] = vertex_id
                    else:
                        uv_to_vertex[uv_id] = uv_id
                else:
                    uv_to_vertex[uv_id] = uv_id
            except:
                uv_to_vertex[uv_id] = uv_id
        
        return uv_to_vertex
    
    def get_mesh_uv_data(self, mesh):
        """
        获取网格的所有UV数据
        :param mesh: mesh节点名称（完整路径）
        :return: UV数据字典
        """
        # 获取短名称用于显示
        short_name = mesh.split('|')[-1]
        
        # 获取网格拓扑信息
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        face_count = cmds.polyEvaluate(mesh, face=True)
        uv_count = cmds.polyEvaluate(mesh, uvcoord=True)
        
        print("读取UV数据...")
        print("  模型: {}".format(short_name))
        print("  顶点数: {}".format(vertex_count))
        print("  面数: {}".format(face_count))
        print("  UV点数: {}".format(uv_count))
        
        # 获取所有UV坐标
        uv_data = {}
        
        for uv_id in range(uv_count):
            # 使用完整路径构建UV组件名称
            uv_component = "{}.map[{}]".format(mesh, uv_id)
            
            try:
                uv_coords = cmds.polyEditUV(uv_component, query=True)
                if uv_coords and len(uv_coords) >= 2:
                    uv_data[uv_id] = {
                        'u': uv_coords[0],
                        'v': uv_coords[1]
                    }
            except:
                uv_data[uv_id] = {'u': 0.0, 'v': 0.0}
        
        # 获取UV到顶点的映射
        uv_to_vertex = self.get_uv_to_vertex_mapping(mesh)
        
        # 按顶点ID排序UV ID
        sorted_uv_ids = sorted(uv_data.keys(), key=lambda x: uv_to_vertex.get(x, x))
        
        return {
            'mesh': mesh,
            'vertex_count': vertex_count,
            'face_count': face_count,
            'uv_count': uv_count,
            'uv_data': uv_data,
            'uv_to_vertex': uv_to_vertex,
            'sorted_uv_ids': sorted_uv_ids
        }
    
    def copy_uv_from_mesh(self):
        """从选中的模型复制UV"""
        mesh = self.get_mesh_from_selection()
        
        if not mesh:
            cmds.warning("请选择一个网格模型！")
            return False
        
        try:
            self.uv_data = self.get_mesh_uv_data(mesh)
            
            # 获取短名称用于显示
            short_name = mesh.split('|')[-1]
            
            cmds.inViewMessage(
                amg='已复制UV数据！模型: {} | UV点数: {}'.format(
                    short_name, self.uv_data['uv_count']
                ),
                pos='midCenter',
                fade=True,
                fadeStayTime=1500,
                fadeOutTime=500
            )
            
            print("\n" + "="*50)
            print("UV数据已复制！")
            print("  源模型: {}".format(short_name))
            print("  完整路径: {}".format(mesh))
            print("  顶点数: {}".format(self.uv_data['vertex_count']))
            print("  面数: {}".format(self.uv_data['face_count']))
            print("  UV点数: {}".format(self.uv_data['uv_count']))
            print("  映射方法: 基于顶点ID")
            print("="*50 + "\n")
            
            # 更新UI状态
            self.update_status("已复制 {} | 顶点:{} | UV:{}".format(
                short_name,
                self.uv_data['vertex_count'],
                self.uv_data['uv_count']
            ))
            
            return True
            
        except Exception as e:
            cmds.warning("复制UV数据失败: {}".format(str(e)))
            return False
    
    def paste_uv_to_mesh(self):
        """将UV数据粘贴到选中的模型（支持批量）"""
        if not self.uv_data:
            cmds.warning("请先复制UV数据！")
            return False
        
        # 获取所有选中的模型（使用完整路径避免重名问题）
        selection = cmds.ls(selection=True, type='transform', long=True)
        
        if not selection:
            # 尝试直接获取mesh
            selection = cmds.ls(selection=True, type='mesh', long=True)
            if not selection:
                cmds.warning("请选择要粘贴UV的模型！")
                return False
        
        success_count = 0
        failed_list = []
        total_count = len(selection)
        
        # 获取源模型的短名称
        source_short_name = self.uv_data['mesh'].split('|')[-1]
        
        print("\n" + "="*50)
        print("开始批量传递UV...")
        print("源模型: {}".format(source_short_name))
        print("目标模型数量: {}".format(total_count))
        print("="*50)
        
        for idx, obj in enumerate(selection, 1):
            # 获取短名称用于显示
            obj_short_name = obj.split('|')[-1]
            
            print("\n[{}/{}] 处理模型: {}".format(idx, total_count, obj_short_name))
            
            # 获取mesh节点（使用完整路径）
            if cmds.nodeType(obj) == 'mesh':
                target_mesh = obj
            else:
                shapes = cmds.listRelatives(obj, shapes=True, type='mesh', fullPath=True)
                if not shapes:
                    failed_list.append("{} - 不是网格对象".format(obj_short_name))
                    print("  ❌ 失败: 不是网格对象")
                    continue
                target_mesh = shapes[0]
            
            # 检查拓扑是否匹配
            target_vertex_count = cmds.polyEvaluate(target_mesh, vertex=True)
            target_face_count = cmds.polyEvaluate(target_mesh, face=True)
            target_uv_count = cmds.polyEvaluate(target_mesh, uvcoord=True)
            
            print("  顶点数: {} (源: {})".format(
                target_vertex_count, self.uv_data['vertex_count']
            ))
            print("  UV点数: {} (源: {})".format(
                target_uv_count, self.uv_data['uv_count']
            ))
            
            # 检查拓扑匹配
            if target_vertex_count != self.uv_data['vertex_count']:
                failed_msg = "{} - 顶点数不匹配: {} vs {}".format(
                    obj_short_name, target_vertex_count, self.uv_data['vertex_count']
                )
                failed_list.append(failed_msg)
                print("  ❌ 失败: 顶点数不匹配")
                continue
            
            if target_face_count != self.uv_data['face_count']:
                failed_msg = "{} - 面数不匹配: {} vs {}".format(
                    obj_short_name, target_face_count, self.uv_data['face_count']
                )
                failed_list.append(failed_msg)
                print("  ❌ 失败: 面数不匹配")
                continue
            
            if target_uv_count != self.uv_data['uv_count']:
                failed_msg = "{} - UV点数不匹配: {} vs {}".format(
                    obj_short_name, target_uv_count, self.uv_data['uv_count']
                )
                failed_list.append(failed_msg)
                print("  ❌ 失败: UV点数不匹配")
                continue
            
            # 获取目标的UV到顶点映射
            target_uv_to_vertex = self.get_uv_to_vertex_mapping(target_mesh)
            target_sorted_uv_ids = sorted(
                range(target_uv_count), 
                key=lambda x: target_uv_to_vertex.get(x, x)
            )
            
            # 应用UV数据（按顶点ID映射）
            apply_count = 0
            error_count = 0
            
            for i, target_uv_id in enumerate(target_sorted_uv_ids):
                if i >= len(self.uv_data['sorted_uv_ids']):
                    break
                
                source_uv_id = self.uv_data['sorted_uv_ids'][i]
                
                if source_uv_id in self.uv_data['uv_data']:
                    uv_coords = self.uv_data['uv_data'][source_uv_id]
                    # 使用完整路径构建UV组件名称
                    uv_component = "{}.map[{}]".format(target_mesh, target_uv_id)
                    
                    try:
                        cmds.polyEditUV(
                            uv_component,
                            u=uv_coords['u'],
                            v=uv_coords['v'],
                            relative=False
                        )
                        apply_count += 1
                    except Exception as e:
                        error_count += 1
                        if error_count <= 3:  # 只显示前3个错误
                            print("  ⚠️  UV[{}]设置失败: {}".format(target_uv_id, str(e)))
            
            success_count += 1
            print("  ✅ 成功: 已传递{}个UV点".format(apply_count))
            if error_count > 0:
                print("  ⚠️  有{}个UV点设置失败".format(error_count))
        
        # 显示结果摘要
        print("\n" + "="*50)
        print("UV传递完成！")
        print("成功: {} 个模型".format(success_count))
        if failed_list:
            print("失败: {} 个模型".format(len(failed_list)))
            for fail_msg in failed_list:
                print("  - {}".format(fail_msg))
        print("="*50 + "\n")
        
        if success_count > 0:
            cmds.inViewMessage(
                amg='成功传递UV到 {} 个模型'.format(success_count),
                pos='midCenter',
                fade=True,
                fadeStayTime=1500,
                fadeOutTime=500
            )
            
            # 更新UI状态
            if failed_list:
                self.update_status("传递完成: 成功{}个, 失败{}个".format(
                    success_count, len(failed_list)
                ))
            else:
                self.update_status("成功传递UV到 {} 个模型".format(success_count))
            return True
        else:
            self.update_status("传递失败: 所有模型拓扑都不匹配")
        
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
            title="UV传递工具",
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
            label="UV传递工具", 
            font="boldLabelFont", 
            height=30,
            backgroundColor=(0.3, 0.25, 0.35)
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
            label="1. 在视图中选择源模型（已有UV）",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="2. 点击【复制UV】按钮",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="3. 在视图中选择目标模型（可多选）",
            align='left',
            height=22,
            font="smallPlainLabelFont"
        )
        cmds.text(
            label="4. 点击【粘贴UV】按钮",
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
            label="复制UV",
            height=45,
            backgroundColor=(0.5, 0.4, 0.7),
            annotation="从选中的模型复制UV数据",
            command=lambda x: self.copy_uv_from_mesh()
        )
        
        cmds.button(
            label="粘贴UV",
            height=45,
            backgroundColor=(0.7, 0.5, 0.4),
            annotation="将UV数据传递到选中的模型（支持批量）",
            command=lambda x: self.paste_uv_to_mesh()
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
            label="就绪 - 请在视图中选择模型",
            align='center',
            height=25,
            font="smallPlainLabelFont",
            backgroundColor=(0.2, 0.2, 0.2)
        )
        
        cmds.setParent('..')
        
        cmds.separator(height=5, style='none')
        
        # 提示信息
        cmds.text(
            label="提示：适用于拓扑完全相同的模型间UV传递",
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
uv_transfer_tool = UVTransferTool()


def copy_uv():
    """复制UV的快捷函数"""
    return uv_transfer_tool.copy_uv_from_mesh()


def paste_uv():
    """粘贴UV的快捷函数"""
    return uv_transfer_tool.paste_uv_to_mesh()


def show_ui():
    """显示UI窗口的快捷函数"""
    uv_transfer_tool.show_ui()


# 主函数
if __name__ == "__main__":
    show_ui()
