"""One active loan per item + overdue detection with grace days."""

from datetime import date, timedelta

def can_lend(item_status: str, active_loans: int) -> dict:
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}

def parse_grace_days(value) -> int | None:
    """Zero or positive integer, else None (rejected)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, str):
        s = value.strip()
        if not s or not s.isascii() or not s.isdigit():
            return None
        n = int(s)
    else:
        return None
    return n if n >= 0 else None

def is_overdue(due_date: str, today: str, loan_status: str, grace_days: int = 0) -> bool:
    if loan_status != "active" or not due_date:
        return False
    if grace_days > 0:
        try:
            limit = date.fromisoformat(due_date) + timedelta(days=grace_days)
        except ValueError:
            limit = None
        if limit is not None:
            return limit.isoformat() < today
    return due_date < today

def classify_loans(loans: list[dict], today: str, grace_days: int = 0) -> dict:
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
        elif is_overdue(L.get("due_date"), today, st, grace_days):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}
