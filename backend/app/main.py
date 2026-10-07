from datetime import date, datetime, timezone
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, snapshot, tx
from app.engines.borrow_rules import can_lend, classify_loans, is_overdue, parse_grace_days

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

def _grace_days(c) -> int:
    """The one grace reader. Must be called inside an open transaction so
    callers classify rows against the same setting they just read."""
    row = c.execute("SELECT value FROM settings WHERE key='grace_days'").fetchone()
    n = parse_grace_days(row["value"]) if row else None
    return n if n is not None else 0

def _today() -> str:
    return date.today().isoformat()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/board")
def board():
    with snapshot() as c:
        available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
        loans = [dict(r) for r in c.execute(
            """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
               WHERE loans.status='active'""")]
        grace = _grace_days(c)
        cls = classify_loans(loans, _today(), grace)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
        "grace_days": grace,
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    with tx() as c:
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
        check = can_lend(item["status"], active)
        if not check["ok"]:
            raise HTTPException(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (iid, body.borrower, "active", body.due_date, _now()))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
        lid = cur.lastrowid
    return {"loan_id": lid}

class ReturnIn(BaseModel):
    expected_grace: int | None = None

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int, body: ReturnIn | None = None):
    body = body or ReturnIn()
    with tx() as c:
        loan = c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id WHERE loans.id=?",
            (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        if loan["status"] != "active":
            raise HTTPException(400, "not_active")
        # The settle verdict is read in the same write transaction that
        # performs it. BEGIN IMMEDIATE serializes against a concurrent
        # settings update, and if grace moved since the caller's preview we
        # refuse to settle under a different overdue world.
        grace = _grace_days(c)
        if body.expected_grace is not None and body.expected_grace != grace:
            raise HTTPException(409, "stale_preview")
        overdue = is_overdue(loan["due_date"], _today(), loan["status"], grace)
        c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?", (_now(), lid))
        c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    return {"ok": True, "grace_days": grace, "overdue": overdue}

@app.get("/api/loans/{lid}/return-preview")
def return_preview(lid: int):
    with snapshot() as c:
        loan = c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id WHERE loans.id=?",
            (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        grace = _grace_days(c)
        overdue = is_overdue(loan["due_date"], _today(), loan["status"], grace)
    return {
        "loan_id": lid,
        "title": loan["title"],
        "borrower": loan["borrower"],
        "due_date": loan["due_date"],
        "grace_days": grace,
        "overdue": overdue,
    }

@app.get("/api/loans")
def loans():
    with snapshot() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
        grace = _grace_days(c)
        cls = classify_loans(rows, _today(), grace)
    return {**cls, "grace_days": grace}

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows

class SettingsIn(BaseModel):
    grace_days: Any

@app.put("/api/settings")
def update_settings(body: SettingsIn):
    n = parse_grace_days(body.grace_days)
    if n is None:
        # Whole-order failure: validated before any write transaction opens,
        # so the stored value and every overdue view stay at the old world.
        raise HTTPException(400, "invalid_grace_days")
    with tx() as c:
        c.execute("INSERT INTO settings(key,value) VALUES ('grace_days',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(n),))
    return {"grace_days": n}
