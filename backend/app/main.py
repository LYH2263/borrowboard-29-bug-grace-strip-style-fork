from datetime import date, datetime, timezone
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.borrow_rules import can_lend, classify_loans, is_overdue, parse_grace_days
from app.engines import grace_fork as gf

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

def _grace_days(c) -> int:
    row = c.execute("SELECT value FROM settings WHERE key='grace_days'").fetchone()
    n = parse_grace_days(row["value"]) if row else None
    return n if n is not None else 0

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/board")
def board():
    c = connect()
    available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    grace = gf.board_grace(c, _grace_days)
    c.close()
    cls = classify_loans(loans, date.today().isoformat(), grace)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": gf.paint_overdue_style(cls["overdue"], grace),
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
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

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
              (datetime.now(timezone.utc).isoformat(), lid))
    c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    c.commit(); c.close(); return {"ok": True}

@app.get("/api/loans/{lid}/return-preview")
def return_preview(lid: int):
    c = connect()
    loan = c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id WHERE loans.id=?",
        (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    grace = _grace_days(c)
    c.close()
    return {
        "loan_id": lid,
        "title": loan["title"],
        "borrower": loan["borrower"],
        "due_date": loan["due_date"],
        "grace_days": grace,
        "overdue": is_overdue(loan["due_date"], date.today().isoformat(), loan["status"], grace),
    }

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    grace = gf.record_grace(c, _grace_days)
    c.close()
    return classify_loans(rows, date.today().isoformat(), grace)

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows

class SettingsIn(BaseModel):
    grace_days: Any

@app.put("/api/settings")
def update_settings(body: SettingsIn):
    n = parse_grace_days(body.grace_days)
    if n is None:
        raise HTTPException(400, "invalid_grace_days")
    c = connect()
    c.execute("INSERT INTO settings(key,value) VALUES ('grace_days',?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(n),))
    c.commit(); c.close(); return {"grace_days": n}
