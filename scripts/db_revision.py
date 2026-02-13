"""
创建 Alembic 迁移版本脚本。

示例：
    python scripts/db_revision.py -m "add pgvector support"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Alembic revision")
    parser.add_argument("-m", "--message", required=True, help="Revision message")
    parser.add_argument(
        "--autogenerate",
        action="store_true",
        help="Auto-generate from SQLAlchemy models",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

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

    command.revision(
        cfg,
        message=args.message,
        autogenerate=bool(args.autogenerate),
    )
    print("[DONE] Revision created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
