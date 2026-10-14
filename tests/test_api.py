"""HTTP API: auth, rate limiting, runs and replies, uploads, run scoping, health checks."""
import dataclasses
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from workflow_agent.api import create_app

KEY = "test-key-alice"
OTHER = "test-key-bob"


@pytest.fixture()
def client(settings, agent):
    s = dataclasses.replace(settings, api_keys=(KEY, OTHER), rate_limit_per_minute=1000, max_upload_mb=0.05)
    with TestClient(create_app(settings=s, agent=agent)) as c:
        yield c


def auth(key=KEY):
    return {"X-API-Key": key}


def test_health_endpoints_need_no_key(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["workflows"] == 10


def test_requests_without_a_valid_key_are_rejected(client):
    assert client.get("/v1/workflows").status_code == 401
    assert client.get("/v1/workflows", headers=auth("wrong")).status_code == 401
    assert client.get("/v1/workflows", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200


def test_workflows_listing(client):
    wfs = client.get("/v1/workflows", headers=auth()).json()
    assert len(wfs) == 10
    assert next(w for w in wfs if w["id"] == "WF001")["accepts_upload"]


def test_run_then_reply(client):
    r = client.post("/v1/runs", json={"request": "Where is my order?"}, headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["awaiting_reply"] and body["question"]
    assert r.headers["X-Request-ID"]
    r2 = client.post(f"/v1/runs/{body['run_id']}/reply", json={"answer": "It's ORD-1003"}, headers=auth())
    assert r2.status_code == 200
    done = r2.json()
    assert done["status"] == "completed" and done["workflow"]["id"] == "WF005"
    assert "ORD-1003" in done["markdown"]

    stored = client.get(f"/v1/runs/{body['run_id']}", headers=auth()).json()
    assert stored["status"] == "completed" and stored["steps"]
    assert any(run["run_id"] == body["run_id"] for run in client.get("/v1/runs", headers=auth()).json())


def test_runs_are_private_to_their_key(client):
    run_id = client.post("/v1/runs", json={"request": "Where is my order?"}, headers=auth()).json()["run_id"]
    assert client.get(f"/v1/runs/{run_id}", headers=auth(OTHER)).status_code == 404
    assert client.post(f"/v1/runs/{run_id}/reply", json={"answer": "ORD-1001"}, headers=auth(OTHER)).status_code == 404
    assert all(r["run_id"] != run_id for r in client.get("/v1/runs", headers=auth(OTHER)).json())


def test_reply_to_finished_run_is_422(client):
    run_id = client.post("/v1/runs", json={"request": "Which products need restocking?"}, headers=auth()).json()["run_id"]
    assert client.post(f"/v1/runs/{run_id}/reply", json={"answer": "hi"}, headers=auth()).status_code == 422


def test_invalid_bodies(client):
    assert client.post("/v1/runs", json={"request": ""}, headers=auth()).status_code == 422
    assert client.post("/v1/runs", json={"request": "   "}, headers=auth()).status_code == 422


def test_upload_drives_the_workflow(client):
    csv = (b"sku,product_name,category,current_stock,minimum_stock,unit_cost,supplier\n"
           b"ZZ-1,Uploaded Widget,Misc,1,10,2.0,Acme\nZZ-2,Fine Widget,Misc,50,10,2.0,Acme\n")
    r = client.post("/v1/runs/upload", data={"request": "Which products need restocking?"},
                    files={"file": ("stock.csv", csv, "text/csv")}, headers=auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow"]["id"] == "WF001" and body["status"] == "completed"
    assert "upload" in body["inputs"]["inventory_file"]
    assert "Uploaded Widget" in body["markdown"] and "Fine Widget" not in body["answer"]


def test_upload_rejections(client):
    req = {"request": "Which products need restocking?"}
    assert client.post("/v1/runs/upload", data=req, files={"file": ("x.exe", b"MZ", "application/octet-stream")},
                       headers=auth()).status_code == 415
    big = b"a,b\n" + b"1,2\n" * 20_000
    assert client.post("/v1/runs/upload", data=req, files={"file": ("big.csv", big, "text/csv")},
                       headers=auth()).status_code == 413
    assert client.post("/v1/runs/upload", data=req, files={"file": ("bad.csv", b"\xff\xfe\x00bad", "text/csv")},
                       headers=auth()).status_code == 422
    assert client.post("/v1/runs/upload", data=req, files={"file": ("fake.xlsx", b"not a zip", "application/zip")},
                       headers=auth()).status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "no content types")
    assert client.post("/v1/runs/upload", data=req, files={"file": ("nope.xlsx", buf.getvalue(), "application/zip")},
                       headers=auth()).status_code == 422


def test_rate_limit(settings, agent):
    s = dataclasses.replace(settings, api_keys=(KEY,), rate_limit_per_minute=2)
    with TestClient(create_app(settings=s, agent=agent)) as c:
        assert c.get("/v1/workflows", headers=auth()).status_code == 200
        assert c.get("/v1/workflows", headers=auth()).status_code == 200
        r = c.get("/v1/workflows", headers=auth())
        assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_production_config_is_validated(settings, agent):
    s = dataclasses.replace(settings, env="production", api_keys=())
    with pytest.raises(RuntimeError, match="API_KEYS"):
        create_app(settings=s, agent=agent)
