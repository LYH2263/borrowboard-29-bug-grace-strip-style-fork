"""Grace-change consistency: one overdue world across every entry point."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

SEED_LOAN_ID = 1  # 种子「已外借样例」, due 2020-06-01

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c

def ids(rows):
    return {l["id"] for l in rows}

def world(client):
    b = client.get("/api/board").json()
    l = client.get("/api/loans").json()
    p = client.get(f"/api/loans/{SEED_LOAN_ID}/return-preview").json()
    return b, l, p

def assert_one_world(b, l, p, grace):
    assert b["grace_days"] == l["grace_days"] == p["grace_days"] == grace
    assert b["grace_version"] == l["grace_version"] == p["grace_version"]
    # 顶细条逾期数 == 借还记录逾期段;在借栏红标与计数不拧
    assert b["counts"]["overdue"] == len(b["overdue"]) == len(l["overdue"])
    assert ids(b["overdue"]) == ids(l["overdue"])
    assert ids(b["active"]) == ids(l["active"])
    assert all(x["overdue"] for x in b["overdue"])
    assert not any(x["overdue"] for x in b["active"])

def test_board_records_preview_share_one_overdue_world(client):
    b, l, p = world(client)
    assert_one_world(b, l, p, 0)
    assert SEED_LOAN_ID in ids(l["overdue"]) and p["overdue"] is True

    r = client.put("/api/settings", json={"grace_days": 100000})
    assert r.status_code == 200
    b, l, p = world(client)
    assert_one_world(b, l, p, 100000)
    assert SEED_LOAN_ID in ids(l["active"]) and p["overdue"] is False
    assert b["grace_version"] == r.json()["grace_version"]

def test_revert_restores_every_entry_not_half(client):
    client.put("/api/settings", json={"grace_days": 7})
    b, l, p = world(client)
    assert_one_world(b, l, p, 7)
    assert SEED_LOAN_ID in ids(l["overdue"])  # 2020-06-01 + 7d 仍逾期

    client.put("/api/settings", json={"grace_days": 0})
    b, l, p = world(client)
    assert_one_world(b, l, p, 0)
    assert SEED_LOAN_ID in ids(l["overdue"]) and p["overdue"] is True

def test_invalid_grace_fails_whole_and_views_stay(client):
    assert client.put("/api/settings", json={"grace_days": 5}).status_code == 200
    before_b, before_l, _ = world(client)
    for bad in ["abc", "", "-1", -1, True, 3.5, "1e3", "０", 10**10]:
        r = client.put("/api/settings", json={"grace_days": bad})
        assert r.status_code == 400, f"accepted invalid grace: {bad!r}"
    after_b, after_l, _ = world(client)
    # 失败回包后顶细条与借还记录停在点前
    assert after_b["grace_days"] == after_l["grace_days"] == 5
    assert after_b["grace_version"] == before_b["grace_version"]
    assert after_l["grace_version"] == before_l["grace_version"]
    assert ids(after_b["overdue"]) == ids(before_b["overdue"])
    assert ids(after_l["overdue"]) == ids(before_l["overdue"])
    assert client.get("/api/settings").json()["grace_days"] == "5"

def test_huge_grace_within_range_means_never_overdue(client):
    r = client.put("/api/settings", json={"grace_days": 999_999_999})
    assert r.status_code == 200
    b, l, p = world(client)
    assert_one_world(b, l, p, 999_999_999)
    assert b["counts"]["overdue"] == 0 and p["overdue"] is False

def test_seed_loan_judged_same_as_fresh_loan(client):
    iid = client.post("/api/items", json={"title": "新物", "owner": "阿明"}).json()["id"]
    lid = client.post(f"/api/items/{iid}/lend",
                      json={"borrower": "邻居乙", "due_date": "2020-06-01"}).json()["loan_id"]
    l = client.get("/api/loans").json()
    assert {SEED_LOAN_ID, lid} <= ids(l["overdue"])  # 同一应还日,同一判
    client.put("/api/settings", json={"grace_days": 100000})
    b = client.get("/api/board").json()
    l = client.get("/api/loans").json()
    assert {SEED_LOAN_ID, lid} <= ids(l["active"])
    assert {SEED_LOAN_ID, lid} <= ids(b["active"])

def test_return_submit_after_grace_change_conflicts_then_repreview(client):
    p = client.get(f"/api/loans/{SEED_LOAN_ID}/return-preview").json()
    client.put("/api/settings", json={"grace_days": 3})
    # 预演是旧世界,提交必须拒,不得按另一套结
    r = client.post(f"/api/loans/{SEED_LOAN_ID}/return", json={"grace_version": p["grace_version"]})
    assert r.status_code == 409 and r.json()["detail"] == "grace_changed"
    l = client.get("/api/loans").json()
    assert SEED_LOAN_ID in ids(l["active"]) | ids(l["overdue"])  # 仍在借,未半结
    # 重新预演(新世界)后提交成功
    p2 = client.get(f"/api/loans/{SEED_LOAN_ID}/return-preview").json()
    assert p2["grace_version"] != p["grace_version"]
    r2 = client.post(f"/api/loans/{SEED_LOAN_ID}/return", json={"grace_version": p2["grace_version"]})
    assert r2.status_code == 200
    l2 = client.get("/api/loans").json()
    assert SEED_LOAN_ID in ids(l2["returned"])

def test_resaving_same_grace_keeps_world(client):
    p = client.get(f"/api/loans/{SEED_LOAN_ID}/return-preview").json()
    r = client.put("/api/settings", json={"grace_days": 0})  # 与种子默认相同
    assert r.status_code == 200
    assert r.json()["grace_version"] == p["grace_version"]  # 值没变,世界没变
    ok = client.post(f"/api/loans/{SEED_LOAN_ID}/return", json={"grace_version": p["grace_version"]})
    assert ok.status_code == 200

def test_return_without_version_still_works(client):
    assert client.post(f"/api/loans/{SEED_LOAN_ID}/return").status_code == 200
