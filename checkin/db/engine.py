"""Database engine, sessions and migrations."""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(url):
    """An engine for `url`. SQLite gets WAL (readers don't block the scheduler),
    foreign keys and a busy timeout; its folder is created if missing."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _record):
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            if parsed.database not in (None, "", ":memory:"):
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


def make_sessionmaker(engine):
    return sessionmaker(engine, expire_on_commit=False)


def alembic_config(url):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def migrate(url, revision="head"):
    """Bring the database at `url` up to `revision`."""
    from alembic import command
    command.upgrade(alembic_config(url), revision)


def downgrade(url, revision):
    from alembic import command
    command.downgrade(alembic_config(url), revision)
