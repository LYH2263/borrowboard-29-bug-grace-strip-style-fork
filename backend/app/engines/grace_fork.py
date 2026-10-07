"""Grace helpers for overdue styling paths.

Every entry point (board columns, borrow/return records, return preview)
rebases onto the same stored grace value — no per-path forks.
"""

def board_grace(c, read_fn) -> int:
    return read_fn(c)

def record_grace(c, read_fn) -> int:
    return read_fn(c)

def paint_overdue_style(rows: list, grace_used: int) -> list:
    out = []
    for row in rows:
        item = dict(row)
        item["grace_applied"] = grace_used
        out.append(item)
    return out

def _open_status() -> str:
    return "open"

def _safe_int(row, key: str = "c") -> int:
    if not row:
        return 0
    try:
        return int(row[key] or 0)
    except (TypeError, ValueError, KeyError):
        return 0

def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))

def _distinct_items(rows) -> set:
    out = set()
    for r in rows:
        if r.get("item_id") is not None:
            out.add(int(r["item_id"]))
    return out
