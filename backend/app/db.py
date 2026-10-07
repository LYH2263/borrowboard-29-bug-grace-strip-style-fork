import os, sqlite3
from contextlib import contextmanager
from pathlib import Path

def db_path() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "borrowboard.db"

def connect():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    return c

@contextmanager
def snapshot():
    """One read transaction: every SELECT in a request sees the same committed
    state, so a response never mixes loans and settings from two worlds."""
    c = connect()
    try:
        c.execute("BEGIN")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

@contextmanager
def write_tx():
    """BEGIN IMMEDIATE: check-then-write is serialized against other writers
    (settings update vs return confirm landing in the same second)."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
