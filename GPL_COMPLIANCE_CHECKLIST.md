# GPL-2.0 合规性检查清单

## ✅ 已完成的任务

### 1. 许可证文件
- [x] **LICENSE** - 已下载 GPL-2.0 完整文本
- [x] **COPYING** - 已创建版权信息和致谢文件
- [x] **README.md** - 已更新，添加开源协议说明

### 2. 版权声明
已为所有使用 Quod Libet 代码的文件添加完整版权声明：

- [x] `lib/quodlibet_adapter/__init__.py`
- [x] `lib/quodlibet_adapter/pattern_adapter.py`
- [x] `lib/quodlibet_adapter/rename_adapter.py`
- [x] `lib/quodlibet_adapter/query_adapter.py`
- [x] `lib/quodlibet_adapter/formats_adapter.py`
- [x] `lib/quodlibet_adapter/player_adapter.py`

版权声明格式：
```python
"""
[文件描述]

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) [年份] [原作者]
Copyright (C) 2024-2026 音译家开发者 (modifications and adaptations)

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

[完整 GPL 声明...]
"""
```

### 3. 软件内致谢
- [x] 设置页面"关于"板块已添加：
  - 开源协议声明
  - Quod Libet 致谢信息
  - 核心贡献者名单
  - 访问 Quod Libet 项目的链接按钮

### 4. 文档
- [x] **QUODLIBET_CODE_USAGE_ANALYSIS.md** - 详细的代码使用分析报告
- [x] **GPL_COMPLIANCE_CHECKLIST.md** - 本检查清单

---

## 📋 合规性要点

### GPL-2.0 的核心要求

#### ✅ 必须做的事情
1. **提供源代码** - 分发软件时必须提供完整源代码
2. **保留版权声明** - 不能删除原作者的版权信息
3. **使用相同协议** - 整个项目必须采用 GPL-2.0（或兼容协议）
4. **提供许可证文本** - 必须包含 GPL-2.0 完整文本
5. **标注修改** - 修改的文件需要说明修改内容和日期

#### ✅ 可以做的事情
1. **商业使用** - 可以收费销售软件
2. **修改代码** - 可以自由修改和定制
3. **分发软件** - 可以自由分发给他人
4. **私人使用** - 可以内部使用而不公开

#### ⚠️ 不能做的事情
1. **闭源** - 不能将软件变成闭源商业软件
2. **改变协议** - 不能改用其他不兼容的协议
3. **删除版权** - 不能删除原作者的版权声明
4. **专利限制** - 不能添加专利限制

---

## 📦 分发软件时的要求

### 源代码分发
如果分发源代码，必须：
1. 包含所有源文件
2. 包含 LICENSE 文件
3. 包含 COPYING 文件
4. 包含构建说明（如 README.md）

### 二进制分发
如果分发编译后的可执行文件，必须：
1. 提供获取源代码的方式（如 GitHub 链接）
2. 或者随软件一起提供完整源代码
3. 在软件中显示版权信息和许可证
4. 提供书面承诺，保证任何第三方都能获取源代码

### 推荐做法
1. 在 GitHub 上公开源代码仓库
2. 在软件"关于"页面提供源代码链接
3. 在分发包中包含 LICENSE 和 COPYING 文件
4. 在安装程序中显示许可证信息

---

## 🎯 使用的 Quod Libet 代码总结

### 代码量统计
- **Pattern System**: ~700 行
- **Rename Filters**: ~400 行
- **Query Parser**: ~500 行
- **Audio Formats**: ~300 行
- **GStreamer Player**: ~250 行
- **总计**: ~2,150 行（约占项目 5-8%）

### 核心功能
1. **文件命名模板** - 使用 Pattern System
2. **批量重命名** - 使用 Rename Filters
3. **搜索查询** - 使用 Query Parser
4. **元数据提取** - 使用 Audio Formats
5. **音频播放** - 使用 GStreamer Player

### 修改说明
- 移除了 GTK 依赖
- 适配到 PySide6/Qt 框架
- 简化了接口
- 添加了类型注解
- 改进了错误处理

---

## 📝 版权声明模板

### 对于新文件（不含 Quod Libet 代码）
```python
"""
[文件描述]

Copyright (C) 2024-2026 音译家开发者

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""
```

### 对于修改的 Quod Libet 文件
```python
"""
[文件描述]

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) [年份] [原作者]
Copyright (C) 2024-2026 音译家开发者 (modifications)

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
```

---

## 🔍 常见问题

### Q: 我可以收费销售这个软件吗？
**A**: 可以！GPL 允许商业使用和收费。但你必须：
- 提供源代码给购买者
- 告知他们可以自由分发
- 不能限制他们的 GPL 权利

### Q: 我可以将软件改成闭源吗？
**A**: 不可以。使用了 GPL 代码的软件必须保持开源。

### Q: 我可以在公司内部使用而不公开吗？
**A**: 可以。只要不分发给外部，就不需要公开源代码。

### Q: 我可以改用 GPL-3.0 吗？
**A**: 可以。GPL-2.0-or-later 允许升级到更高版本。

### Q: 我需要为每个文件都加版权声明吗？
**A**: 建议这样做，特别是使用了 Quod Libet 代码的文件。

---

## ✅ 最终检查

在发布软件前，请确认：

- [ ] LICENSE 文件存在且完整
- [ ] COPYING 文件包含所有第三方版权信息
- [ ] README.md 说明了开源协议
- [ ] 所有适配器文件都有正确的版权声明
- [ ] 软件"关于"页面显示致谢信息
- [ ] 提供了获取源代码的方式（如 GitHub 链接）
- [ ] 分发包中包含必要的文档

---

## 📚 参考资源

- [GPL-2.0 官方文本](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
- [GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [Quod Libet 项目](https://github.com/quodlibet/quodlibet)
- [GPL 合规指南](https://www.gnu.org/licenses/gpl-howto.html)

---

**状态**: ✅ 已完成 GPL-2.0 合规性配置

**最后更新**: 2026-01-24

**维护者**: 音译家开发者
