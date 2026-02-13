# 音译家 v1.2.0 压力测试指南（无百万真实素材版）

## 1. 目标

在缺少海量真实音效素材时，通过“合成语料 + 数据库压力路径”验证以下能力：

- 导入链路是否稳定（大批量路径入队、去重、入库）
- 批量翻译替换/撤销链路是否可执行
- AI 检索链路在大数据量下是否可用

---

## 2. 新增脚本

- 语料生成：`scripts/generate_stress_corpus.py`
- 压测执行：`scripts/run_stress_suite.py`
- 一键批处理：`scripts/run_stress_suite_pipeline.bat`

---

## 2.1 Windows 一键批处理（推荐）

```bat
scripts\run_stress_suite_pipeline.bat smoke
scripts\run_stress_suite_pipeline.bat 100k
scripts\run_stress_suite_pipeline.bat 500k
scripts\run_stress_suite_pipeline.bat 1m
scripts\run_stress_suite_pipeline.bat all

:: optional seed dir (if provided, hardlink mode will be used)
scripts\run_stress_suite_pipeline.bat 100k "D:\seed_audio"
```

---

## 3. 快速开始

### 3.1 生成 10 万压测语料（推荐 hardlink）

```powershell
py -3 "scripts/generate_stress_corpus.py" \
  --output-dir "data/stress_corpus_100k" \
  --mode hardlink \
  --seed-dir "D:/your_small_audio_seed" \
  --count 100000 \
  --levels "120,80" \
  --force
```

> 说明：
> - `hardlink` 模式几乎不额外占用磁盘，适合大规模压测。
> - 如果硬链接失败会自动回退到复制。

### 3.2 跑压测套件

```powershell
py -3 "scripts/run_stress_suite.py" \
  --dataset-dir "data/stress_corpus_100k" \
  --db-path "data/database/stress_suite_100k.db" \
  --records 100000 \
  --search-queries 20 \
  --translate-batch 5000 \
  --json-out "docs/reports/stress_suite_100k.json"
```

---

## 4. 百万级建议跑法

### 4.1 先做 10 万（冒烟）

- 验证脚本与机器环境可跑通。
- 观察是否有 SQL 报错、卡死或 UI 假死现象。

### 4.2 再做 50 万（中压）

```powershell
py -3 "scripts/generate_stress_corpus.py" --output-dir "data/stress_corpus_500k" --mode hardlink --seed-dir "D:/your_small_audio_seed" --count 500000 --levels "220,160" --force
py -3 "scripts/run_stress_suite.py" --dataset-dir "data/stress_corpus_500k" --db-path "data/database/stress_suite_500k.db" --records 500000 --search-queries 30 --translate-batch 10000 --json-out "docs/reports/stress_suite_500k.json"
```

### 4.3 最后做 100 万（高压）

```powershell
py -3 "scripts/generate_stress_corpus.py" --output-dir "data/stress_corpus_1m" --mode hardlink --seed-dir "D:/your_small_audio_seed" --count 1000000 --levels "320,220" --force
py -3 "scripts/run_stress_suite.py" --dataset-dir "data/stress_corpus_1m" --db-path "data/database/stress_suite_1m.db" --records 1000000 --search-queries 50 --translate-batch 20000 --json-out "docs/reports/stress_suite_1m.json"
```

---

## 4.4 纯本地快速验证（不依赖种子音频）

```powershell
py -3 "scripts/generate_stress_corpus.py" --output-dir "data/stress_smoke" --mode synth --count 1000 --levels "20,10" --force
py -3 "scripts/run_stress_suite.py" --dataset-dir "data/stress_smoke" --db-path "data/database/stress_suite_smoke.db" --records 20000 --search-queries 10 --translate-batch 2000 --json-out "docs/reports/stress_suite_smoke.json"
```

---

## 5. 输出结果说明

压测报告默认输出到 `docs/reports/*.json`，重点关注：

- `passed`：是否整体通过
- `cases[].passed`：每个子场景是否通过
- `cases[].elapsed_ms`：各子场景耗时
- `cases[].detail`：插入条数、查询轮次、平均耗时等细节

---

## 6. 注意事项

- 本方案重点验证“系统承压路径”，并不等同于“真实业务分布”的绝对性能上限。
- 真实线上使用前，建议再做一次“真实素材混合压测”（不同时长、码率、采样率）。
- 如出现性能瓶颈，优先查看：数据库 I/O、批次大小、并发参数、检索 TopK。
