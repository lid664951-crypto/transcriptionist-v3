# v1.2.0 Alembic 版本化迁移工作流

## 1. 目标

- 将数据库变更纳入版本管理（upgrade/downgrade/stamp）。
- 为 SQLite 主路径提供可回滚的结构迁移机制。

## 2. 关键文件

- `alembic.ini`
- `infrastructure/database/migrations/env.py`
- `infrastructure/database/migrations/versions/20260207_0001_initial_schema.py`
- `scripts/db_revision.py`
- `scripts/db_upgrade.py`
- `scripts/db_downgrade.py`
- `scripts/db_stamp.py`
- `scripts/db_current.py`

## 3. 常用命令

### 3.1 查看当前版本

```bash
python scripts/db_current.py
```

### 3.2 升级到最新版本

```bash
python scripts/db_upgrade.py --revision head
```

### 3.3 回滚一个版本

```bash
python scripts/db_downgrade.py --revision -1
```

### 3.4 生成新版本脚本

```bash
python scripts/db_revision.py -m "add xxx"
python scripts/db_revision.py -m "add xxx" --autogenerate
```

### 3.5 标记版本（不执行 SQL）

```bash
python scripts/db_stamp.py --revision 20260207_0001
```

## 4. 数据库 URL 优先级

1. 命令执行环境变量：`TRANSCRIPTIONIST_DATABASE_URL`
2. 命令执行环境变量：`DATABASE_URL`
3. 应用配置：`database.url`
4. 回退到 SQLite 本地文件

> 说明：当前仅支持 `sqlite://` URL，非 SQLite URL 会被忽略。

## 5. SQLite 主线建议流程

1. 首次初始化或升级：

```bash
python scripts/db_upgrade.py --revision head
```

2. 若已有现网结构但缺少版本记录，可先标记：

```bash
python scripts/db_stamp.py --revision 20260207_0001
```

3. 后续结构变更统一通过 Alembic 升级/回滚。
