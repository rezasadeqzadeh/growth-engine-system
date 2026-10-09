"""Apply pending database migrations when the API starts.

Runs `alembic upgrade head` in-process. On Postgres an advisory lock makes
concurrent starts (several API processes, a redeploy overlapping the old
container) take turns instead of migrating twice.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from . import db

logger = logging.getLogger(__name__)
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
LOCK_KEY = 0x6765_6E67  # any fixed number shared by every process of this app


def upgrade_to_head() -> None:
    cfg = Config(str(ALEMBIC_INI))
    # The app has configured logging already; alembic's ini must not replace it.
    cfg.attributes["configure_logger"] = False
    with db.engine().connect() as conn:
        postgres = conn.dialect.name == "postgresql"
        if postgres:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        finally:
            if postgres:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()
    logger.info("[migrate] database is at head")
