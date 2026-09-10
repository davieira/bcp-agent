import logging
import pytest
from fastapi.testclient import TestClient

from src.api.server import app, process_bcp_calculation, jobs
from bcp.logger import setup_logger

@pytest.fixture(autouse=True)
def clear_jobs():
    jobs.clear()
    yield
    jobs.clear()


def test_root():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "BCP Calculator API"


def test_calculate_and_status(monkeypatch):
    client = TestClient(app)

    # Stub calculation to be deterministic and fast
    def fake_process(job_id: str, story_content: str, provider: str):
        jobs[job_id] = {"status": "completed", "result": {"story_name": "X", "total_bcp": 1, "breakdown": {}}}

    monkeypatch.setattr("src.api.server.process_bcp_calculation", fake_process)

    resp = client.post("/calculate", json={"content": "A", "provider": "openai"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Immediately check status
    status = client.get(f"/status/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "completed"
    assert data["result"]["total_bcp"] == 1


def test_list_sources():
    client = TestClient(app)
    resp = client.get("/sources")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["sources"]]
    assert "file" in names
    assert "trello" in names


def test_calculate_from_source(monkeypatch):
    client = TestClient(app)

    def fake_process(job_id: str, source_name: str, query, provider: str, write_back: bool = True, write_custom_fields: bool = False):
        jobs[job_id] = {
            "status": "completed",
            "result": {"story_name": "X", "total_bcp": 2, "source": {"type": source_name}},
        }

    monkeypatch.setattr("src.api.server.process_source_calculation", fake_process)

    resp = client.post(
        "/calculate/source",
        json={"source": "trello", "id": "https://trello.com/c/abc123", "provider": "openai"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/status/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "completed"
    assert data["result"]["source"]["type"] == "trello"


def test_calculate_from_source_requires_target():
    client = TestClient(app)
    resp = client.post("/calculate/source", json={"source": "trello", "provider": "openai"})
    assert resp.status_code == 400


def test_calculate_from_unknown_source():
    client = TestClient(app)
    resp = client.post("/calculate/source", json={"source": "jira", "id": "PROJ-1"})
    assert resp.status_code == 400

