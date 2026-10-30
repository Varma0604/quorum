"""Authenticated WebSocket benchmark for a running Quorum gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from urllib.parse import quote

import httpx
import websockets


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8002")
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--updates", type=int, default=100)
    parser.add_argument("--expected-instances", type=int, default=2)
    args = parser.parse_args()
    if args.clients < 2 or args.updates < 1 or args.expected_instances < 1:
        raise SystemExit("clients must be at least 2; updates and expected-instances must be positive")

    run_id = uuid.uuid4().hex[:10]
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        async def register(label: str):
            response = await client.post("/api/v1/auth/register", json={
                "email": f"benchmark-{run_id}-{label}@example.test",
                "password": "benchmark-password-123",
            })
            response.raise_for_status()
            return response.json()

        owner = await register("owner")
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        workspace = await client.post("/api/v1/workspaces", headers=owner_headers, json={"name": "benchmark"})
        workspace.raise_for_status()
        workspace_id = workspace.json()["workspace_id"]
        members = [owner]
        for number in range(args.clients - 1):
            member = await register(f"member-{number}")
            invite = await client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=owner_headers,
                params={"email": member["email"]},
            )
            invite.raise_for_status()
            members.append(member)
        document = await client.post(
            f"/api/v1/workspaces/{workspace_id}/documents",
            headers=owner_headers,
            json={"title": "benchmark", "content": "version 1"},
        )
        document.raise_for_status()
        document_id = document.json()["document_id"]

    websocket_base = args.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    urls = [f"{websocket_base}/api/v1/documents/{document_id}/live?token={quote(member['access_token'])}" for member in members]
    sockets = [await websockets.connect(url, proxy=None) for url in urls]
    try:
        welcomes = [json.loads(await socket.recv()) for socket in sockets]
        instances = {welcome["instance_id"] for welcome in welcomes if welcome.get("type") == "document.connected"}
        if len(instances) < args.expected_instances:
            raise RuntimeError(f"expected {args.expected_instances} API instances but observed {len(instances)}: {sorted(instances)}")

        writer, readers = sockets[0], sockets[1:]
        latencies = []
        for version in range(2, args.updates + 2):
            started = time.perf_counter()
            await writer.send(json.dumps({
                "type": "document.update", "base_version": version - 1, "content": f"benchmark version {version}",
            }))
            acknowledgement = json.loads(await writer.recv())
            broadcasts = [json.loads(message) for message in await asyncio.gather(*(reader.recv() for reader in readers))]
            if acknowledgement.get("version") != version or any(event.get("version") != version for event in broadcasts):
                raise RuntimeError(f"unexpected update response at version {version}")
            latencies.append((time.perf_counter() - started) * 1000)
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets))

    print(json.dumps({
        "workload": {"clients": args.clients, "updates": args.updates, "expected_api_instances": args.expected_instances},
        "result": {"observed_api_instances": len(instances), "successful_broadcasts": args.updates * (args.clients - 1),
                   "failed_broadcasts": 0, "p50_update_ms": round(statistics.median(latencies), 2),
                   "p95_update_ms": round(percentile(latencies, 0.95), 2)},
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
