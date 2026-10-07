from datetime import date, datetime, timezone
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, snapshot, write_tx
from app.engines.borrow_rules import can_lend, classify_loans, is_overdue, parse_grace_days
from app.engines import grace_fork as gf

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

def _setting_int(c, key: str) -> int:
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    n = parse_grace_days(row["value"]) if row else None
    return n if n is not None else 0

def _grace_days(c) -> int:
    return _setting_int(c, "grace_days")

def _grace_version(c) -> int:
    return _setting_int(c, "grace_version")

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
        grace = gf.board_grace(c, _grace_days)
        version = _grace_version(c)
    cls = classify_loans(loans, date.today().isoformat(), grace)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": gf.paint_overdue_style(cls["overdue"], grace),
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
        "grace_days": grace,
        "grace_version": version,
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
    c = connect()
    item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not item: c.close(); raise HTTPException(404, "item")
    active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
    check = can_lend(item["status"], active)
    if not check["ok"]:
        c.close(); raise HTTPException(409, check["reason"])
    cur = c.execute(
        "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
        (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
    c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
    c.commit(); lid = cur.lastrowid; c.close(); return {"loan_id": lid}

class ReturnIn(BaseModel):
    grace_version: int | None = None

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int, body: ReturnIn | None = None):
    with write_tx() as c:
        loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        if loan["status"] != "active":
            raise HTTPException(400, "not_active")
        # The confirm dialog judged overdue with the preview's grace version;
        # if settings moved since, refuse rather than settle in a second world.
        if body is not None and body.grace_version is not None:
            if body.grace_version != _grace_version(c):
                raise HTTPException(409, "grace_changed")
        c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
                  (datetime.now(timezone.utc).isoformat(), lid))
        c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    return {"ok": True}

@app.get("/api/loans/{lid}/return-preview")
def return_preview(lid: int):
    with snapshot() as c:
        loan = c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id WHERE loans.id=?",
            (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        grace = _grace_days(c)
        version = _grace_version(c)
    return {
        "loan_id": lid,
        "title": loan["title"],
        "borrower": loan["borrower"],
        "due_date": loan["due_date"],
        "grace_days": grace,
        "grace_version": version,
        "overdue": is_overdue(loan["due_date"], date.today().isoformat(), loan["status"], grace),
    }

@app.get("/api/loans")
def loans():
    with snapshot() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
        grace = gf.record_grace(c, _grace_days)
        version = _grace_version(c)
    cls = classify_loans(rows, date.today().isoformat(), grace)
    return {**cls, "grace_days": grace, "grace_version": version}

@app.get("/api/settings")
def settings():
    with snapshot() as c:
        rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
    return rows

class SettingsIn(BaseModel):
    grace_days: Any

@app.put("/api/settings")
def update_settings(body: SettingsIn):
    n = parse_grace_days(body.grace_days)
    if n is None:
        # Whole request fails before any write; every view stays pre-change.
        raise HTTPException(400, "invalid_grace_days")
    with write_tx() as c:
        cur = c.execute("SELECT value FROM settings WHERE key='grace_days'").fetchone()
        if cur and cur["value"] == str(n):
            v = _grace_version(c)  # same value, same world: no version bump
        else:
            c.execute("INSERT INTO settings(key,value) VALUES ('grace_days',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(n),))
            v = _grace_version(c) + 1
            c.execute("INSERT INTO settings(key,value) VALUES ('grace_version',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(v),))
    return {"grace_days": n, "grace_version": v}
