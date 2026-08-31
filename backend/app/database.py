from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

# Build engine — SQLite gets check_same_thread + WAL; PostgreSQL uses connection pooling
connect_args = {}
engine_kwargs = {}

if settings.is_postgres:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10
else:
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

# SQLite-specific pragmas
if not settings.is_postgres:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


class Base(DeclarativeBase):
    pass


# Columns that may not exist in older database schemas.
# Only tables that are actively queried on every request are listed here.
LIGHT_MIGRATIONS = {
    "users": {
        "password_hash": "VARCHAR(200)",
        "last_login": "TIMESTAMP",
        "role": "VARCHAR(50) DEFAULT 'Viewer'",
        "status": "VARCHAR(20) DEFAULT 'Active'",
    },
    "products": {
        "unit_cost_inr": "DOUBLE PRECISION",
    },
    "inventory": {
        "unit_cost_inr": "DOUBLE PRECISION",
    },
    "sap_config": {"last_sync_at": "DATETIME"},
    "sales": {"created_at": "DATETIME"},
    "sap_sync_log": {"detail_json": "TEXT"},
    "orders": {"order_type": "VARCHAR(20) DEFAULT 'SALES_ORDER'",
               "supplier_name": "VARCHAR(200)",
               "fulfillment_region": "VARCHAR(100)"},
}


def run_light_migrations() -> list[str]:
    """Idempotent column additions for tables that already exist.
    create_all only adds new tables, never new columns — this bridges the gap
    for both SQLite (build) and PostgreSQL (cloud).

    Each ALTER TABLE is committed independently so one failure
    does not abort the entire transaction (PostgreSQL behavior)."""
    applied = []
    for table, cols in LIGHT_MIGRATIONS.items():
        existing = _get_existing_columns_raw(table)
        if not existing:
            continue
        for col, ddl in cols.items():
            if col not in existing:
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                        conn.commit()
                        applied.append(f"{table}.{col}")
                except Exception as e:
                    logger.warning(f"Migration skip {table}.{col}: {e}")
    return applied


def _get_existing_columns_raw(table: str) -> set[str]:
    """Return the set of existing column names for a table (standalone connection)."""
    try:
        with engine.connect() as conn:
            if settings.is_postgres:
                result = conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = :tbl"
                ), {"tbl": table})
                return {row[0] for row in result}
            else:
                result = conn.execute(text(f"PRAGMA table_info({table})"))
                return {row[1] for row in result}
    except Exception:
        return set()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
