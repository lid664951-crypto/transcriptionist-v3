"""
Native Windows File Dialogs using pywin32
Provides true native multi-folder selection dialog
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# File Dialog Options (FOS)
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200


def select_folders_dialog(
    title: str = "选择文件夹",
    initial_dir: Optional[str] = None,
    parent_hwnd: Optional[int] = None
) -> List[str]:
    """
    Open native Windows dialog to select multiple folders.
    Uses pywin32 for reliable COM interface access.
    
    Args:
        title: Dialog window title
        initial_dir: Initial directory to open
        parent_hwnd: Parent window handle (optional)
    
    Returns:
        List of selected folder paths, empty list if cancelled
    """
    try:
        import pythoncom
        from win32com.shell import shell, shellcon
        import pywintypes
        
        # Initialize COM
        pythoncom.CoInitialize()
        
        try:
            # Define GUIDs manually (pywin32 doesn't expose these constants)
            CLSID_FileOpenDialog = pywintypes.IID("{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}")
            IID_IFileOpenDialog = pywintypes.IID("{d57c7288-d4ad-4768-be02-9d969532d960}")
            
            # Create FileOpenDialog instance
            file_dialog = pythoncom.CoCreateInstance(
                CLSID_FileOpenDialog,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                IID_IFileOpenDialog
            )
            
            # Set options: Pick Folders + Allow Multi-Select
            options = file_dialog.GetOptions()
            options |= FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT | FOS_FORCEFILESYSTEM
            file_dialog.SetOptions(options)
            
            # Set title
            if title:
                file_dialog.SetTitle(title)
            
            # Set initial directory (optional)
            if initial_dir:
                try:
                    folder_item = shell.SHCreateItemFromParsingName(
                        initial_dir, None, shell.IID_IShellItem
                    )
                    file_dialog.SetFolder(folder_item)
                except Exception:
                    pass  # Ignore if initial dir is invalid
            
            # Show dialog
            try:
                file_dialog.Show(parent_hwnd or 0)
            except pythoncom.com_error as e:
                # User cancelled (HRESULT_FROM_WIN32(ERROR_CANCELLED))
                if e.hresult == -2147023673:  # 0x800704C7
                    return []
                raise
            
            # Get results
            results = file_dialog.GetResults()
            count = results.GetCount()
            
            selected_paths = []
            for i in range(count):
                item = results.GetItemAt(i)
                # SIGDN_FILESYSPATH = 0x80058000
                path = item.GetDisplayName(shellcon.SIGDN_FILESYSPATH)
                selected_paths.append(path)
            
            return selected_paths
            
        finally:
            pythoncom.CoUninitialize()
            
    except ImportError:
        logger.warning("pywin32 not installed, falling back to Qt dialog")
        return []
    except Exception as e:
        logger.debug(f"Native dialog error: {e}, falling back to Qt dialog")
        return []


if __name__ == "__main__":
    # Test
    folders = select_folders_dialog("测试：选择多个文件夹")
    print(f"Selected folders: {folders}")
