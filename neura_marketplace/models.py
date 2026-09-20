from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GoalBrief(BaseModel):
    objective: str
    product: str | None = None
    target_user: str | None = None
    desired_outputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(default_factory=list)


class JarvisDecision(BaseModel):
    ready: bool
    question: str | None = None
    brief: GoalBrief | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    status: Literal["needs_input", "accepted", "error"]
    message: str
    run_id: str | None = None


class A2AJob(BaseModel):
    run_id: str
    callback_url: str
    goal: GoalBrief


class A2AMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    sender: str
    recipient: str
    type: Literal["question", "progress", "result", "failure"]
    payload: dict[str, Any]
    correlation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PlanTask(BaseModel):
    id: str
    title: str
    objective: str
    capability_query: str
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    tasks: list[PlanTask]


class AgentListing(BaseModel):
    id: str
    name: str
    division: str
    description: str
    vibe: str | None = None
    source_path: str
    sha256: str


class AgentSelection(BaseModel):
    selected_agent_id: str
    rationale: str
    confidence: float = Field(ge=0, le=1)


class AgentContract(BaseModel):
    contract_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    task_id: str
    buyer_agent: str = "MARCELO"
    seller_agent: str
    objective: str
    acceptance_criteria: list[str]
    status: Literal["hired", "running", "submitted", "accepted", "rejected"] = "hired"


class VerificationResult(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    score: float = Field(ge=0, le=1)
    failed_criteria: list[str] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    task_id: str
    title: str
    worker_agent_id: str
    worker_agent_name: str
    output: str
    verification: VerificationResult
    attempts: int
