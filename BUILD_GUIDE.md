# 音译家 v1.0.0 - 打包构建指南

## 📋 目录
1. [打包前检查](#打包前检查)
2. [推荐打包方案](#推荐打包方案)
3. [详细步骤](#详细步骤)
4. [常见问题](#常见问题)
5. [测试清单](#测试清单)

---

## 🔍 打包前检查

### 1. 项目依赖检查

#### 核心依赖（必须）
- ✅ **PySide6** >= 6.6.0 - Qt GUI 框架
- ✅ **qfluentwidgets** >= 1.5.0 - Fluent Design 组件
- ✅ **SQLAlchemy** >= 2.0.0 - 数据库 ORM
- ✅ **mutagen** >= 1.47.0 - 音频元数据
- ✅ **numpy** >= 1.24.0 - 数值计算
- ✅ **aiohttp** >= 3.9.0 - 异步 HTTP

#### 可选依赖（AI 功能）
- ⚠️ **torch** - PyTorch（AI 模型，体积大）
- ⚠️ **onnxruntime-directml** - GPU 加速
- ⚠️ **librosa** - 音频分析

#### 系统依赖
- ⚠️ **GStreamer** - 音频播放（需要单独安装）
- ⚠️ **Visual C++ Redistributable** - Windows 运行时

### 2. 文件结构检查

```
transcriptionist_v3/
├── ui/                    ✅ UI 组件
├── application/           ✅ 业务逻辑
├── domain/                ✅ 领域模型
├── infrastructure/        ✅ 基础设施
├── lib/                   ✅ 第三方适配器
├── data/                  ✅ 数据目录
├── config/                ✅ 配置目录
├── LICENSE                ✅ GPL-2.0 许可证
├── COPYING                ✅ 版权信息
├── README.md              ✅ 说明文档
└── __main__.py            ✅ 入口文件
```

### 3. 资源文件检查

- ✅ 图标文件: `ui/resources/icons/app_icon.png`
- ✅ 微信二维码: `ui/resources/images/wechat_qr.png`
- ✅ 样式文件: `ui/resources/styles/workstation_dark.qss`

---

## 🎯 推荐打包方案

### 方案对比

| 工具 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **PyInstaller** | 成熟稳定、支持好 | 体积较大 | ⭐⭐⭐⭐⭐ |
| **Nuitka** | 体积小、性能好 | 编译慢、配置复杂 | ⭐⭐⭐⭐ |
| **cx_Freeze** | 跨平台好 | 文档少 | ⭐⭐⭐ |
| **py2exe** | Windows 专用 | 不再维护 | ⭐⭐ |

### 🏆 最佳选择：PyInstaller

**理由**：
1. 对 PySide6/Qt 支持最好
2. 社区活跃，问题容易解决
3. 可以打包成单文件或目录
4. 支持自定义图标和版本信息

---

## 📦 详细步骤

### 步骤 1: 安装 PyInstaller

```bash
pip install pyinstaller
```

### 步骤 2: 创建打包配置文件

我会为你创建一个 `build.spec` 文件（见下方）

### 步骤 3: 执行打包

```bash
# 方式 1: 使用 spec 文件（推荐）
pyinstaller build.spec

# 方式 2: 命令行（简单测试）
pyinstaller --name="音译家" --windowed --icon=ui/resources/icons/app_icon.ico __main__.py
```

### 步骤 4: 测试打包结果

```bash
# 打包后的文件在 dist/ 目录
cd dist/音译家
音译家.exe
```

---

## ⚙️ PyInstaller 配置文件

### build.spec（完整配置）

```python
# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

# 项目根目录
project_root = Path('.').absolute()

# 收集所有数据文件
datas = [
    # UI 资源
    ('ui/resources', 'ui/resources'),
    
    # 数据文件
    ('data/defaults', 'data/defaults'),
    
    # 配置文件
    ('config', 'config'),
    
    # 许可证文件
    ('LICENSE', '.'),
    ('COPYING', '.'),
    ('README.md', '.'),
]

# 收集所有隐藏导入
hiddenimports = [
    # PySide6 模块
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtMultimedia',
    'PySide6.QtNetwork',
    
    # qfluentwidgets
    'qfluentwidgets',
    'qfluentwidgets.components',
    'qfluentwidgets.common',
    'qfluentwidgets.window',
    
    # 数据库
    'SQLAlchemy',
    'alembic',
    
    # 音频处理
    'mutagen',
    'mutagen.mp3',
    'mutagen.flac',
    'mutagen.oggvorbis',
    'mutagen.mp4',
    'mutagen.wave',
    'mutagen.aiff',
    
    # 网络
    'aiohttp',
    'aiofiles',
    
    # 工具
    'watchdog',
    'pydantic',
    
    # 项目模块
    'transcriptionist_v3.ui',
    'transcriptionist_v3.application',
    'transcriptionist_v3.domain',
    'transcriptionist_v3.infrastructure',
    'transcriptionist_v3.lib.quodlibet_adapter',
]

# 排除不需要的模块（减小体积）
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'pandas',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'sphinx',
]

# 分析
a = Analysis(
    ['__main__.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 打包
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 可执行文件
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='音译家',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ui/resources/icons/app_icon.ico',  # 需要转换为 .ico 格式
    version_file='version_info.txt',  # 版本信息文件
)

# 收集所有文件
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='音译家',
)
```

---

## 🔧 版本信息文件

### version_info.txt

```
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'音译家开发者'),
        StringStruct(u'FileDescription', u'音译家 AI音效管理工具'),
        StringStruct(u'FileVersion', u'1.0.0.0'),
        StringStruct(u'InternalName', u'Transcriptionist'),
        StringStruct(u'LegalCopyright', u'Copyright (C) 2024-2026 音译家开发者. Licensed under GPL-2.0'),
        StringStruct(u'OriginalFilename', u'音译家.exe'),
        StringStruct(u'ProductName', u'音译家 AI音效管理工具'),
        StringStruct(u'ProductVersion', u'1.0.0.0')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
```

---

## 🎨 图标转换

### PNG 转 ICO

```bash
# 使用 Python PIL
pip install Pillow

python -c "from PIL import Image; img = Image.open('ui/resources/icons/app_icon.png'); img.save('ui/resources/icons/app_icon.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])"
```

或使用在线工具：
- https://convertio.co/zh/png-ico/
- https://www.icoconverter.com/

---

## ⚠️ 常见问题

### 问题 1: 打包后无法启动

**原因**: 缺少依赖或路径问题

**解决**:
```bash
# 使用 --debug 模式查看详细错误
pyinstaller --debug=all build.spec
```

### 问题 2: 找不到资源文件

**原因**: 资源文件路径不正确

**解决**: 在代码中使用相对路径
```python
# 错误
icon_path = "ui/resources/icons/app_icon.png"

# 正确
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # 打包后的路径
    base_path = Path(sys._MEIPASS)
else:
    # 开发环境路径
    base_path = Path(__file__).parent

icon_path = base_path / "ui" / "resources" / "icons" / "app_icon.png"
```

### 问题 3: 体积太大

**原因**: 包含了不必要的库

**解决**:
1. 在 `excludes` 中排除不需要的模块
2. 不打包 AI 模型（让用户下载）
3. 使用 UPX 压缩

```bash
# 安装 UPX
# 下载: https://github.com/upx/upx/releases
# 解压后将 upx.exe 放到 PATH 中

# PyInstaller 会自动使用 UPX 压缩
```

### 问题 4: 杀毒软件误报

**原因**: PyInstaller 打包的程序容易被误报

**解决**:
1. 使用代码签名证书
2. 上传到 VirusTotal 检测
3. 联系杀毒软件厂商添加白名单

### 问题 5: GStreamer 依赖问题

**原因**: GStreamer 需要单独安装

**解决方案 A**: 使用 pygame 替代（已在代码中）
```python
# 不需要 GStreamer，使用 pygame
import pygame
pygame.mixer.init()
```

**解决方案 B**: 打包 GStreamer
```python
# 在 build.spec 中添加
datas += [
    ('C:/gstreamer/1.0/x86_64/bin/*.dll', 'gstreamer/bin'),
    ('C:/gstreamer/1.0/x86_64/lib/gstreamer-1.0/*.dll', 'gstreamer/lib'),
]
```

---

## ✅ 测试清单

### 打包前测试

- [ ] 在开发环境运行正常
- [ ] 所有功能都能使用
- [ ] 没有硬编码的绝对路径
- [ ] 资源文件都能正确加载

### 打包后测试

#### 基础测试
- [ ] 程序能正常启动
- [ ] 主窗口显示正常
- [ ] 图标显示正常
- [ ] 没有控制台窗口

#### 功能测试
- [ ] 音效库导入
- [ ] 音频播放
- [ ] AI 翻译
- [ ] 批量重命名
- [ ] 在线资源下载
- [ ] 设置保存和加载
- [ ] 数据库操作

#### 兼容性测试
- [ ] Windows 10 (21H2)
- [ ] Windows 10 (22H2)
- [ ] Windows 11 (21H2)
- [ ] Windows 11 (22H2)
- [ ] Windows 11 (23H2)

#### 性能测试
- [ ] 启动时间 < 5秒
- [ ] 内存占用 < 500MB
- [ ] CPU 占用正常
- [ ] 无内存泄漏

#### 安装测试
- [ ] 在干净的系统上安装
- [ ] 不需要安装 Python
- [ ] 不需要安装其他依赖
- [ ] 卸载干净

---

## 📦 创建安装包

### 使用 Inno Setup（推荐）

1. **下载 Inno Setup**
   - https://jrsoftware.org/isdl.php

2. **创建安装脚本** (见下方 `installer.iss`)

3. **编译安装包**
   ```bash
   iscc installer.iss
   ```

### installer.iss

```ini
[Setup]
AppName=音译家 AI音效管理工具
AppVersion=1.0.0
AppPublisher=音译家开发者
AppPublisherURL=https://github.com/your-repo
DefaultDirName={autopf}\Transcriptionist
DefaultGroupName=音译家
OutputDir=output
OutputBaseFilename=音译家_v1.0.0_Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
LicenseFile=LICENSE
SetupIconFile=ui\resources\icons\app_icon.ico
UninstallDisplayIcon={app}\音译家.exe
PrivilegesRequired=admin

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "quicklaunchicon"; Description: "创建快速启动栏快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
Source: "dist\音译家\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\音译家"; Filename: "{app}\音译家.exe"
Name: "{group}\卸载音译家"; Filename: "{uninstallexe}"
Name: "{autodesktop}\音译家"; Filename: "{app}\音译家.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\音译家"; Filename: "{app}\音译家.exe"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\音译家.exe"; Description: "启动音译家"; Flags: nowait postinstall skipifsilent
```

---

## 🚀 完整打包流程

### 1. 准备工作

```bash
# 1. 安装打包工具
pip install pyinstaller pillow

# 2. 转换图标
python convert_icon.py

# 3. 清理旧的构建文件
rmdir /s /q build dist
```

### 2. 执行打包

```bash
# 使用 spec 文件打包
pyinstaller build.spec
```

### 3. 测试程序

```bash
# 运行打包后的程序
cd dist\音译家
音译家.exe
```

### 4. 创建安装包

```bash
# 使用 Inno Setup 编译
iscc installer.iss
```

### 5. 最终产物

```
output/
└── 音译家_v1.0.0_Setup.exe  (约 200-300MB)
```

---

## 📊 预期体积

| 组件 | 大小 |
|------|------|
| Python 运行时 | ~50MB |
| PySide6 | ~80MB |
| qfluentwidgets | ~20MB |
| 其他依赖 | ~30MB |
| 项目代码 | ~10MB |
| **总计** | **~200MB** |

如果包含 AI 模型：
- CLAP 模型: ~600MB
- MusicGen 模型: ~900MB
- **总计**: ~1.7GB

**建议**: 不打包 AI 模型，让用户在软件内下载。

---

## 🎯 优化建议

### 1. 减小体积
- 排除不需要的模块
- 使用 UPX 压缩
- 不打包 AI 模型

### 2. 提高兼容性
- 静态链接 VC++ 运行时
- 包含必要的 DLL
- 测试多个 Windows 版本

### 3. 提升用户体验
- 添加启动画面
- 优化启动速度
- 提供详细的错误信息

---

## 📞 需要帮助？

如果遇到问题，请：
1. 查看 PyInstaller 文档: https://pyinstaller.org/
2. 搜索 GitHub Issues
3. 联系开发者

---

**祝打包顺利！** 🎉
