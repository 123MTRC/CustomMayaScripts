# -*- coding: utf-8 -*-
"""
Maya历史清理工具
适用于Maya 2022及以上版本
功能：快速清理模型历史，提升编辑流畅度
"""

import maya.cmds as cmds
import maya.mel as mel

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt

import maya.OpenMayaUI as omui
try:
    from shiboken2 import wrapInstance
except ImportError:
    from shiboken6 import wrapInstance


def get_maya_main_window():
    """获取Maya主窗口"""
    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)


class HistoryCleanerUI(QtWidgets.QDialog):
    """历史清理工具UI"""
    
    WINDOW_TITLE = "Maya历史清理工具"
    
    def __init__(self, parent=get_maya_main_window()):
        super(HistoryCleanerUI, self).__init__(parent)
        
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setWindowFlags(self.windowFlags() ^ Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)
        
        # 自动清理定时器
        self.auto_clean_timer = QtCore.QTimer()
        self.auto_clean_timer.timeout.connect(self.auto_clean_history)
        
        self.create_widgets()
        self.create_layouts()
        self.create_connections()
        
        # 加载设置
        self.load_settings()
    
    def create_widgets(self):
        """创建UI控件"""
        # === 信息显示区域 ===
        self.info_group = QtWidgets.QGroupBox("场景信息")
        self.scene_objects_label = QtWidgets.QLabel("场景物体数量: --")
        self.history_objects_label = QtWidgets.QLabel("有历史的物体: --")
        self.refresh_info_btn = QtWidgets.QPushButton("刷新信息")
        self.refresh_info_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        
        # === 清理选项 ===
        self.options_group = QtWidgets.QGroupBox("清理选项")
        self.clean_selected_radio = QtWidgets.QRadioButton("清理选中物体")
        self.clean_all_radio = QtWidgets.QRadioButton("清理所有物体")
        self.clean_all_radio.setChecked(True)
        
        # 清理类型选项
        self.delete_history_cb = QtWidgets.QCheckBox("删除历史 (Delete History)")
        self.delete_history_cb.setChecked(True)
        self.delete_history_cb.setToolTip("删除构造历史，这是最常用的清理方式")
        
        self.freeze_transform_cb = QtWidgets.QCheckBox("冻结变换 (Freeze Transformations)")
        self.freeze_transform_cb.setToolTip("将变换值归零，通常在清理历史前执行")
        
        self.delete_empty_groups_cb = QtWidgets.QCheckBox("删除空组")
        self.delete_empty_groups_cb.setToolTip("删除场景中的空组节点")
        
        self.optimize_scene_cb = QtWidgets.QCheckBox("优化场景大小")
        self.optimize_scene_cb.setToolTip("执行场景优化命令")
        
        # === 执行按钮 ===
        self.clean_now_btn = QtWidgets.QPushButton("立即清理")
        self.clean_now_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        # === 自动清理 ===
        self.auto_clean_group = QtWidgets.QGroupBox("自动清理")
        self.auto_clean_enabled_cb = QtWidgets.QCheckBox("启用自动清理")
        self.auto_clean_interval_label = QtWidgets.QLabel("清理间隔 (秒):")
        self.auto_clean_interval_spin = QtWidgets.QSpinBox()
        self.auto_clean_interval_spin.setRange(10, 600)
        self.auto_clean_interval_spin.setValue(60)
        self.auto_clean_interval_spin.setSuffix(" 秒")
        
        # === 快捷操作 ===
        self.quick_actions_group = QtWidgets.QGroupBox("快捷操作")
        self.quick_clean_selected_btn = QtWidgets.QPushButton("清理选中")
        self.quick_clean_all_btn = QtWidgets.QPushButton("清理全部")
        self.quick_optimize_btn = QtWidgets.QPushButton("优化场景")
        
        # === 日志区域 ===
        self.log_group = QtWidgets.QGroupBox("操作日志")
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.clear_log_btn = QtWidgets.QPushButton("清空日志")
        
        # === 底部按钮 ===
        self.close_btn = QtWidgets.QPushButton("关闭")
    
    def create_layouts(self):
        """创建布局"""
        main_layout = QtWidgets.QVBoxLayout(self)
        
        # 信息显示布局
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.addWidget(self.scene_objects_label)
        info_layout.addWidget(self.history_objects_label)
        info_layout.addWidget(self.refresh_info_btn)
        self.info_group.setLayout(info_layout)
        
        # 清理选项布局
        options_layout = QtWidgets.QVBoxLayout()
        options_layout.addWidget(self.clean_selected_radio)
        options_layout.addWidget(self.clean_all_radio)
        options_layout.addWidget(QtWidgets.QLabel(""))  # 分隔
        options_layout.addWidget(self.delete_history_cb)
        options_layout.addWidget(self.freeze_transform_cb)
        options_layout.addWidget(self.delete_empty_groups_cb)
        options_layout.addWidget(self.optimize_scene_cb)
        self.options_group.setLayout(options_layout)
        
        # 自动清理布局
        auto_clean_layout = QtWidgets.QVBoxLayout()
        auto_clean_layout.addWidget(self.auto_clean_enabled_cb)
        interval_layout = QtWidgets.QHBoxLayout()
        interval_layout.addWidget(self.auto_clean_interval_label)
        interval_layout.addWidget(self.auto_clean_interval_spin)
        auto_clean_layout.addLayout(interval_layout)
        self.auto_clean_group.setLayout(auto_clean_layout)
        
        # 快捷操作布局
        quick_actions_layout = QtWidgets.QHBoxLayout()
        quick_actions_layout.addWidget(self.quick_clean_selected_btn)
        quick_actions_layout.addWidget(self.quick_clean_all_btn)
        quick_actions_layout.addWidget(self.quick_optimize_btn)
        self.quick_actions_group.setLayout(quick_actions_layout)
        
        # 日志布局
        log_layout = QtWidgets.QVBoxLayout()
        log_layout.addWidget(self.log_text)
        log_layout.addWidget(self.clear_log_btn)
        self.log_group.setLayout(log_layout)
        
        # 主布局组装
        main_layout.addWidget(self.info_group)
        main_layout.addWidget(self.options_group)
        main_layout.addWidget(self.clean_now_btn)
        main_layout.addWidget(self.auto_clean_group)
        main_layout.addWidget(self.quick_actions_group)
        main_layout.addWidget(self.log_group)
        main_layout.addWidget(self.close_btn)
    
    def create_connections(self):
        """创建信号连接"""
        self.refresh_info_btn.clicked.connect(self.refresh_scene_info)
        self.clean_now_btn.clicked.connect(self.clean_history)
        self.auto_clean_enabled_cb.toggled.connect(self.toggle_auto_clean)
        self.auto_clean_interval_spin.valueChanged.connect(self.update_auto_clean_interval)
        
        self.quick_clean_selected_btn.clicked.connect(self.quick_clean_selected)
        self.quick_clean_all_btn.clicked.connect(self.quick_clean_all)
        self.quick_optimize_btn.clicked.connect(self.quick_optimize)
        
        self.clear_log_btn.clicked.connect(self.log_text.clear)
        self.close_btn.clicked.connect(self.close)
    
    def log_message(self, message, level="INFO"):
        """记录日志消息"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        if level == "SUCCESS":
            color = "green"
        elif level == "WARNING":
            color = "orange"
        elif level == "ERROR":
            color = "red"
        else:
            color = "black"
        
        formatted_msg = f'<span style="color:{color}">[{timestamp}] {message}</span>'
        self.log_text.append(formatted_msg)
        
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def refresh_scene_info(self):
        """刷新场景信息"""
        try:
            # 获取所有网格物体
            all_meshes = cmds.ls(type='mesh', long=True) or []
            
            # 过滤掉中间形状和非渲染节点
            scene_meshes = [m for m in all_meshes if not cmds.getAttr(m + '.intermediateObject')]
            
            # 获取有历史的物体
            history_count = 0
            for mesh in scene_meshes:
                history = cmds.listHistory(mesh, pruneDagObjects=True) or []
                if len(history) > 1:  # 超过自身节点就算有历史
                    history_count += 1
            
            self.scene_objects_label.setText(f"场景物体数量: {len(scene_meshes)}")
            self.history_objects_label.setText(f"有历史的物体: {history_count}")
            
            self.log_message(f"刷新完成: {len(scene_meshes)} 个物体, {history_count} 个有历史")
        except Exception as e:
            self.log_message(f"刷新场景信息失败: {str(e)}", "ERROR")
    
    def clean_history(self):
        """执行历史清理"""
        try:
            # 确定清理范围
            if self.clean_selected_radio.isChecked():
                selected = cmds.ls(selection=True, long=True)
                if not selected:
                    self.log_message("没有选中任何物体", "WARNING")
                    return
                objects_to_clean = selected
                scope = "选中的物体"
            else:
                objects_to_clean = cmds.ls(type='transform', long=True) or []
                scope = "所有物体"
            
            cleaned_count = 0
            error_count = 0
            
            # 冻结变换
            if self.freeze_transform_cb.isChecked():
                for obj in objects_to_clean:
                    try:
                        if cmds.objExists(obj):
                            cmds.makeIdentity(obj, apply=True, translate=True, rotate=True, scale=True)
                            cleaned_count += 1
                    except:
                        error_count += 1
                self.log_message(f"冻结变换完成: {cleaned_count} 个物体", "SUCCESS")
                cleaned_count = 0
            
            # 删除历史
            if self.delete_history_cb.isChecked():
                for obj in objects_to_clean:
                    try:
                        if cmds.objExists(obj):
                            # 检查是否有历史
                            history = cmds.listHistory(obj, pruneDagObjects=True) or []
                            if len(history) > 1:
                                cmds.delete(obj, constructionHistory=True)
                                cleaned_count += 1
                    except:
                        error_count += 1
                self.log_message(f"删除历史完成: {cleaned_count} 个物体", "SUCCESS")
            
            # 删除空组
            if self.delete_empty_groups_cb.isChecked():
                empty_groups = []
                all_transforms = cmds.ls(type='transform', long=True) or []
                for transform in all_transforms:
                    try:
                        if cmds.objExists(transform):
                            children = cmds.listRelatives(transform, children=True, fullPath=True) or []
                            if not children:
                                empty_groups.append(transform)
                    except:
                        pass
                
                if empty_groups:
                    try:
                        cmds.delete(empty_groups)
                        self.log_message(f"删除空组: {len(empty_groups)} 个", "SUCCESS")
                    except:
                        pass
            
            # 优化场景
            if self.optimize_scene_cb.isChecked():
                try:
                    mel.eval('cleanUpScene 3;')
                    self.log_message("场景优化完成", "SUCCESS")
                except Exception as e:
                    self.log_message(f"场景优化失败: {str(e)}", "ERROR")
            
            # 刷新信息
            self.refresh_scene_info()
            
            if error_count > 0:
                self.log_message(f"清理 {scope} 完成，但有 {error_count} 个物体出错", "WARNING")
            else:
                self.log_message(f"清理 {scope} 完成", "SUCCESS")
                
        except Exception as e:
            self.log_message(f"清理失败: {str(e)}", "ERROR")
    
    def toggle_auto_clean(self, enabled):
        """切换自动清理"""
        if enabled:
            interval = self.auto_clean_interval_spin.value() * 1000  # 转换为毫秒
            self.auto_clean_timer.start(interval)
            self.log_message(f"自动清理已启用，间隔 {self.auto_clean_interval_spin.value()} 秒", "SUCCESS")
        else:
            self.auto_clean_timer.stop()
            self.log_message("自动清理已停用", "INFO")
    
    def update_auto_clean_interval(self, value):
        """更新自动清理间隔"""
        if self.auto_clean_enabled_cb.isChecked():
            self.auto_clean_timer.stop()
            self.auto_clean_timer.start(value * 1000)
            self.log_message(f"自动清理间隔已更新为 {value} 秒", "INFO")
    
    def auto_clean_history(self):
        """自动清理历史"""
        self.log_message("执行自动清理...", "INFO")
        self.clean_history()
    
    def quick_clean_selected(self):
        """快速清理选中"""
        selected = cmds.ls(selection=True)
        if not selected:
            self.log_message("没有选中任何物体", "WARNING")
            return
        
        try:
            for obj in selected:
                if cmds.objExists(obj):
                    cmds.delete(obj, constructionHistory=True)
            self.log_message(f"快速清理选中: {len(selected)} 个物体", "SUCCESS")
            self.refresh_scene_info()
        except Exception as e:
            self.log_message(f"快速清理失败: {str(e)}", "ERROR")
    
    def quick_clean_all(self):
        """快速清理全部"""
        try:
            all_objects = cmds.ls(type='transform')
            cleaned = 0
            for obj in all_objects:
                try:
                    if cmds.objExists(obj):
                        cmds.delete(obj, constructionHistory=True)
                        cleaned += 1
                except:
                    pass
            self.log_message(f"快速清理全部: {cleaned} 个物体", "SUCCESS")
            self.refresh_scene_info()
        except Exception as e:
            self.log_message(f"快速清理全部失败: {str(e)}", "ERROR")
    
    def quick_optimize(self):
        """快速优化场景"""
        try:
            mel.eval('cleanUpScene 3;')
            self.log_message("快速优化场景完成", "SUCCESS")
            self.refresh_scene_info()
        except Exception as e:
            self.log_message(f"快速优化失败: {str(e)}", "ERROR")
    
    def showEvent(self, event):
        """窗口显示时刷新信息"""
        super(HistoryCleanerUI, self).showEvent(event)
        self.refresh_scene_info()
    
    def closeEvent(self, event):
        """关闭窗口时保存设置并停止定时器"""
        self.auto_clean_timer.stop()
        self.save_settings()
        super(HistoryCleanerUI, self).closeEvent(event)
    
    def save_settings(self):
        """保存设置到Maya选项变量"""
        cmds.optionVar(intValue=('historyCleanerAutoEnabled', int(self.auto_clean_enabled_cb.isChecked())))
        cmds.optionVar(intValue=('historyCleanerAutoInterval', self.auto_clean_interval_spin.value()))
        cmds.optionVar(intValue=('historyCleanerDeleteHistory', int(self.delete_history_cb.isChecked())))
        cmds.optionVar(intValue=('historyCleanerFreezeTransform', int(self.freeze_transform_cb.isChecked())))
        cmds.optionVar(intValue=('historyCleanerDeleteEmptyGroups', int(self.delete_empty_groups_cb.isChecked())))
        cmds.optionVar(intValue=('historyCleanerOptimizeScene', int(self.optimize_scene_cb.isChecked())))
    
    def load_settings(self):
        """从Maya选项变量加载设置"""
        if cmds.optionVar(exists='historyCleanerAutoEnabled'):
            self.auto_clean_enabled_cb.setChecked(bool(cmds.optionVar(query='historyCleanerAutoEnabled')))
        
        if cmds.optionVar(exists='historyCleanerAutoInterval'):
            self.auto_clean_interval_spin.setValue(cmds.optionVar(query='historyCleanerAutoInterval'))
        
        if cmds.optionVar(exists='historyCleanerDeleteHistory'):
            self.delete_history_cb.setChecked(bool(cmds.optionVar(query='historyCleanerDeleteHistory')))
        
        if cmds.optionVar(exists='historyCleanerFreezeTransform'):
            self.freeze_transform_cb.setChecked(bool(cmds.optionVar(query='historyCleanerFreezeTransform')))
        
        if cmds.optionVar(exists='historyCleanerDeleteEmptyGroups'):
            self.delete_empty_groups_cb.setChecked(bool(cmds.optionVar(query='historyCleanerDeleteEmptyGroups')))
        
        if cmds.optionVar(exists='historyCleanerOptimizeScene'):
            self.optimize_scene_cb.setChecked(bool(cmds.optionVar(query='historyCleanerOptimizeScene')))


def show_ui():
    """显示UI"""
    global history_cleaner_ui
    
    try:
        history_cleaner_ui.close()
        history_cleaner_ui.deleteLater()
    except:
        pass
    
    history_cleaner_ui = HistoryCleanerUI()
    history_cleaner_ui.show()
    
    return history_cleaner_ui


# 便捷函数：直接清理选中物体历史
def clean_selected():
    """快速清理选中物体的历史"""
    selected = cmds.ls(selection=True)
    if not selected:
        cmds.warning("没有选中任何物体")
        return
    
    try:
        for obj in selected:
            cmds.delete(obj, constructionHistory=True)
        cmds.inViewMessage(amg='清理完成: {} 个物体'.format(len(selected)), 
                          pos='midCenter', fade=True, fadeStayTime=1000)
        print("# 清理完成: {} 个物体".format(len(selected)))
    except Exception as e:
        cmds.warning("清理失败: {}".format(str(e)))


# 便捷函数：直接清理所有物体历史
def clean_all():
    """快速清理所有物体的历史"""
    try:
        all_objects = cmds.ls(type='transform')
        cleaned = 0
        for obj in all_objects:
            try:
                cmds.delete(obj, constructionHistory=True)
                cleaned += 1
            except:
                pass
        cmds.inViewMessage(amg='清理完成: {} 个物体'.format(cleaned), 
                          pos='midCenter', fade=True, fadeStayTime=1000)
        print("# 清理完成: {} 个物体".format(cleaned))
    except Exception as e:
        cmds.warning("清理失败: {}".format(str(e)))


if __name__ == "__main__":
    show_ui()
