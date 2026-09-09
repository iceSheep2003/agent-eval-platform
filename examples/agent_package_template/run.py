"""Runnable Agent service with DeepEval tracing and AgenticBench adaptation."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import deepeval
import uvicorn
from deepeval.tracing import observe, update_current_span, update_current_trace
from fastapi import FastAPI
from pydantic import BaseModel, Field

from agentic_bench_adapter import AgenticBenchAdapter


class InvokeRequest(BaseModel):
    input: str | None = None
    task_id: str | None = None
    task: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    observation: dict[str, Any] | None = None
    limits: dict[str, Any] = Field(default_factory=dict)


@observe(type="tool", description="Look up a business object in the demo data source")
async def lookup(identifier: str) -> dict[str, Any]:
    output = {"id": identifier, "status": "found"}
    update_current_span(input={"identifier": identifier}, output=output)
    return output


@observe(type="agent", available_tools=["lookup"])
async def agent_step(state: dict[str, Any]) -> dict[str, Any]:
    """Replace this deterministic body with your framework or model call."""
    instruction = str(state.get("instruction") or "")
    tool_result = await lookup(state.get("task_id") or "demo")
    output = {"message": f"已处理：{instruction}", "tool_result": tool_result}
    update_current_trace(
        name="Eval Loom imported agent",
        input=state,
        output=output,
        metadata={"agent_version": os.getenv("AGENT_VERSION", "0.1.0")},
    )
    return {"output": output}


adapter = AgenticBenchAdapter(agent_step)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await deepeval.a_flush_traces(timeout=10.0)


app = FastAPI(title="Eval Loom Agent", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ready", "protocol": adapter.protocol}


@app.post("/invoke")
async def invoke(request: InvokeRequest) -> dict[str, Any]:
    return await adapter.invoke(request.model_dump(exclude_none=True))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

