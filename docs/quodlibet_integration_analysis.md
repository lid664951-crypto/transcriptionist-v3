# Quod Libet 模块集成分析报告

本文档分析 Transcriptionist v3 各任务如何更好地利用 Quod Libet 的成熟模块。

## 已完成的集成

### ✅ 任务 12/13 - 命名管理器 (rename_adapter.py)
已从 `quodlibet/qltk/renamefiles.py` 和 `quodlibet/util/path.py` 移植：
- `strip_win32_incompat()` - Windows 不兼容字符处理
- `strip_win32_incompat_from_path()` - 路径级别的字符处理
- `limit_path()` - 文件名长度限制
- 12 个重命名过滤器 (SpacesToUnderscores, StripDiacriticals 等)
- FilterChain 过滤器链

### ✅ 任务 6 - 搜索引擎 (query_adapter.py) - 已增强
已从 `quodlibet/query/_parser.py` 移植：
- 完整的布尔运算支持 (AND, OR, NOT)
- 时间值解析 (支持 "3:30", "5m", "2 minutes" 等格式)
- 文件大小解析 (支持 "1mb", "500kb" 等格式)
- 正则表达式搜索
- 字段特定搜索
- 单位系统 (Units enum)

### ✅ 任务 12 - 模式系统 (pattern_adapter.py) - 新建
已从 `quodlibet/pattern/_pattern.py` 移植：
- 完整的模式解析器 (Lexer + Parser)
- 条件表达式 `<tag|if|else>`
- 析取表达式 `<tag1||tag2>`
- 文件名安全处理 (FilePatternFormatter)
- UCS 命名模式支持 (UCSPatternFormatter)
- 模式缓存机制

---

## 建议增强的任务

### 🔧 任务 4 - Library Manager (高优先级)

**当前实现**: 自定义扫描器和元数据提取器

**Quod Libet 可用模块**:
- `quodlibet/library/file.py` - FileLibrary 类
  - 成熟的目录扫描 (`scan()` 方法)
  - 挂载点检测和遮罩处理
  - 文件变更检测 (WatchedFileLibraryMixin)
  - 库重建和增量更新
- `quodlibet/library/base.py` - 基础库类
  - 信号系统 (added, removed, changed)
  - 事务支持

**建议增强**:
```python
# 创建 library_adapter.py
from quodlibet.library.file import FileLibrary, WatchedFileLibraryMixin
from quodlibet.util.path import normalize_path, ismount, find_mount_point
```

**可移植功能**:
1. `iter_paths()` - 高效的路径迭代器
2. `normalize_path()` - 跨平台路径规范化
3. `ismount()` / `find_mount_point()` - 挂载点检测
4. 文件监控逻辑 (Gio.FileMonitor)

---

### 🔧 任务 5 - Audio Player (低优先级 - 当前实现已足够)

**当前实现**: 基础 GStreamer playbin (player_adapter.py)

**Quod Libet 可用模块**:
- `quodlibet/player/gstbe/` - 完整的 GStreamer 后端

**可选增强**:
- ReplayGain 支持
- 均衡器支持

---

### 🔧 任务 18 - Batch Processor (中优先级)

**Quod Libet 可用模块**:
- `quodlibet/util/copool.py` - 协程池 (后台任务)
- `quodlibet/util/thread.py` - 线程工具

**可移植功能**:
1. `copool` - 协作式任务调度
2. 进度回调机制

---

### 🔧 任务 20 - Performance Optimization (中优先级)

**Quod Libet 可用模块**:
- `quodlibet/library/base.py` - 库缓存机制
- `quodlibet/util/picklehelper.py` - 序列化优化

**可移植功能**:
1. 库序列化/反序列化
2. 增量更新机制

---

## 适配器模块清单

### 已创建的适配器

| 适配器 | 文件 | 状态 | 移植功能 |
|--------|------|------|----------|
| Player | `player_adapter.py` | ✅ 完成 | GStreamer 播放器 |
| Formats | `formats_adapter.py` | ✅ 完成 | 元数据提取 (Mutagen) |
| Query | `query_adapter.py` | ✅ 增强 | 查询解析、时间/大小单位 |
| Rename | `rename_adapter.py` | ✅ 完成 | 重命名过滤器、路径处理 |
| Pattern | `pattern_adapter.py` | ✅ 新建 | 模式系统、UCS 命名 |

### 建议创建的适配器

| 适配器 | 文件 | 优先级 | 移植功能 |
|--------|------|--------|----------|
| Library | `library_adapter.py` | 高 | 目录扫描、文件监控 |
| Util | `util_adapter.py` | 低 | 通用工具函数 |

---

## 实施优先级 (更新)

| 优先级 | 任务 | 适配器 | 状态 |
|--------|------|--------|------|
| ~~高~~ | ~~任务 6 (搜索)~~ | ~~query_adapter.py~~ | ✅ 已完成 |
| ~~高~~ | ~~任务 12 (命名)~~ | ~~pattern_adapter.py~~ | ✅ 已完成 |
| 高 | 任务 4 (库管理) | library_adapter.py | 📝 待实施 |
| 低 | 任务 5 (播放器) | player_adapter.py | ⏸️ 当前足够 |
| 中 | 任务 18 (批处理) | util_adapter.py | 📝 待实施 |

---

## 注意事项

1. **许可证**: Quod Libet 使用 GPL v2，我们的项目也需要遵循 GPL v2
2. **依赖**: 某些模块依赖 GTK/GLib，需要确保运行环境支持
3. **测试**: 移植后需要充分测试，确保功能正确
4. **文档**: 保留原始版权声明和作者信息

---

## 使用示例

### 查询解析器 (增强版)
```python
from transcriptionist_v3.lib.quodlibet_adapter import (
    parse_query, parse_time_value, parse_size_value
)

# 搜索时长大于 3:30 的文件
query = parse_query("duration:>3:30")

# 搜索大于 1MB 的 WAV 文件
query = parse_query("format:wav AND size:>1mb")

# 解析时间值
seconds = parse_time_value("5 minutes")  # 300.0

# 解析文件大小
bytes_val = parse_size_value("2.5gb")  # 2684354560.0
```

### 模式系统
```python
from transcriptionist_v3.lib.quodlibet_adapter import (
    Pattern, FilePattern, UCSPattern
)

# 基础模式
pattern = Pattern("<category>_<name>")
result = pattern.format({'category': 'AMB', 'name': 'City Traffic'})
# 结果: "AMB_City Traffic"

# 条件模式
pattern = Pattern("<artist|<artist> - |><title>")
result = pattern.format({'title': 'Explosion'})
# 结果: "Explosion" (artist 为空，跳过)

# 文件名安全模式
pattern = FilePattern("<category>/<name>", extension=".wav")
result = pattern.format({'category': 'SFX', 'name': 'Gun:Shot'})
# 结果: "SFX/Gun_Shot.wav" (冒号被替换)

# UCS 命名模式
ucs = UCSPattern()
result = ucs.format_ucs(category='AMB', subcategory='City', fx_name='Traffic')
# 结果: "AMB_City_Traffic"
```

### 重命名过滤器
```python
from transcriptionist_v3.lib.quodlibet_adapter import (
    create_default_filter_chain, sanitize_filename
)

# 使用过滤器链
chain = create_default_filter_chain()
result = chain.apply("My File: Test (2024)")
# 结果: FilterResult(original="...", filtered="My_File_Test_2024", ...)

# 快速清理文件名
safe_name = sanitize_filename("File<>Name?.wav")
# 结果: "File__Name_.wav"
```

---

## 下一步行动

1. ✅ 完成 rename_adapter.py
2. ✅ 增强 query_adapter.py - 集成时间/大小解析
3. ✅ 创建 pattern_adapter.py - 移植模式系统
4. 📝 创建 library_adapter.py - 移植库管理功能 (可选)
