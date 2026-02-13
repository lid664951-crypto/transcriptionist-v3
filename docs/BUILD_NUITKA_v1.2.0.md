# Transcriptionist v1.2.0 Nuitka 打包说明

## 目标

- 彻底切换为 `Nuitka` 打包链路，不再依赖 `PyInstaller`。
- 产出两种分发物：
  - 绿色版目录：`dist/transcriptionist_v1.2.0/`
  - 安装包（Inno Setup）：`dist/音译家_AI音效管理工具_v1.2.0_setup.exe`

## 前置条件

- Windows 10/11 x64
- 项目根目录包含：`runtime/python/python.exe`
- 安装 Inno Setup（可选，仅安装包阶段需要）

## 一键构建

在项目根目录执行：

```bat
build_nuitka.bat
```

默认会执行：

1. 安装构建依赖：`nuitka / ordered-set / zstandard`
2. 编译 `scripts/metadata_worker.py` 为独立 `metadata_worker.exe`
3. 编译主程序 `__main__.py` 为 `standalone`
4. 组装最终绿色版目录 `dist/transcriptionist_v1.2.0/`
5. 若检测到 Inno Setup，则自动构建安装包

## 诊断模式（推荐）

`build_nuitka.bat` 已内置诊断模式，默认开启（`NUITKA_DIAG=1`）：

- 详细诊断日志：`build_nuitka_diagnostic.log`
- 分步失败定位（带错误码）
- 可从指定步骤断点续跑（`NUITKA_RESUME_STEP`）
- 出包后自动校验关键资源（图标/图片/目录）

### 常用诊断命令

- 从头完整诊断：

```bat
set NUITKA_DIAG=1
set NUITKA_RESUME_STEP=0
build_nuitka.bat
```

- 仅从主程序编译步骤续跑（跳过前面步骤）：

```bat
set NUITKA_DIAG=1
set NUITKA_RESUME_STEP=5
build_nuitka.bat
```

- 迷你诊断（最小参数，先确认 Nuitka 基础可用）：

```bat
set NUITKA_DIAG=1
set NUITKA_DIAG_MINI=1
set BUILD_INSTALLER=0
build_nuitka.bat
```

### 步骤编号对照

- `1` 安装构建依赖
- `2` 图标转换
- `3` 清理/准备输出目录
- `4` 编译 `metadata_worker.exe`
- `5` 编译主程序
- `6` 组装绿色版 + 资源校验
- `7` 编译安装包

## 可选参数

- 跳过安装包阶段：

```bat
set BUILD_INSTALLER=0
build_nuitka.bat
```

## 目录结构（构建后）

- `dist/transcriptionist_v1.2.0/transcriptionist.exe`：主程序
- `dist/transcriptionist_v1.2.0/metadata_worker.exe`：并行元数据提取进程
- `dist/transcriptionist_v1.2.0/ui/resources/...`：UI资源
- `dist/transcriptionist_v1.2.0/resources/...`：字体与其它资源
- `dist/transcriptionist_v1.2.0/locale/...`：国际化资源
- `dist/transcriptionist_v1.2.0/plugins/...`：插件目录
- `dist/transcriptionist_v1.2.0/data/models/onnx_preprocess/...`：ONNX 预处理模型

## 与 v1.2.0 改动的对应关系

- 设置页新增/重构模块依赖的样式和图标资源，已通过 `--include-data-dir` 打包。
- 音频列表并行元数据提取依赖 `metadata_worker.exe`，已独立编译并复制到主程序同目录。
- 资源加载路径已兼容 `PyInstaller/Nuitka`，在 frozen 模式下可正常查找资源目录。

## 常见问题

### 1) 启动后并行扫描退化为单线程

- 现象：日志提示找不到 `metadata_worker.exe`。
- 处理：确认 `dist/transcriptionist_v1.2.0/metadata_worker.exe` 存在，且与主程序同目录。

### 2) 缺失图标/样式/字体

- 处理：确认以下目录存在并有内容：
  - `ui/resources`
  - `resources`
  - `locale`
  - `plugins`

脚本在步骤 6 会自动校验以下关键项：

- `ui/resources/icons/app_icon.ico`
- `ui/resources/icons/app_icon.png`
- `ui/resources/images/`
- `resources/`
- `locale/`
- `plugins/`

### 3) 不需要安装包，只要绿色版

- 使用 `set BUILD_INSTALLER=0` 后执行 `build_nuitka.bat`。

## 产物验收建议

- 验证设置页（包括 AI 服务商和音效工坊配置）能正常显示与保存。
- 验证音频列表卡片/表格视图正常切换，波形与播放器可用。
- 验证在线资源、AI 音效工坊请求链路不因打包缺资源报错。
