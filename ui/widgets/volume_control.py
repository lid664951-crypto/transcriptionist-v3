"""
Volume Control Widget

GTK4 音量控制组件，包含音量滑块和静音按钮。
参考 Quod Libet 的 Volume 类实现。
"""

from __future__ import annotations

import logging
from typing import Optional, Callable

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GObject

logger = logging.getLogger(__name__)


class VolumeControl(Gtk.Box):
    """
    音量控制组件
    
    功能：
    - 音量滑块 (0-100%)
    - 静音按钮
    - 音量图标随音量变化
    """
    
    __gtype_name__ = "VolumeControl"
    
    __gsignals__ = {
        "volume-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
        "mute-toggled": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }
    
    # 音量图标
    ICON_MUTED = "audio-volume-muted-symbolic"
    ICON_LOW = "audio-volume-low-symbolic"
    ICON_MEDIUM = "audio-volume-medium-symbolic"
    ICON_HIGH = "audio-volume-high-symbolic"
    
    def __init__(self, orientation: Gtk.Orientation = Gtk.Orientation.HORIZONTAL):
        super().__init__(orientation=orientation, spacing=6)
        
        self._volume = 1.0  # 0.0 - 1.0
        self._muted = False
        self._updating = False  # 防止循环更新
        
        self._build_ui(orientation)
    
    def _build_ui(self, orientation: Gtk.Orientation) -> None:
        """构建UI"""
        # 静音按钮
        self._mute_button = Gtk.Button()
        self._mute_button.add_css_class("flat")
        self._mute_button.connect("clicked", self._on_mute_clicked)
        self._update_icon()
        self.append(self._mute_button)
        
        # 音量滑块
        if orientation == Gtk.Orientation.HORIZONTAL:
            self._scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 0, 100, 1
            )
            self._scale.set_size_request(100, -1)
        else:
            self._scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.VERTICAL, 0, 100, 1
            )
            self._scale.set_size_request(-1, 100)
            self._scale.set_inverted(True)
        
        self._scale.set_draw_value(False)
        self._scale.set_value(self._volume * 100)
        self._scale.connect("value-changed", self._on_scale_changed)
        self.append(self._scale)
    
    def _update_icon(self) -> None:
        """更新音量图标"""
        if self._muted or self._volume == 0:
            icon = self.ICON_MUTED
        elif self._volume < 0.33:
            icon = self.ICON_LOW
        elif self._volume < 0.66:
            icon = self.ICON_MEDIUM
        else:
            icon = self.ICON_HIGH
        
        self._mute_button.set_icon_name(icon)
    
    def _on_mute_clicked(self, button: Gtk.Button) -> None:
        """静音按钮点击"""
        self.set_muted(not self._muted)
        self.emit("mute-toggled", self._muted)
    
    def _on_scale_changed(self, scale: Gtk.Scale) -> None:
        """滑块值改变"""
        if self._updating:
            return
        
        value = scale.get_value() / 100
        self._volume = value
        self._update_icon()
        
        # 如果调整音量，自动取消静音
        if self._muted and value > 0:
            self._muted = False
            self.emit("mute-toggled", False)
        
        self.emit("volume-changed", value)
    
    def get_volume(self) -> float:
        """获取音量 (0.0 - 1.0)"""
        return self._volume
    
    def set_volume(self, volume: float) -> None:
        """设置音量 (0.0 - 1.0)"""
        self._volume = max(0.0, min(1.0, volume))
        self._updating = True
        self._scale.set_value(self._volume * 100)
        self._updating = False
        self._update_icon()
    
    def get_muted(self) -> bool:
        """获取静音状态"""
        return self._muted
    
    def set_muted(self, muted: bool) -> None:
        """设置静音状态"""
        self._muted = muted
        self._update_icon()
    
    def increase_volume(self, step: float = 0.05) -> None:
        """增加音量"""
        self.set_volume(self._volume + step)
        self.emit("volume-changed", self._volume)
    
    def decrease_volume(self, step: float = 0.05) -> None:
        """减少音量"""
        self.set_volume(self._volume - step)
        self.emit("volume-changed", self._volume)


class VolumePopover(Gtk.Popover):
    """
    音量弹出窗口
    
    点击音量按钮时显示的垂直音量滑块。
    """
    
    __gtype_name__ = "VolumePopover"
    
    def __init__(self):
        super().__init__()
        
        self._volume_control = VolumeControl(Gtk.Orientation.VERTICAL)
        self._volume_control.set_margin_top(12)
        self._volume_control.set_margin_bottom(12)
        self._volume_control.set_margin_start(6)
        self._volume_control.set_margin_end(6)
        
        self.set_child(self._volume_control)
    
    @property
    def volume_control(self) -> VolumeControl:
        """获取音量控制组件"""
        return self._volume_control


class VolumeButton(Gtk.MenuButton):
    """
    音量按钮
    
    点击显示音量弹出窗口。
    """
    
    __gtype_name__ = "VolumeButton"
    
    __gsignals__ = {
        "volume-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
        "mute-toggled": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }
    
    def __init__(self):
        super().__init__()
        
        self._volume = 1.0
        self._muted = False
        
        # 设置图标
        self._update_icon()
        self.add_css_class("flat")
        
        # 创建弹出窗口
        self._popover = VolumePopover()
        self.set_popover(self._popover)
        
        # 连接信号
        self._popover.volume_control.connect(
            "volume-changed", self._on_volume_changed
        )
        self._popover.volume_control.connect(
            "mute-toggled", self._on_mute_toggled
        )
    
    def _update_icon(self) -> None:
        """更新图标"""
        if self._muted or self._volume == 0:
            icon = VolumeControl.ICON_MUTED
        elif self._volume < 0.33:
            icon = VolumeControl.ICON_LOW
        elif self._volume < 0.66:
            icon = VolumeControl.ICON_MEDIUM
        else:
            icon = VolumeControl.ICON_HIGH
        
        self.set_icon_name(icon)
    
    def _on_volume_changed(self, control: VolumeControl, volume: float) -> None:
        """音量改变"""
        self._volume = volume
        self._update_icon()
        self.emit("volume-changed", volume)
    
    def _on_mute_toggled(self, control: VolumeControl, muted: bool) -> None:
        """静音切换"""
        self._muted = muted
        self._update_icon()
        self.emit("mute-toggled", muted)
    
    def get_volume(self) -> float:
        """获取音量"""
        return self._popover.volume_control.get_volume()
    
    def set_volume(self, volume: float) -> None:
        """设置音量"""
        self._volume = volume
        self._popover.volume_control.set_volume(volume)
        self._update_icon()
    
    def get_muted(self) -> bool:
        """获取静音状态"""
        return self._popover.volume_control.get_muted()
    
    def set_muted(self, muted: bool) -> None:
        """设置静音状态"""
        self._muted = muted
        self._popover.volume_control.set_muted(muted)
        self._update_icon()
