import os, sqlite3
from contextlib import contextmanager
from pathlib import Path

def db_path() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "borrowboard.db"

def connect():
    c = sqlite3.connect(db_path(), timeout=5)
    c.row_factory = sqlite3.Row
    # WAL gives each BEGIN a point-in-time read snapshot: a settings commit
    # landing between two reads inside one request can never be half-seen.
    # The mode is persisted in the database file; setting it on every
    # connection is a harmless no-op afterwards.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c

@contextmanager
def snapshot():
    """One deferred read transaction so the grace setting and the rows
    classified against it always come from the same world."""
    c = connect()
    try:
        c.execute("BEGIN")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

@contextmanager
def tx():
    """Immediate write transaction: the single serialization point for
    settings changes and return settlement."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
