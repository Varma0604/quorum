from fastapi.testclient import TestClient

from app.main import app


def test_document_version_conflict_and_restore():
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": "owner@example.com", "password": "a-long-test-password"
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
