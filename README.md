# Quorum

Quorum is a multi-user workspace API for shared documents. Users register and sign in, create workspaces, invite registered members, create documents, edit them through REST or WebSockets, and inspect or restore document revisions.

## Run locally

```bash
docker compose up --build
```

The API is at `http://localhost:8002`; interactive docs are at `/docs`. Register an account and use its `access_token` as a bearer token in Swagger or subsequent API requests. The API provides `/health`, `/api/v1/auth/register`, `/api/v1/auth/login`, workspace, member, document, and version-history routes.

For a live document session, connect to `ws://localhost:8002/api/v1/documents/{document_id}/live?token={access_token}`. Send JSON such as `{"type":"document.update","base_version":1,"content":"Updated shared text"}`. Successful edits are persisted in PostgreSQL, assigned a new version, returned to the sender, and broadcast to other connected clients. An edit based on an old version receives a conflict response with the current content and version.

## Current design limits

- Authentication uses signed bearer tokens with a 12-hour expiry; passwords are hashed with Argon2. Workspace members can read and edit documents; only owners can invite members.
- Version history stores full document snapshots. Restore creates a new version, preserving prior history.
- WebSocket fan-out is in-process, so live broadcasts currently require a single API process. PostgreSQL remains the canonical document state; this is optimistic conflict detection, not character-level OT/CRDT merging.
- Benchmark claims for concurrent clients and P95 latency should be added only after running a repeatable load test.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

GitHub Actions runs the test suite on pushes and pull requests.
