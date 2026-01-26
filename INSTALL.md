# Transcriptionist v3 安装指南

## 快速开始

### 方式一：使用内嵌运行时（推荐）

项目已包含完整的内嵌Python运行时和GTK4环境，无需额外安装系统依赖。

```batch
# 安装Python依赖到内嵌环境
install_deps.bat

# 运行应用
run.bat
```

### 方式二：使用系统Python

如果你想使用系统Python，需要先安装GTK4：

1. 安装MSYS2: https://www.msys2.org/
2. 在MSYS2中安装GTK4:
   ```bash
   pacman -S mingw-w64-x86_64-gtk4 mingw-w64-x86_64-libadwaita mingw-w64-x86_64-python-gobject
   ```
3. 安装Python依赖:
   ```bash
   pip install -r requirements.txt
   ```

---

## 依赖列表

### 核心依赖

| 类别 | 包名 | 版本 | 说明 |
|------|------|------|------|
| **UI** | PyGObject | >=3.42.0 | GTK4/Libadwaita绑定 |
| **数据库** | SQLAlchemy | >=2.0.0 | ORM框架 |
| | alembic | >=1.12.0 | 数据库迁移 |
| **音频** | mutagen | >=1.47.0 | 元数据提取 |
| | soundfile | >=0.12.0 | 音频读写 |
| | pygame | >=2.5.0 | 音频播放 |
| | pyloudnorm | >=0.1.1 | 响度标准化 |
| | librosa | >=0.10.0 | 音频分析 |
| **AI** | numpy | >=1.24.0 | 数值计算 |
| | scikit-learn | >=1.3.0 | 机器学习 |
| **网络** | aiohttp | >=3.9.0 | 异步HTTP |
| | aiofiles | >=23.0.0 | 异步文件 |
| **工具** | watchdog | >=3.0.0 | 文件监控 |
| | pydantic | >=2.0.0 | 数据验证 |

### 开发依赖（可选）

```bash
pip install -r requirements-dev.txt
```

包含：pytest, black, mypy, ruff 等开发工具。

---

## 目录结构

```
transcriptionist_v3/
├── runtime/
│   ├── python/          # 内嵌Python 3.13
│   │   └── Lib/site-packages/  # Python依赖
│   └── gtk4/            # GTK4运行时
│       ├── bin/         # DLL文件
│       ├── lib/         # typelib文件
│       └── share/       # 资源文件
├── scripts/
│   ├── install_embedded_deps.bat  # 安装脚本
│   ├── verify_deps.py   # 验证脚本
│   └── test_gtk4.py     # GTK4测试
├── requirements.txt     # 核心依赖
├── requirements-dev.txt # 开发依赖
├── install_deps.bat     # 安装入口
└── run.bat              # 启动脚本
```

---

## 验证安装

```batch
# 运行验证脚本
runtime\python\python.exe scripts\verify_deps.py
```

预期输出：
```
所有依赖已正确安装！
```

---

## 常见问题

### Q: GTK4 DLL加载失败
A: 确保通过 `run.bat` 启动应用，它会自动设置GTK4环境变量。

### Q: 找不到某个Python包
A: 运行 `install_deps.bat` 重新安装依赖。

### Q: 如何更新依赖？
A: 编辑 `requirements.txt` 后重新运行 `install_deps.bat`。
