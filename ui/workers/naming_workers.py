import csv
import logging
from pathlib import Path
from PySide6.QtCore import Signal, QObject

logger = logging.getLogger(__name__)

class GlossaryLoadWorker(QObject):
    """术语库加载工作线程"""
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(int, int)
    
    def __init__(self, file_path: str, file_type: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_type = file_type  # 'csv' or 'excel'
    
    def run(self):
        try:
            glossary = {}
            
            if self.file_type == 'csv':
                glossary = self._load_csv()
            elif self.file_type == 'excel':
                glossary = self._load_excel()
            
            self.finished.emit(glossary)
        except Exception as e:
            logger.error(f"Failed to load glossary: {e}")
            self.error.emit(str(e))
    
    def _load_csv(self) -> dict:
        glossary = {}
        with open(self.file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # 跳过表头
            for row in reader:
                if len(row) >= 2:
                    en_term = row[0].strip()
                    zh_term = row[1].strip()
                    if en_term and zh_term:
                        glossary[en_term] = zh_term
        return glossary

    def _load_excel(self) -> dict:
        import pandas as pd
        
        glossary = {}
        # 尝试读取 Excel (通常表头在第2行)
        df = pd.read_excel(self.file_path, sheet_name=0, header=1)
        
        # 查找中英文列
        zh_cat_col = zh_sub_col = None
        en_cat_col = en_sub_col = None
        
        for col in df.columns:
            col_lower = str(col).lower()
            if 'category_zh' in col_lower or col == 'Category_zh':
                zh_cat_col = col
            elif 'subcategory_zh' in col_lower or col == 'SubCategory_zh':
                zh_sub_col = col
            elif col == 'Category':
                en_cat_col = col
            elif col == 'SubCategory':
                en_sub_col = col
        
        # 导入Category
        if en_cat_col and zh_cat_col:
            for _, row in df.iterrows():
                en_cat = str(row.get(en_cat_col, '')).strip()
                zh_cat = str(row.get(zh_cat_col, '')).strip()
                if en_cat and zh_cat and en_cat != 'nan' and zh_cat != 'nan':
                    if en_cat not in glossary:
                        glossary[en_cat] = zh_cat
        
        # 导入SubCategory
        if en_sub_col and zh_sub_col:
            for _, row in df.iterrows():
                en_sub = str(row.get(en_sub_col, '')).strip()
                zh_sub = str(row.get(zh_sub_col, '')).strip()
                if en_sub and zh_sub and en_sub != 'nan' and zh_sub != 'nan':
                    if en_sub not in glossary:
                        glossary[en_sub] = zh_sub
        
        return glossary
