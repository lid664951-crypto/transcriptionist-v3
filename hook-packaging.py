# PyInstaller hook for packaging module
from PyInstaller.utils.hooks import collect_submodules

# Collect all submodules of packaging
hiddenimports = collect_submodules('packaging')
