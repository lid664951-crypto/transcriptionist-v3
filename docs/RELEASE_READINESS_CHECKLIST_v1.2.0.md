# 音译家 v1.2.0 发布就绪检查清单（R1）

## 1. 一键自动检查

- 快速档（推荐先跑）
  - `py -3 scripts/run_release_readiness_check.py --profile ci --mode gate`
- 发布档（更接近正式发布）
  - `py -3 scripts/run_release_readiness_check.py --profile standard --mode gate`

输出报告位置：

- `docs/reports/release_readiness_<tag>.json`
- 关联压测与回归报告在 `docs/reports/` 下自动生成

判定规则：

- 退出码 `0`：通过
- 退出码 `2`：未通过（需修复后重跑）

## 2. 手工 UI 回归（你本地启动后执行）

### 2.1 工作区布局三态

- 验证 `Split / LibraryFocus / WorkbenchFocus` 可循环切换
- 验证切换后：
  - 当前页面状态不丢失
  - 列表选择与滚动位置尽量保持
  - 播放器和波形继续可用

### 2.2 性能闸门信息展示

- 标题栏应出现“性能闸门：通过/失败（模式）”摘要
- 点击“性能闸门详情”按钮弹出报告摘要
- 报告路径、模式、耗时信息与 `docs/reports` 中 JSON 一致

### 2.3 实时索引状态

- 标题栏“实时索引”状态可刷新
- 详情弹窗可展示最近索引任务摘要

## 3. 中文编码与显示

- 检查新增文案是否出现乱码
- 若出现乱码，优先检查：
  - 文件编码是否 UTF-8
  - 终端/编辑器是否按 UTF-8 打开
  - 系统区域设置与字体回退

## 4. 性能门禁建议

- 日常开发：`--profile ci`
- 发布前：`--profile standard`
- 若硬件差异较大，保留不同机器 baseline 并记录设备信息

## 5. R1 通过标准

- 自动检查脚本通过（`PASS`）
- UI 三态、性能闸门、实时索引详情手工回归通过
- 中文显示无新增乱码

