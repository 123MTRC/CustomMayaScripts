# -*- coding: utf-8 -*-
"""
Maya 智能分离与合并工具
功能：实现类似Blender的智能分离和合并功能
解决Maya原生功能的问题：
1. 避免生成多余的组和transform节点
2. 支持批量选择面片后一次性分离
3. 分离/合并后自动清理层级和历史
4. 保持物体原始位置和命名

适用场景：
- 需要将模型的选定部分分离为独立对象
- 需要批量分离多个面片组
- 需要合并多个对象且保持层级清洁
- 需要保持干净的场景层级结构

支持：Maya 2022+
作者：Custom Tools
"""

import maya.cmds as cmds
import maya.mel as mel


class SmartSeparateCombineTool:
    """智能分离与合并工具类"""
    
    def __init__(self):
        self.window_name = "smartSepCombineWindow"
        self.delete_original = True  # 是否删除原始模型中的分离部分
        self.clean_hierarchy = True  # 是否清理层级
        self.delete_history = True   # 是否删除历史
        self.separate_suffix = "separated"  # 分离后缀
        self.combine_suffix = "combined"    # 合并后缀
        self.suffix_field_separate = None   # 分离后缀输入框
        self.suffix_field_combine = None    # 合并后缀输入框
        
    def separate_selection(self, delete_original=True, clean_hierarchy=True, delete_history=True, custom_suffix=None):
        """
        智能分离选中的面片
        :param delete_original: 是否从原模型中删除分离的面
        :param clean_hierarchy: 是否清理多余的组和节点
        :param delete_history: 是否删除历史记录
        :return: 分离出的新对象列表
        """
        # 获取当前选择
        selection = cmds.ls(selection=True, flatten=True)
        
        if not selection:
            cmds.warning("请先选择要分离的面！")
            return None
        
        # 检查选择类型
        if not any('.f[' in str(s) for s in selection):
            cmds.warning("请选择面（Face）！当前选择的不是面组件。")
            return None
        
        # 获取选中的面所属的模型
        component_str = str(selection[0])
        if '.' in component_str:
            source_mesh = component_str.split('.')[0]
        else:
            cmds.warning("无法识别选择的组件！")
            return None
        
        # 获取源模型的短名称
        source_short_name = source_mesh.split('|')[-1]
        
        print("\n" + "="*60)
        print("开始智能分离...")
        print("源模型: {}".format(source_short_name))
        print("选中面数: {}".format(len(selection)))
        print("="*60)
        
        try:
            # 提取选中面的索引
            print("\n[步骤1] 分析选中的面...")
            original_face_indices = []
            for face in selection:
                if '.f[' in str(face):
                    face_str = str(face).split('.f[')[1].rstrip(']')
                    if ':' in face_str:
                        start, end = face_str.split(':')
                        original_face_indices.extend(range(int(start), int(end) + 1))
                    else:
                        original_face_indices.append(int(face_str))
            
            print("  ✅ 解析了 {} 个面索引".format(len(original_face_indices)))
            
            # 复制整个源对象
            print("\n[步骤2] 复制源模型...")
            cmds.select(source_mesh, replace=True)
            duplicated = cmds.duplicate(returnRootsOnly=True)
            
            if not duplicated:
                cmds.warning("复制失败！")
                return None
            
            # 使用完整路径避免重名问题
            duplicated_obj = cmds.ls(duplicated[0], long=True)[0]
            duplicated_short = duplicated[0]
            print("  ✅ 已复制为: {}".format(duplicated_short))
            
            # 在复制对象上删除不需要的面
            print("\n[步骤3] 保留需要的面...")
            total_faces = cmds.polyEvaluate(duplicated_obj, face=True)
            
            faces_to_delete = []
            for i in range(total_faces):
                if i not in original_face_indices:
                    faces_to_delete.append("{}.f[{}]".format(duplicated_obj, i))
            
            if faces_to_delete:
                cmds.select(faces_to_delete, replace=True)
                cmds.delete()
                print("  ✅ 已删除 {} 个不需要的面".format(len(faces_to_delete)))
            
            # 从原模型中删除分离的面
            if delete_original:
                print("\n[步骤4] 从原模型删除已分离的面...")
                cmds.select(selection, replace=True)
                cmds.delete()
                print("  ✅ 已删除原模型中的选中面")
            
            # 清理历史
            if delete_history:
                print("\n[步骤5] 清理历史记录...")
                cmds.select(duplicated_obj, replace=True)
                cmds.delete(constructionHistory=True)
                
                if delete_original:
                    cmds.select(source_mesh, replace=True)
                    cmds.delete(constructionHistory=True)
                
                print("  ✅ 历史记录已清理")
            
            # 清理层级结构
            if clean_hierarchy:
                print("\n[步骤6] 清理层级结构...")
                parent = cmds.listRelatives(duplicated_obj, parent=True, fullPath=True)
                if parent:
                    parent_type = cmds.nodeType(parent[0])
                    if parent_type == 'transform':
                        children = cmds.listRelatives(parent[0], children=True, type='transform')
                        if children and len(children) == 1:
                            cmds.parent(duplicated_obj, world=True)
                            if cmds.objExists(parent[0]):
                                cmds.delete(parent[0])
                            print("  ✅ 已清理多余的组节点")
            
            # 重命名新对象
            print("\n[步骤7] 重命名新对象...")
            
            # 使用自定义后缀或默认后缀
            suffix = custom_suffix if custom_suffix else self.separate_suffix
            
            # 如果后缀为空，直接使用原名称
            if suffix and suffix.strip():
                new_name = "{}_{}".format(source_short_name, suffix)
            else:
                new_name = source_short_name
            
            counter = 1
            final_name = new_name
            while cmds.objExists(final_name):
                if suffix and suffix.strip():
                    final_name = "{}_{}_{}".format(source_short_name, suffix, counter)
                else:
                    final_name = "{}_{}".format(source_short_name, counter)
                counter += 1
            
            if duplicated_short != final_name:
                renamed_obj = cmds.rename(duplicated_obj, final_name)
                duplicated_obj = cmds.ls(renamed_obj, long=True)[0]
                duplicated_short = renamed_obj
                print("  ✅ 已重命名为: {}".format(duplicated_short))
            
            cmds.select(duplicated_obj, replace=True)
            
            print("\n" + "="*60)
            print("分离完成！")
            print("新对象: {}".format(duplicated_short))
            print("="*60 + "\n")
            
            cmds.inViewMessage(
                amg='分离成功！新对象: {}'.format(duplicated_short),
                pos='midCenter',
                fade=True,
                fadeStayTime=2000,
                fadeOutTime=500
            )
            
            return [duplicated_short]
            
        except Exception as e:
            cmds.warning("分离失败: {}".format(str(e)))
            import traceback
            print("\n错误详情:")
            print(traceback.format_exc())
            return None
    
    def combine_selection(self, clean_hierarchy=True, delete_history=True, custom_suffix=None):
        """
        智能合并选中的对象
        :param clean_hierarchy: 是否清理多余的组和节点
        :param delete_history: 是否删除历史记录
        :param custom_suffix: 自定义后缀
        :return: 合并后的对象
        """
        selection = cmds.ls(selection=True, type='transform')
        
        if not selection or len(selection) < 2:
            cmds.warning("请选择至少两个对象进行合并！")
            return None
        
        print("\n" + "="*60)
        print("开始智能合并...")
        print("选中对象数: {}".format(len(selection)))
        print("="*60)
        
        try:
            # 记录第一个对象的名称（作为合并后的基础名称）
            first_obj = selection[0]
            first_obj_name = first_obj.split('|')[-1]
            
            print("\n[步骤1] 执行合并...")
            print("  基础对象: {}".format(first_obj_name))
            
            # 获取所有对象的完整路径（避免重名问题）
            selection_long = [cmds.ls(obj, long=True)[0] for obj in selection]
            cmds.select(selection_long, replace=True)
            
            # 执行合并
            combined = cmds.polyUnite(selection_long, constructionHistory=False, mergeUVSets=True)
            
            if not combined:
                cmds.warning("合并失败！")
                return None
            
            combined_obj = combined[0]
            combined_obj_long = cmds.ls(combined_obj, long=True)[0]
            print("  ✅ 合并完成: {}".format(combined_obj))
            
            # 清理层级结构
            if clean_hierarchy:
                print("\n[步骤2] 清理层级结构...")
                
                # 检查是否在组中
                parent = cmds.listRelatives(combined_obj_long, parent=True, fullPath=True)
                if parent:
                    parent_type = cmds.nodeType(parent[0])
                    if parent_type == 'transform':
                        # 提取到世界空间
                        try:
                            cmds.parent(combined_obj_long, world=True)
                            combined_obj_long = cmds.ls(combined_obj, long=True)[0]
                            print("  ✅ 已提取到根级别")
                        except:
                            pass
                        
                        # 删除空的父节点
                        if cmds.objExists(parent[0]):
                            children = cmds.listRelatives(parent[0], children=True)
                            if not children:
                                cmds.delete(parent[0])
                                print("  ✅ 已删除空组节点")
            
            # 清理历史
            if delete_history:
                print("\n[步骤3] 清理历史记录...")
                cmds.select(combined_obj_long, replace=True)
                cmds.delete(constructionHistory=True)
                print("  ✅ 历史记录已清理")
            
            # 重命名对象
            print("\n[步骤4] 重命名对象...")
            
            # 使用自定义后缀或默认后缀
            suffix = custom_suffix if custom_suffix else self.combine_suffix
            
            # 如果后缀为空，直接使用原名称
            if suffix and suffix.strip():
                new_name = "{}_{}".format(first_obj_name, suffix)
            else:
                new_name = first_obj_name
            
            # 确保名称唯一
            counter = 1
            final_name = new_name
            while cmds.objExists(final_name) and final_name != combined_obj:
                if suffix and suffix.strip():
                    final_name = "{}_{}_{}".format(first_obj_name, suffix, counter)
                else:
                    final_name = "{}_{}".format(first_obj_name, counter)
                counter += 1
            
            if combined_obj != final_name:
                renamed_obj = cmds.rename(combined_obj_long, final_name)
                combined_obj = renamed_obj
                print("  ✅ 已重命名为: {}".format(combined_obj))
            
            # 选中合并后的对象
            cmds.select(combined_obj, replace=True)
            
            print("\n" + "="*60)
            print("合并完成！")
            print("合并对象: {}".format(combined_obj))
            print("="*60 + "\n")
            
            cmds.inViewMessage(
                amg='合并成功！对象: {}'.format(combined_obj),
                pos='midCenter',
                fade=True,
                fadeStayTime=2000,
                fadeOutTime=500
            )
            
            return combined_obj
            
        except Exception as e:
            cmds.warning("合并失败: {}".format(str(e)))
            import traceback
            print("\n错误详情:")
            print(traceback.format_exc())
            return None
    
    def separate_by_loose_parts(self):
        """
        按松散部分分离（类似Blender的Separate by Loose Parts）
        """
        selection = cmds.ls(selection=True, type='transform')
        
        if not selection:
            cmds.warning("请选择一个或多个模型！")
            return None
        
        all_separated = []
        
        for obj in selection:
            print("\n" + "="*60)
            print("处理模型: {}".format(obj))
            
            shapes = cmds.listRelatives(obj, shapes=True, type='mesh', fullPath=True)
            if not shapes:
                cmds.warning("对象 {} 不是网格模型，跳过。".format(obj))
                continue
            
            mesh = shapes[0]
            
            cmds.select(obj, replace=True)
            separated = cmds.polySeparate(mesh, constructionHistory=False)
            
            if separated and len(separated) > 1:
                print("  ✅ 分离为 {} 个独立部分".format(len(separated)))
                
                if self.clean_hierarchy:
                    for sep_obj in separated:
                        if cmds.objExists(sep_obj):
                            try:
                                cmds.parent(sep_obj, world=True)
                            except:
                                pass
                
                if cmds.objExists(obj):
                    try:
                        cmds.delete(obj)
                    except:
                        pass
                
                all_separated.extend(separated)
            else:
                print("  ℹ️  模型是单一连续的，无需分离")
        
        if all_separated:
            cmds.select(all_separated, replace=True)
            
            cmds.inViewMessage(
                amg='已分离为 {} 个独立对象'.format(len(all_separated)),
                pos='midCenter',
                fade=True,
                fadeStayTime=2000,
                fadeOutTime=500
            )
            
            print("\n" + "="*60)
            print("松散部分分离完成！")
            print("生成对象数: {}".format(len(all_separated)))
            print("="*60 + "\n")
            
        return all_separated
    
    def extract_selection(self, custom_suffix=None):
        """
        提取选中的面（类似分离，但保留原模型）
        """
        return self.separate_selection(
            delete_original=False, 
            clean_hierarchy=self.clean_hierarchy, 
            delete_history=self.delete_history,
            custom_suffix=custom_suffix
        )
    
    def create_ui(self):
        """创建用户界面"""
        if cmds.window(self.window_name, exists=True):
            cmds.deleteUI(self.window_name)
        
        window = cmds.window(
            self.window_name,
            title="智能分离与合并工具",
            widthHeight=(380, 480),
            sizeable=True
        )
        
        main_layout = cmds.columnLayout(
            adjustableColumn=True, 
            rowSpacing=10, 
            columnAttach=('both', 15)
        )
        
        cmds.separator(height=10, style='none')
        
        # 标题
        cmds.text(
            label="智能分离与合并工具", 
            font="boldLabelFont", 
            height=35,
            backgroundColor=(0.3, 0.35, 0.45)
        )
        
        cmds.separator(height=10, style='in')
        
        # 命名后缀设置
        cmds.frameLayout(
            label="命名后缀", 
            collapsable=False,
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=10
        )
        
        cmds.columnLayout(adjustableColumn=True, rowSpacing=8)
        
        # 分离后缀
        cmds.rowLayout(numberOfColumns=2, columnWidth2=(100, 250), columnAttach=[(1, 'left', 5), (2, 'left', 5)])
        cmds.text(label="分离后缀:", align='left', width=95)
        self.suffix_field_separate = cmds.textField(
            text=self.separate_suffix,
            width=245,
            annotation="分离后的对象名称后缀，例如：separated、sep、part等",
            changeCommand=lambda x: setattr(self, 'separate_suffix', x)
        )
        cmds.setParent('..')
        
        # 合并后缀
        cmds.rowLayout(numberOfColumns=2, columnWidth2=(100, 250), columnAttach=[(1, 'left', 5), (2, 'left', 5)])
        cmds.text(label="合并后缀:", align='left', width=95)
        self.suffix_field_combine = cmds.textField(
            text=self.combine_suffix,
            width=245,
            annotation="合并后的对象名称后缀，例如：combined、merge、union等",
            changeCommand=lambda x: setattr(self, 'combine_suffix', x)
        )
        cmds.setParent('..')
        
        cmds.setParent('..')
        cmds.setParent('..')
        
        cmds.separator(height=10, style='none')
        
        # 操作选项
        cmds.frameLayout(
            label="选项", 
            collapsable=False,
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=10
        )
        
        cmds.columnLayout(adjustableColumn=True, rowSpacing=8)
        
        cmds.checkBox(
            label="清理层级结构（移除多余的组）",
            value=self.clean_hierarchy,
            changeCommand=lambda x: setattr(self, 'clean_hierarchy', x),
            annotation="操作后自动清理多余的组和transform节点"
        )
        
        cmds.checkBox(
            label="删除历史记录",
            value=self.delete_history,
            changeCommand=lambda x: setattr(self, 'delete_history', x),
            annotation="操作后删除构造历史记录"
        )
        
        cmds.setParent('..')
        cmds.setParent('..')
        
        cmds.separator(height=10, style='none')
        
        # 分离操作
        cmds.frameLayout(
            label="分离操作", 
            collapsable=False,
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=10
        )
        
        cmds.columnLayout(adjustableColumn=True, rowSpacing=8)
        
        cmds.button(
            label="分离选中的面（P）",
            height=45,
            backgroundColor=(0.5, 0.6, 0.7),
            annotation="将选中的面分离为新对象，并从原模型中删除",
            command=lambda x: self.separate_selection(
                delete_original=True,
                clean_hierarchy=self.clean_hierarchy,
                delete_history=self.delete_history,
                custom_suffix=cmds.textField(self.suffix_field_separate, query=True, text=True)
            )
        )
        
        cmds.button(
            label="提取选中的面（保留原始）",
            height=40,
            backgroundColor=(0.6, 0.7, 0.5),
            annotation="提取选中的面为新对象，保留原模型",
            command=lambda x: self.separate_selection(
                delete_original=False,
                clean_hierarchy=self.clean_hierarchy,
                delete_history=self.delete_history,
                custom_suffix=cmds.textField(self.suffix_field_separate, query=True, text=True)
            )
        )
        
        cmds.button(
            label="按松散部分分离",
            height=40,
            backgroundColor=(0.7, 0.5, 0.6),
            annotation="将选中的模型按不连接的部分自动分离",
            command=lambda x: self.separate_by_loose_parts()
        )
        
        cmds.setParent('..')
        cmds.setParent('..')
        
        cmds.separator(height=5, style='in')
        
        # 合并操作
        cmds.frameLayout(
            label="合并操作", 
            collapsable=False,
            borderStyle='etchedIn',
            marginWidth=10,
            marginHeight=10
        )
        
        cmds.columnLayout(adjustableColumn=True, rowSpacing=8)
        
        cmds.button(
            label="合并选中的对象（Ctrl+J）",
            height=45,
            backgroundColor=(0.7, 0.6, 0.5),
            annotation="将选中的多个对象合并为一个，自动清理层级",
            command=lambda x: self.combine_selection(
                clean_hierarchy=self.clean_hierarchy,
                delete_history=self.delete_history,
                custom_suffix=cmds.textField(self.suffix_field_combine, query=True, text=True)
            )
        )
        
        cmds.setParent('..')
        cmds.setParent('..')
        
        cmds.separator(height=5, style='none')
        
        cmds.showWindow(window)
    
    def show_ui(self):
        """显示UI"""
        self.create_ui()


# 全局工具实例
smart_tool = SmartSeparateCombineTool()


def separate_faces():
    """分离选中的面（快捷函数）"""
    return smart_tool.separate_selection(
        delete_original=True,
        clean_hierarchy=True,
        delete_history=True
    )


def extract_faces():
    """提取选中的面（快捷函数）"""
    return smart_tool.extract_selection()


def separate_loose_parts():
    """按松散部分分离（快捷函数）"""
    return smart_tool.separate_by_loose_parts()


def combine_objects():
    """合并选中的对象（快捷函数）"""
    return smart_tool.combine_selection(
        clean_hierarchy=True,
        delete_history=True
    )


def show_ui():
    """显示UI窗口（快捷函数）"""
    smart_tool.show_ui()


# 主函数
if __name__ == "__main__":
    show_ui()
