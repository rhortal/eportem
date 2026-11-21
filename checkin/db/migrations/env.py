from alembic import context

from checkin.db.engine import make_engine
from checkin.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = make_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as connection:
        # render_as_batch: SQLite can't ALTER most things; batch mode copies the table.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
