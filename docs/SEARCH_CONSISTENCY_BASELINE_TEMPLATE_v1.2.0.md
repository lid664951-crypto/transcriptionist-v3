# 音译家 v1.2.0 检索一致性基线报告模板（M5）

## 1. 基本信息

- 执行日期：
- 执行人：
- 分支 / 构建版本：
- 数据规模：
  - 样本条数：
  - 查询条数：
  - TopK：

## 2. 执行命令

```bash
py -3 scripts/benchmark_search_orchestrator.py \
  --records 100000 \
  --queries 50 \
  --top-k 200 \
  --threshold-total-ms 220 \
  --threshold-fuse-ms 60 \
  --threshold-overlap 0.45 \
  --json-out docs/reports/search_benchmark_100k.json
```

## 3. 指标结果（填报）

- `lexical_p95_ms`：
- `semantic_p95_ms`：
- `fuse_p95_ms`：
- `total_p95_ms`：
- `overlap_avg`：
- `overlap_p50`：
- `overlap_p95`：

## 4. 阈值判定

- 总耗时阈值（P95）<= 220ms：`PASS / FAIL`
- 融合耗时阈值（P95）<= 60ms：`PASS / FAIL`
- 一致性重叠率（平均）>= 45%：`PASS / FAIL`
- 综合判定：`PASS / FAIL`

## 5. 差异样本（TopN）

- Query#1:
  - AI 独有：
  - 库页独有：
- Query#2:
  - AI 独有：
  - 库页独有：

## 6. 结论与动作

- 当前结论：
- 风险等级：
- 后续动作：
  - [ ] 调整 `rrf_k`
  - [ ] 调整 lexical/semantic 权重
  - [ ] 检查索引覆盖率与路径归一化
  - [ ] 优化向量检索批处理策略

