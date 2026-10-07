import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _ids(rows):
    return {r["id"] for r in rows}


def _seed_loan_id(client):
    """种子样例的 loan id（其 item_id=4，loan 表自增独立编号）。"""
    payload = client.get("/api/loans").json()
    for bucket in (payload["active"], payload["overdue"], payload["returned"]):
        for r in bucket:
            if r.get("item_id") == 4:
                return r["id"]
    raise AssertionError("seed loan not found")


@pytest.fixture()
def seed_loan(client):
    return _seed_loan_id(client)


def _worlds(client):
    """看板与借还记录对同一笔在借必须给出同一判定。"""
    b = client.get("/api/board").json()
    L = client.get("/api/loans").json()
    return b, L


def test_seed_sample_overdue_in_board_and_records(client, seed_loan):
    b, L = _worlds(client)
    assert b["counts"]["overdue"] == 1
    assert _ids(b["overdue"]) == {seed_loan}
    assert _ids(L["overdue"]) == {seed_loan}
    assert _ids(b["active"]) == _ids(L["active"]) == set()
    assert b["grace_days"] == L["grace_days"] == 0


def test_changing_grace_moves_red_in_every_view_together(client, seed_loan):
    r = client.put("/api/settings", json={"grace_days": 100000})
    assert r.status_code == 200 and r.json() == {"grace_days": 100000}
    b, L = _worlds(client)
    assert b["counts"] == {"available": 3, "active": 1, "overdue": 0}
    assert _ids(b["active"]) == {seed_loan}
    assert _ids(L["active"]) == {seed_loan}
    assert _ids(b["overdue"]) == _ids(L["overdue"]) == set()
    p = client.get(f"/api/loans/{seed_loan}/return-preview").json()
    assert p["grace_days"] == 100000 and p["overdue"] is False

    # 改回去：红标必须在所有入口一起回来，不回一半。
    client.put("/api/settings", json={"grace_days": 0})
    b, L = _worlds(client)
    assert b["counts"]["overdue"] == 1
    assert _ids(b["overdue"]) == _ids(L["overdue"]) == {seed_loan}
    assert _ids(b["active"]) == _ids(L["active"]) == set()


@pytest.mark.parametrize("bad", [-1, "-1", "abc", "", "  ", 1.5, True, False, None, "3天"])
def test_invalid_grace_fails_whole_order_keeps_old_world(client, bad):
    client.put("/api/settings", json={"grace_days": 7})
    before_b = client.get("/api/board").json()
    before_l = client.get("/api/loans").json()

    r = client.put("/api/settings", json={"grace_days": bad})
    assert r.status_code == 400

    assert client.get("/api/settings").json()["grace_days"] == "7"
    after_b = client.get("/api/board").json()
    after_l = client.get("/api/loans").json()
    # 失败回包后顶细条与借还记录停在点前。
    assert after_b["counts"] == before_b["counts"]
    assert _ids(after_b["overdue"]) == _ids(before_b["overdue"])
    assert _ids(after_l["overdue"]) == _ids(before_l["overdue"])
    assert after_b["grace_days"] == after_l["grace_days"] == 7


def test_preview_and_settle_use_same_world(client, seed_loan):
    p = client.get(f"/api/loans/{seed_loan}/return-preview").json()
    assert p["overdue"] is True and p["grace_days"] == 0
    r = client.post(
        f"/api/loans/{seed_loan}/return",
        json={"expected_grace": p["grace_days"]},
    )
    assert r.status_code == 200
    s = r.json()
    assert s["overdue"] == p["overdue"] and s["grace_days"] == p["grace_days"]
    b = client.get("/api/board").json()
    assert b["counts"] == {"available": 4, "active": 0, "overdue": 0}


def test_settle_rejected_when_grace_moved_between_preview_and_commit(client, seed_loan):
    p = client.get(f"/api/loans/{seed_loan}/return-preview").json()
    assert p["grace_days"] == 0
    client.put("/api/settings", json={"grace_days": 100000})

    # 预演通过的那一套已过期，提交不得按另一套静默结。
    r = client.post(
        f"/api/loans/{seed_loan}/return",
        json={"expected_grace": p["grace_days"]},
    )
    assert r.status_code == 409 and r.json()["detail"] == "stale_preview"
    b = client.get("/api/board").json()
    assert b["counts"]["active"] == 1 and b["counts"]["available"] == 3

    # 重新预演后按新世界可正常结算。
    p2 = client.get(f"/api/loans/{seed_loan}/return-preview").json()
    assert p2["overdue"] is False
    r2 = client.post(
        f"/api/loans/{seed_loan}/return",
        json={"expected_grace": p2["grace_days"]},
    )
    assert r2.status_code == 200 and r2.json()["overdue"] is False


def test_return_without_expected_grace_still_settles(client, seed_loan):
    r = client.post(f"/api/loans/{seed_loan}/return", json={})
    assert r.status_code == 200 and r.json()["grace_days"] == 0
