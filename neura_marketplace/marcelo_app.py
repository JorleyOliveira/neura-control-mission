from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException

from .config import settings
from .db import Database
from .marcelo_core import MarceloOrchestrator
from .marketplace import AgentMarketplace
from .models import A2AJob
from .neuralake import NeuraLakeClient


app = FastAPI(title="MARCELO", version="0.1.0")
db = Database(settings.database_path)
orchestrator: MarceloOrchestrator | None = None


@app.on_event("startup")
async def startup() -> None:
    global orchestrator
    await db.init()
    marketplace = AgentMarketplace(db, settings.effective_agent_dataset_dir)
    indexed = await marketplace.index()
    if indexed == 0:
        raise RuntimeError("Marketplace contains no agents")
    orchestrator = MarceloOrchestrator(db, marketplace, NeuraLakeClient())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "MARCELO"}


@app.post("/a2a/jobs", status_code=202)
async def accept_job(job: A2AJob) -> dict[str, str]:
    if orchestrator is None:
        raise HTTPException(503, "MARCELO is not initialized")
    if not await db.get_run(job.run_id):
        # JARVIS normally creates it in the shared local DB; this keeps direct A2A calls usable.
        await db.create_run(job.run_id, "direct-a2a", job.goal.objective)
    asyncio.create_task(orchestrator.run_job(job))
    return {"run_id": job.run_id, "status": "accepted"}
