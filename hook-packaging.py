# PyInstaller hook for packaging module (v26.0+)
# 根据实际安装的 packaging 模块收集子模块

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# 收集所有子模块（包括 licenses 子包）
hiddenimports = collect_submodules('packaging')

# 收集数据文件（如 licenses/_spdx.py 等）
datas = collect_data_files('packaging')
