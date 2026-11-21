# Quorum

Quorum is a multi-user collaboration service for shared documents and live incident command rooms. Users register and sign in, create workspaces, invite registered members, create documents, edit them through REST or WebSockets, and inspect or restore document revisions. Incident rooms add severity, a durable responder timeline, resolution state, and a separate authenticated live-event channel.

## Run locally

```bash
docker compose up --build
```

The browser demo is at `http://localhost:8002`; interactive docs are at `/docs`. In the demo, register and either create a workspace document or launch an incident room. Open the same URL in a second window to see authenticated WebSocket edits and incident timeline events synchronize. The API provides `/health`, `/api/v1/auth/register`, `/api/v1/auth/login`, workspace, member, document, version-history, and incident routes.

For a live document session, connect to `ws://localhost:8002/api/v1/documents/{document_id}/live?token={access_token}`. Send JSON such as `{"type":"document.update","base_version":1,"content":"Updated shared text"}`. Successful edits are persisted in PostgreSQL, assigned a new version, returned to the sender, and broadcast to other connected clients. An edit based on an old version receives a conflict response with the current content and version.

## Current design limits

- Authentication uses signed bearer tokens with a 12-hour expiry; passwords are hashed with Argon2. Workspace members can read and edit documents and incident timelines; only owners can invite members.
- Version history stores full document snapshots. Restore creates a new version, preserving prior history.
- With `REDIS_URL` configured, Redis Pub/Sub relays committed document events between API instances; each instance maintains only its own WebSocket connections. Without it, local development uses in-process fan-out only. The Docker Compose deployment uses PostgreSQL as the canonical document store and Redis for live-event fan-out, while the local development default is SQLite. This is optimistic conflict detection, not character-level OT/CRDT merging.
- **Recorded benchmark (November 21, 2026):** three authenticated local runs
  with 25 WebSocket clients, two API instances, and 100 document updates per
  run delivered all 7,200 expected cross-client broadcasts without failure.
  Median P50/P95 update latency was **4.35ms / 8.77ms**. This is a local
  Docker measurement, not a production capacity claim.
- The hosted demo is intentionally a single API instance. The Docker Compose
  deployment is the reference environment for the two-instance Redis fan-out
  architecture and benchmark.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

GitHub Actions runs the test suite on pushes and pull requests.

## Two-instance, authenticated WebSocket benchmark

After Docker Desktop is running, start the PostgreSQL, Redis, gateway, and two
API instances:

```bash
docker compose up --build --scale api=2
python scripts/load_test.py --clients 10 --updates 100 --expected-instances 2
```

The script creates an owner and authenticated members, opens one WebSocket per
member through the gateway, records the instance IDs that accepted connections,
and verifies that every non-writing client receives every persisted update.
It prints the workload, number of observed instances, successful broadcasts,
failure count, and P50/P95 update latency. Increase `--clients` to 25 only
after the 10-client run completes without failures.
