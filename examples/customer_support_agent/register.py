"""One-time helper: register the agent (SDK connect_type) and mint an ``evk_`` upload key.

Equivalent to the console flow "添加 Agent → 使用 SDK 接入". This script only talks to
the platform control plane to create a record and an SDK key; the agent itself remains a
plain Python library — it does not expose any HTTP service.

    python -m examples.customer_support_agent.register --base-url http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import os

import httpx


def _client(base: str, workspace: str) -> httpx.Client:
    return httpx.Client(
        base_url=base.rstrip("/"),
        headers={"X-Workspace-Id": workspace},
        timeout=15.0,
        follow_redirects=True,
        trust_env=False,
    )


def register(base: str, identifier: str, password: str, workspace: str, name: str) -> dict[str, str]:
    with _client(base, workspace) as client:
        login = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
        login.raise_for_status()
        agent = client.post(
            "/api/agents",
            json={
                "name": name,
                "description": "客服订单/退款 Agent（SDK 埋点接入，真实 LLM + 确定性兜底）",
                "connect_type": "sdk",
                "environment": "sandbox",
            },
        )
        agent.raise_for_status()
        # 平台统一响应封装：{success, data, errorCode, errorMessage, showType}
        agent_id = agent.json()["data"]["id"]
        key = client.post(f"/api/agents/{agent_id}/sdk-keys", json={"name": "default"})
        key.raise_for_status()
        body = key.json()["data"]
        return {"agent_id": agent_id, "key": body["key"], "ingest_url": body["ingest_url"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Register an SDK-connected agent and print its upload key")
    parser.add_argument("--base-url", default=os.getenv("EVAL_LOOM_BASE_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--identifier", default=os.getenv("EVAL_LOOM_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("EVAL_LOOM_PASSWORD", "admin123"))
    parser.add_argument("--workspace", default=os.getenv("EVAL_LOOM_WORKSPACE", "eval-dev"))
    parser.add_argument("--name", default="customer-support-agent")
    args = parser.parse_args(argv)

    result = register(args.base_url, args.identifier, args.password, args.workspace, args.name)
    print(f"Agent registered (connect_type=sdk): {result['agent_id']}")
    print(f"export EVAL_LOOM_BASE_URL={args.base_url}")
    print(f"export EVAL_LOOM_SDK_KEY={result['key']}")
    print(f"ingest_url: {result['ingest_url']}")


if __name__ == "__main__":
    main()