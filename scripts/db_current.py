"""
查看当前 Alembic 版本。

示例：
    python scripts/db_current.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    try:
        from alembic import command
        from alembic.config import Config
    except Exception as e:
        print(f"[ERROR] Alembic 不可用: {e}")
        return 2

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", "infrastructure/database/migrations")

    env_url = (os.environ.get("TRANSCRIPTIONIST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if env_url.startswith("sqlite://"):
        cfg.set_main_option("sqlalchemy.url", env_url)
    elif env_url:
        print("[WARN] 仅支持 sqlite:// URL，已忽略环境变量中的非 SQLite URL")

    command.current(cfg, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
