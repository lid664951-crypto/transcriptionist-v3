"""
Translation item data structures for hierarchical translation.
Supports both files and folders with level tracking.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Dict


@dataclass
class TranslationItem:
    """
    翻译项（文件或文件夹）
    
    Attributes:
        path: 完整路径
        name: 原名称
        item_type: 'file' 或 'folder'
        parent_path: 父目录路径
        level: 层级深度（根目录为0）
        translated: 翻译结果
        status: 处理状态
        category: UCS分类（仅文件）
        subcategory: UCS子分类（仅文件）
        descriptor: UCS描述（仅文件）
        variation: UCS变体（仅文件）
    """
    path: str
    name: str
    item_type: str  # 'file' or 'folder'
    parent_path: str
    level: int
    translated: str = ""
    status: str = "待应用"
    # UCS fields (for files only)
    category: str = ""
    subcategory: str = ""
    descriptor: str = ""
    variation: str = ""


def collect_translation_items(file_paths: List[str], root_path: str = None) -> List[TranslationItem]:
    """
    收集所有需要翻译的文件和文件夹
    
    Args:
        file_paths: 文件路径列表
        root_path: 根目录路径（用于计算相对层级）
   
    Returns:
        包含文件和文件夹的 TranslationItem 列表
    """
    items = []
    folders_seen: Set[str] = set()
    
    # 自动检测根目录
    if root_path is None and file_paths:
        # 找到所有文件的最短公共父目录
        paths = [Path(p) for p in file_paths]
        root_path = str(paths[0].parent)
        for p in paths[1:]:
            # 向上查找公共父目录
            while not str(p).startswith(root_path):
                root_path = str(Path(root_path).parent)
        
        # FIX: Do NOT go one level up - we only want to include directories that
        # contain the selected files, not their parent directories
        # This prevents showing "软件测试" when user only selected its children
    
    root = Path(root_path) if root_path else None
    
    # 收集所有文件
    for file_path in file_paths:
        file_path_obj = Path(file_path)
        
        # 计算层级
        if root:
            try:
                relative = file_path_obj.relative_to(root)
                level = len(relative.parts)
            except ValueError:
                level = len(file_path_obj.parts)
        else:
            level = len(file_path_obj.parts)
        
        items.append(TranslationItem(
            path=str(file_path_obj),
            name=file_path_obj.name,
            item_type='file',
            parent_path=str(file_path_obj.parent),
            level=level
        ))
        
        # 收集所有父文件夹
        current = file_path_obj.parent
        while current != root and current != current.parent:
            folder_path = str(current)
            
            if folder_path not in folders_seen:
                folders_seen.add(folder_path)
                
                # 计算文件夹层级
                if root:
                    try:
                        relative = current.relative_to(root)
                        folder_level = len(relative.parts)
                    except ValueError:
                        folder_level = len(current.parts) - 1
                else:
                    folder_level = len(current.parts) - 1
                
                items.append(TranslationItem(
                    path=folder_path,
                    name=current.name,
                    item_type='folder',
                    parent_path=str(current.parent),
                    level=folder_level
                ))
            
            current = current.parent
    
    # 按层级排序（用于后续处理）
    items.sort(key=lambda x: (x.level, x.item_type == 'file', x.path))
    
    return items


def group_items_by_parent(items: List[TranslationItem]) -> Dict[str, List[TranslationItem]]:
    """
    按父目录分组翻译项（用于构建树形结构）
    
    Args:
        items: 翻译项列表
        
    Returns:
        parent_path -> children 的字典
    """
    grouped: Dict[str, List[TranslationItem]] = {}
    
    for item in items:
        parent = item.parent_path
        if parent not in grouped:
            grouped[parent] = []
        grouped[parent].append(item)
    
    return grouped
