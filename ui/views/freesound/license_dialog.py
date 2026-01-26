"""
License Confirmation Dialog

Dialog for confirming license terms before downloading.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gdk

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundSound,
    FreesoundLicense,
    LICENSE_INFO,
)


class LicenseConfirmDialog(Adw.Dialog):
    """
    Dialog for confirming license terms before download.
    
    Shows:
    - Sound name and author
    - License type and requirements
    - Attribution text with copy button
    """
    
    __gsignals__ = {
        'confirmed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'cancelled': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, sound: FreesoundSound):
        super().__init__()
        
        self.sound = sound
        self._build_ui()
    
    def _build_ui(self):
        """Build the dialog UI."""
        self.set_title("版权协议确认")
        self.set_content_width(500)
        self.set_content_height(400)
        
        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        
        # Sound info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Name
        name = self.sound.name_zh or self.sound.name
        name_label = Gtk.Label(label=name)
        name_label.add_css_class('title-2')
        name_label.set_xalign(0)
        info_box.append(name_label)
        
        # Author
        author_label = Gtk.Label(label=f"作者: {self.sound.username}")
        author_label.add_css_class('dim-label')
        author_label.set_xalign(0)
        info_box.append(author_label)
        
        content.append(info_box)
        
        # License card
        license_card = self._build_license_card()
        content.append(license_card)
        
        # Attribution section
        if self.sound.requires_attribution:
            attribution_section = self._build_attribution_section()
            content.append(attribution_section)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(16)
        
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect('clicked', self._on_cancel_clicked)
        button_box.append(cancel_btn)
        
        confirm_btn = Gtk.Button(label="确认下载")
        confirm_btn.add_css_class('suggested-action')
        confirm_btn.connect('clicked', self._on_confirm_clicked)
        button_box.append(confirm_btn)
        
        content.append(button_box)
        
        self.set_child(content)
    
    def _build_license_card(self) -> Gtk.Widget:
        """Build the license information card."""
        license_type = self.sound.license_type
        info = LICENSE_INFO.get(license_type, LICENSE_INFO[FreesoundLicense.CC_BY])
        
        frame = Gtk.Frame()
        frame.add_css_class('card')
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        
        # License name with icon
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        icon = Gtk.Label(label="📜")
        header.append(icon)
        
        license_name = Gtk.Label(label=info['name_zh'])
        license_name.add_css_class('heading')
        header.append(license_name)
        
        box.append(header)
        
        # Requirements list
        requirements = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Commercial use
        commercial_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if info['commercial']:
            commercial_icon = Gtk.Label(label="✅")
            commercial_text = Gtk.Label(label="可商业使用")
        else:
            commercial_icon = Gtk.Label(label="❌")
            commercial_text = Gtk.Label(label="仅限非商业使用")
            commercial_text.add_css_class('error')
        commercial_row.append(commercial_icon)
        commercial_row.append(commercial_text)
        requirements.append(commercial_row)
        
        # Modification
        modify_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        modify_icon = Gtk.Label(label="✅")
        modify_text = Gtk.Label(label="可修改和再创作")
        modify_row.append(modify_icon)
        modify_row.append(modify_text)
        requirements.append(modify_row)
        
        # Attribution
        if info['attribution']:
            attr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            attr_icon = Gtk.Label(label="⚠️")
            attr_text = Gtk.Label(label="必须标注原作者")
            attr_text.add_css_class('warning')
            attr_row.append(attr_icon)
            attr_row.append(attr_text)
            requirements.append(attr_row)
        
        box.append(requirements)
        
        # Description
        desc_label = Gtk.Label(label=info['description_zh'])
        desc_label.add_css_class('dim-label')
        desc_label.set_xalign(0)
        desc_label.set_wrap(True)
        box.append(desc_label)
        
        frame.set_child(box)
        return frame
    
    def _build_attribution_section(self) -> Gtk.Widget:
        """Build the attribution section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Label
        label = Gtk.Label(label="署名格式:")
        label.add_css_class('heading')
        label.set_xalign(0)
        box.append(label)
        
        # Attribution text in a frame
        frame = Gtk.Frame()
        
        attr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        attr_box.set_margin_top(12)
        attr_box.set_margin_bottom(12)
        attr_box.set_margin_start(12)
        attr_box.set_margin_end(12)
        
        # Attribution text
        attr_text = Gtk.Label(label=self.sound.attribution_text)
        attr_text.set_xalign(0)
        attr_text.set_wrap(True)
        attr_text.set_hexpand(True)
        attr_text.set_selectable(True)
        attr_box.append(attr_text)
        
        # Copy button
        copy_btn = Gtk.Button()
        copy_btn.set_icon_name('edit-copy-symbolic')
        copy_btn.add_css_class('flat')
        copy_btn.set_tooltip_text('复制作者信息')
        copy_btn.set_valign(Gtk.Align.START)
        copy_btn.connect('clicked', self._on_copy_clicked)
        attr_box.append(copy_btn)
        
        frame.set_child(attr_box)
        box.append(frame)
        
        return box
    
    def _on_copy_clicked(self, button):
        """Copy attribution text to clipboard."""
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self.sound.attribution_text)
        
        # Show toast
        toast = Adw.Toast.new("已复制作者信息")
        toast.set_timeout(2)
        
        # Find the toast overlay (if available)
        parent = self.get_parent()
        while parent:
            if isinstance(parent, Adw.ToastOverlay):
                parent.add_toast(toast)
                break
            parent = parent.get_parent()
    
    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit('cancelled')
        self.close()
    
    def _on_confirm_clicked(self, button):
        """Handle confirm button click."""
        self.emit('confirmed', self.sound)
        self.close()


class BatchLicenseDialog(Adw.Dialog):
    """
    Dialog for confirming licenses for batch download.
    
    Shows summary of license types in the batch.
    """
    
    __gsignals__ = {
        'confirmed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'cancelled': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, sounds: list):
        super().__init__()
        
        self.sounds = sounds
        self._build_ui()
    
    def _build_ui(self):
        """Build the dialog UI."""
        self.set_title("批量下载确认")
        self.set_content_width(450)
        self.set_content_height(350)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        
        # Summary
        summary_label = Gtk.Label(label=f"即将下载 {len(self.sounds)} 个音效")
        summary_label.add_css_class('title-2')
        content.append(summary_label)
        
        # License breakdown
        license_counts = {}
        non_commercial = []
        
        for sound in self.sounds:
            license_type = sound.license_type
            license_counts[license_type] = license_counts.get(license_type, 0) + 1
            if not sound.allows_commercial:
                non_commercial.append(sound)
        
        # License list
        list_box = Gtk.ListBox()
        list_box.add_css_class('boxed-list')
        
        for license_type, count in license_counts.items():
            info = LICENSE_INFO.get(license_type, LICENSE_INFO[FreesoundLicense.CC_BY])
            
            row = Adw.ActionRow()
            row.set_title(info['name_zh'])
            row.set_subtitle(f"{count} 个音效")
            
            # Badge
            badge = Gtk.Label(label=str(count))
            badge.add_css_class('badge')
            if info['commercial']:
                badge.add_css_class('success')
            else:
                badge.add_css_class('warning')
            row.add_suffix(badge)
            
            list_box.append(row)
        
        content.append(list_box)
        
        # Warning for non-commercial
        if non_commercial:
            warning_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            warning_box.add_css_class('warning')
            
            warning_icon = Gtk.Image.new_from_icon_name('dialog-warning-symbolic')
            warning_box.append(warning_icon)
            
            warning_text = Gtk.Label(
                label=f"注意: {len(non_commercial)} 个音效仅限非商业使用"
            )
            warning_text.set_wrap(True)
            warning_box.append(warning_text)
            
            content.append(warning_box)
        
        # Attribution note
        attr_note = Gtk.Label(
            label="下载后请查看各音效的署名要求"
        )
        attr_note.add_css_class('dim-label')
        content.append(attr_note)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(16)
        
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect('clicked', self._on_cancel_clicked)
        button_box.append(cancel_btn)
        
        confirm_btn = Gtk.Button(label=f"下载 {len(self.sounds)} 个音效")
        confirm_btn.add_css_class('suggested-action')
        confirm_btn.connect('clicked', self._on_confirm_clicked)
        button_box.append(confirm_btn)
        
        content.append(button_box)
        
        self.set_child(content)
    
    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit('cancelled')
        self.close()
    
    def _on_confirm_clicked(self, button):
        """Handle confirm button click."""
        self.emit('confirmed', self.sounds)
        self.close()
