from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


LIGHT_MIGRATIONS = {
    "sap_config": {"last_sync_at": "DATETIME"},
    "sales": {"created_at": "DATETIME"},
    "sap_sync_log": {"detail_json": "TEXT"},
}


def run_light_migrations() -> list[str]:
    """Idempotent column additions for tables that already exist.
    create_all only adds new tables, never new columns — this bridges the gap
    for both SQLite (build) and PostgreSQL (cloud)."""
    applied = []
    with engine.connect() as conn:
        for table, cols in LIGHT_MIGRATIONS.items():
            try:
                existing = {row[0] for row in conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"
                ))}
            except Exception:
                existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    applied.append(f"{table}.{col}")
        conn.commit()
    return applied


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
