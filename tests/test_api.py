from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_browser_demo_is_served():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Quorum" in response.text
    assert "Live editing" in response.text
    assert "Join an existing incident room" in response.text


def test_document_version_conflict_and_restore():
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": f"owner-{uuid4().hex}@example.com", "password": "a-long-test-password"
        })
        assert registered.status_code == 201
        headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
        workspace = client.post("/api/v1/workspaces", headers=headers, json={"name": "Design"}).json()
        created = client.post(f"/api/v1/workspaces/{workspace['workspace_id']}/documents", headers=headers,
                              json={"title": "Notes", "content": "first"}).json()
        doc_id = created["document_id"]
        updated = client.put(f"/api/v1/documents/{doc_id}", headers=headers,
                             json={"content": "second", "base_version": 1})
        assert updated.status_code == 200
        conflict = client.put(f"/api/v1/documents/{doc_id}", headers=headers,
                              json={"content": "stale", "base_version": 1})
        assert conflict.status_code == 409
        restored = client.post(f"/api/v1/documents/{doc_id}/versions/1/restore", headers=headers)
        assert restored.status_code == 200
        assert restored.json()["content"] == "first"
        assert restored.json()["version"] == 3


def test_incident_room_persists_a_timeline_and_can_resolve():
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": f"commander-{uuid4().hex}@example.com", "password": "a-long-test-password"
        })
        headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
        created = client.post("/api/v1/incidents", headers=headers, json={
            "title": "Checkout errors", "severity": "high"
        })
        assert created.status_code == 201
        incident_id = created.json()["incident_id"]
        update = client.post(f"/api/v1/incidents/{incident_id}/events", headers=headers,
                             json={"message": "Rolled back the payment deploy."})
        assert update.status_code == 201
        resolved = client.post(f"/api/v1/incidents/{incident_id}/resolve", headers=headers)
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"
        assert [event["type"] for event in resolved.json()["events"]] == ["opened", "update", "resolved"]
        rejected = client.post(f"/api/v1/incidents/{incident_id}/events", headers=headers,
                               json={"message": "This must not be accepted."})
        assert rejected.status_code == 409

        outsider = client.post("/api/v1/auth/register", json={
            "email": f"outsider-{uuid4().hex}@example.com", "password": "a-long-test-password"
        })
        outsider_headers = {"Authorization": "Bearer " + outsider.json()["access_token"]}
        forbidden = client.get(f"/api/v1/incidents/{incident_id}", headers=outsider_headers)
        assert forbidden.status_code == 403
