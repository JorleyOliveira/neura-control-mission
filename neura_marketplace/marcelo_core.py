from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

import httpx

from .config import settings
from .a2a_client import A2AMeshClient
from .capabilities import tools_for_agent
from .tool_protocol import KNOWN_TOOLS
from .db import Database
from .executor import AgentExecutor
from .marketplace import AgentMarketplace
from .models import (
    A2AJob,
    A2AMessage,
    AgentContract,
    AgentListing,
    AgentSelection,
    ExecutionPlan,
    GoalBrief,
    PlanTask,
    TaskResult,
    VerificationResult,
)
from .neuralake import NeuraLakeClient
from .prompt_master import PromptMaster


MARCELO_SYSTEM = """You are MARCELO, the specialized orchestrator for neura-marketplace.
You never do specialist work that should be bought from a marketplace worker.
For every execution task you autonomously perform Discover -> Evaluate -> Hire -> Delegate -> Verify.
No human chooses the worker. Optimize for the parent goal, clear dependency ordering, and minimum unnecessary work.
When asked for JSON, return JSON only.
"""


class MarceloOrchestrator:
    def __init__(self, db: Database, marketplace: AgentMarketplace, llm: NeuraLakeClient):
        self.db = db
        self.marketplace = marketplace
        self.llm = llm
        self.executor = AgentExecutor(marketplace, llm, db)
        # A configured gateway base url switches delegation to the A2A mesh;
        # empty keeps the legacy in-process executor.
        self.mesh = A2AMeshClient() if settings.worker_gateway_base_url else None

    async def run_job(self, job: A2AJob) -> None:
        run_id = job.run_id
        try:
            await self.db.set_run_status(run_id, "running")
            await self.event(run_id, "GOAL_RECEIVED", "MARCELO", {"objective": job.goal.objective})

            plan = await self.plan(run_id, job.goal)
            await self.event(run_id, "PLAN_CREATED", "MARCELO", plan.model_dump())
            for task in plan.tasks:
                await self.db.upsert_task(run_id, task.id, task.title, task.objective, "planned", task.model_dump())

            results = await self.execute_dag(run_id, job.goal, plan)
            final = await self.synthesize(job.goal, results)
            await self.db.set_run_status(run_id, "completed", final)
            await self.event(run_id, "FINAL_RESULT", "MARCELO", {"result": final})
            await self.callback(job.callback_url, A2AMessage(
                run_id=run_id,
                sender="MARCELO",
                recipient="JARVIS",
                type="result",
                payload={"result": final},
            ))
        except Exception as exc:
            await self.db.set_run_status(run_id, "failed")
            await self.event(run_id, "RUN_FAILED", "MARCELO", {"error": str(exc)})
            await self.callback(job.callback_url, A2AMessage(
                run_id=run_id,
                sender="MARCELO",
                recipient="JARVIS",
                type="failure",
                payload={"error": str(exc)},
            ))

    async def plan(self, run_id: str, goal: GoalBrief) -> ExecutionPlan:
        prompt = f"""Create the minimum dependency-aware execution plan for this goal.

GOAL:
{goal.model_dump_json(indent=2)}

Return JSON:
{{
  "tasks": [
    {{
      "id": "short-stable-id",
      "title": "...",
      "objective": "one bounded specialist deliverable",
      "capability_query": "keywords describing the worker capability to discover",
      "depends_on": ["task-id"],
      "acceptance_criteria": ["binary/checkable criterion"],
      "required_tools": ["web.search", "web.fetch", "filesystem.write"]
    }}
  ]
}}

Rules:
- Each task must be substantial enough to hire one specialist.
- Do not name or preselect any marketplace agent.
- If the goal references an internal A2A agent or its URL, that agent is NOT on the public web: never create web-research tasks about it; interacting with it requires a task whose required_tools include a2a.call.
- Honor any task-count limit stated in the goal (for example "exactly 1 task").
- Dependencies must reference earlier task ids and form a DAG.
- For product-launch goals, normally cover research, product/design, implementation/code, and go-to-market/marketing unless clearly irrelevant.
- Keep the plan small enough for a live demo, normally 3-5 tasks.
- required_tools must contain only tools materially required to prove real-world execution.
- Use web.search + web.fetch for tasks requiring current/external evidence.
- Use filesystem.write for durable artifacts when appropriate.
- Use shell.exec for coding/testing tasks that must actually execute code or commands.
- Use a2a.call for tasks that must negotiate or communicate with an external A2A agent.
- Known tools: {', '.join(sorted(KNOWN_TOOLS))}.
"""
        data = await self.llm.json(system=MARCELO_SYSTEM, user=prompt, model=settings.marcelo_model)
        plan = ExecutionPlan.model_validate(data)
        self._validate_dag(plan)
        return plan

    @staticmethod
    def _validate_dag(plan: ExecutionPlan) -> None:
        ids = [task.id for task in plan.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Plan contains duplicate task ids")
        known = set(ids)
        for task in plan.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"Task {task.id} has unknown dependencies: {sorted(unknown)}")
            if task.id in task.depends_on:
                raise ValueError(f"Task {task.id} depends on itself")
            unknown_tools = set(task.required_tools) - KNOWN_TOOLS
            if unknown_tools:
                raise ValueError(f"Task {task.id} requested unknown tools: {sorted(unknown_tools)}")

        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {task.id: task for task in plan.tasks}

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError("Plan contains a dependency cycle")
            visiting.add(task_id)
            for dep in by_id[task_id].depends_on:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in ids:
            visit(task_id)

    async def execute_dag(self, run_id: str, goal: GoalBrief, plan: ExecutionPlan) -> dict[str, TaskResult]:
        pending = {task.id: task for task in plan.tasks}
        completed: dict[str, TaskResult] = {}

        while pending:
            ready = [
                task for task in pending.values()
                if all(dep in completed for dep in task.depends_on)
            ]
            if not ready:
                raise RuntimeError("No executable tasks remain; dependency graph is blocked")

            wave_results = await asyncio.gather(*[
                self.execute_task(
                    run_id=run_id,
                    goal=goal,
                    task=task,
                    dependency_results={dep: completed[dep].output for dep in task.depends_on},
                )
                for task in ready
            ])

            for result in wave_results:
                completed[result.task_id] = result
                pending.pop(result.task_id, None)

        return completed

    async def execute_task(
        self,
        *,
        run_id: str,
        goal: GoalBrief,
        task: PlanTask,
        dependency_results: dict[str, str],
    ) -> TaskResult:
        await self.db.upsert_task(run_id, task.id, task.title, task.objective, "discovering", task.model_dump())
        excluded: set[str] = set()
        feedback: list[str] = []

        for attempt in range(1, settings.max_task_attempts + 1):
            candidates = await self.discover(run_id, task, excluded)
            selection = await self.evaluate(run_id, task, candidates)
            selected = next(item for item in candidates if item.id == selection.selected_agent_id)
            contract = await self.hire(run_id, task, selected, selection)

            delegation = {
                "prompt": PromptMaster.delegation(
                    goal=goal,
                    task=task,
                    dependency_outputs=dependency_results,
                    retry_feedback=feedback,
                    run_id=run_id,
                ),
                "model": settings.worker_code_model if "shell.exec" in task.required_tools else settings.worker_text_model,
            }
            await self.db.set_contract_status(contract.contract_id, "running")
            await self.event(run_id, "DELEGATE", "MARCELO", {
                "task_id": task.id,
                "agent_id": selected.id,
                "agent_name": selected.name,
                "contract_id": contract.contract_id,
                "attempt": attempt,
                # The exact message MARCELO sends to this worker over JSON-RPC message/send.
                "message_to_worker": delegation["prompt"][:3000],
            })

            output = await self._run_agent(
                run_id=run_id,
                task_id=task.id,
                agent_id=selected.id,
                agent_name=selected.name,
                user_prompt=delegation["prompt"],
                model=delegation["model"],
                required_tools=task.required_tools,
            )
            await self.db.add_artifact(run_id, task.id, selected.id, "worker_output", output)
            await self.db.set_contract_status(contract.contract_id, "submitted")
            await self.event(run_id, "WORK_SUBMITTED", selected.name, {
                "task_id": task.id,
                "contract_id": contract.contract_id,
                "attempt": attempt,
                "preview": output[:800],
            })

            verification = await self.verify(run_id, goal, task, selected, output)
            if verification.verdict == "PASS":
                await self.db.set_contract_status(contract.contract_id, "accepted")
                await self.db.upsert_task(run_id, task.id, task.title, task.objective, "completed", {
                    **task.model_dump(), "worker_agent_id": selected.id, "attempts": attempt,
                })
                return TaskResult(
                    task_id=task.id,
                    title=task.title,
                    worker_agent_id=selected.id,
                    worker_agent_name=selected.name,
                    output=output,
                    verification=verification,
                    attempts=attempt,
                )

            await self.db.set_contract_status(contract.contract_id, "rejected")
            feedback = verification.feedback
            excluded.add(selected.id)
            await self.event(run_id, "REJECT_AND_REHIRE", "MARCELO", {
                "task_id": task.id,
                "rejected_agent_id": selected.id,
                "failed_criteria": verification.failed_criteria,
                "feedback": feedback,
                "next_attempt": attempt + 1,
            })

        raise RuntimeError(f"Task {task.id} failed verification after {settings.max_task_attempts} attempts")

    async def _run_agent(
        self,
        *,
        run_id: str,
        task_id: str,
        agent_id: str,
        agent_name: str,
        user_prompt: str,
        model: str,
        required_tools: list[str],
        temperature: float = 0.2,
    ) -> str:
        if self.mesh is None:
            return await self.executor.run(
                run_id=run_id,
                task_id=task_id,
                agent_id=agent_id,
                user_prompt=user_prompt,
                temperature=temperature,
                required_tools=required_tools,
                model=model,
            )

        mirrored_done = asyncio.Event()

        async def forward_progress(event: dict[str, Any]) -> None:
            payload = dict(event.get("payload") or {})
            # A run can execute workers and verifiers concurrently; keep only
            # this delegation's events. The actor check keeps a verifier's
            # replayed feed from re-emitting the worker's earlier events.
            if payload.get("task_id") != task_id or event.get("actor") != agent_name:
                return
            await self.event(
                run_id,
                "WORKER_PROGRESS",
                agent_name,
                {"task_id": task_id, "worker_event_type": event.get("event_type"), **payload},
            )
            if event.get("event_type") == "AGENT_COMPLETED":
                mirrored_done.set()

        watch_task = asyncio.create_task(self._watch_worker_progress(run_id, forward_progress))
        try:
            result = await self.mesh.send_message(
                agent_id=agent_id,
                text=user_prompt,
                required_tools=required_tools,
                model=model,
                run_id=run_id,
                task_id=task_id,
                temperature=temperature,
            )
            # Wait until the SSE feed has mirrored the completion event.
            try:
                await asyncio.wait_for(mirrored_done.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        finally:
            watch_task.cancel()
        await self._log_worker_result(run_id, task_id, agent_id, agent_name, result)
        return str(result.get("output", ""))

    async def _watch_worker_progress(self, run_id: str, forward_progress) -> None:
        assert self.mesh is not None
        try:
            await self.mesh.watch_run(run_id, forward_progress)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Progress mirroring is best-effort and must never fail a delegation.
            return

    async def _log_worker_result(
        self,
        run_id: str,
        task_id: str,
        agent_id: str,
        agent_name: str,
        result: dict[str, Any],
    ) -> None:
        started: dict[str, Any] = {}
        completed: dict[str, Any] = {}
        for item in result.get("events", []):
            if item.get("event_type") == "AGENT_STARTED":
                started = dict(item.get("payload", {}))
            elif item.get("event_type") == "AGENT_COMPLETED":
                completed = dict(item.get("payload", {}))
        await self.event(run_id, "WORKER_RESULT", agent_name, {
            "task_id": task_id,
            "agent_id": agent_id,
            "model": started.get("model"),
            "used_tools": completed.get("used_tools", []),
            "status": result.get("state") or result.get("status"),
            # The exact message this worker sent back to MARCELO.
            "message_from_worker": str(result.get("output", ""))[:3000],
        })

    async def discover(self, run_id: str, task: PlanTask, excluded: set[str]) -> list[AgentListing]:
        required = set(task.required_tools)
        if self.mesh is not None:
            candidates = await self.mesh.search(
                query=task.capability_query,
                limit=settings.marketplace_candidate_limit,
                exclude=excluded,
                required_tools=sorted(required),
            )
        else:
            discovered = await self.marketplace.search(
                task.capability_query,
                limit=max(settings.marketplace_candidate_limit * 4, 20),
                exclude=excluded,
            )
            candidates = [c for c in discovered if required.issubset(set(tools_for_agent(c)))][:settings.marketplace_candidate_limit]
        if not candidates:
            raise RuntimeError(
                f"No marketplace agent found for task {task.id} with required tools {sorted(required)}: {task.capability_query}"
            )
        await self.event(run_id, "DISCOVER", "MARCELO", {
            "task_id": task.id,
            "query": task.capability_query,
            "candidates": [{**c.model_dump(exclude={"source_path"}), "tools": tools_for_agent(c)} for c in candidates],
        })
        return candidates

    async def evaluate(self, run_id: str, task: PlanTask, candidates: list[AgentListing]) -> AgentSelection:
        public_candidates = [{**c.model_dump(exclude={"source_path", "sha256"}), "tools": tools_for_agent(c)} for c in candidates]
        prompt = f"""Select exactly one marketplace agent for this task.

TASK:
{task.model_dump_json(indent=2)}

CANDIDATES:
{json.dumps(public_candidates, ensure_ascii=False, indent=2)}

Evaluate capability fit, specialization, expected deliverable quality, required tool coverage, and unnecessary capability overhead.
Return JSON only:
{{"selected_agent_id":"exact candidate id","rationale":"concise reason","confidence":0.0}}
"""
        data = await self.llm.json(system=MARCELO_SYSTEM, user=prompt, model=settings.marcelo_model)
        selection = AgentSelection.model_validate(data)
        valid = {candidate.id for candidate in candidates}
        if selection.selected_agent_id not in valid:
            repair = await self.llm.json(
                system=MARCELO_SYSTEM,
                user=f"Your previous selected_agent_id was invalid. Choose exactly one of {sorted(valid)}. Return the same JSON shape only.",
                model=settings.marcelo_model,
            )
            selection = AgentSelection.model_validate(repair)
            if selection.selected_agent_id not in valid:
                raise RuntimeError("MARCELO failed to select a valid discovered marketplace agent")

        await self.event(run_id, "EVALUATE", "MARCELO", {
            "task_id": task.id,
            **selection.model_dump(),
        })
        return selection

    async def hire(
        self,
        run_id: str,
        task: PlanTask,
        selected: AgentListing,
        selection: AgentSelection,
    ) -> AgentContract:
        contract = AgentContract(
            run_id=run_id,
            task_id=task.id,
            seller_agent=selected.id,
            objective=task.objective,
            acceptance_criteria=task.acceptance_criteria,
        )
        await self.db.insert_contract(contract.model_dump())
        await self.event(run_id, "HIRE", "MARCELO", {
            "task_id": task.id,
            "contract_id": contract.contract_id,
            "agent_id": selected.id,
            "agent_name": selected.name,
            "rationale": selection.rationale,
            "confidence": selection.confidence,
        })
        return contract

    async def verify(
        self,
        run_id: str,
        goal: GoalBrief,
        task: PlanTask,
        worker: AgentListing,
        output: str,
    ) -> VerificationResult:
        verifier_query = "independent quality assurance reviewer critic verifier reality checker audit"
        candidates = await self.marketplace.search(verifier_query, limit=settings.marketplace_candidate_limit, exclude={worker.id})
        if not candidates:
            raise RuntimeError("No independent verifier agent found")
        await self.event(run_id, "VERIFY_DISCOVER", "MARCELO", {
            "task_id": task.id,
            "candidates": [c.model_dump(exclude={"source_path"}) for c in candidates],
        })

        selection = await self.evaluate_verifier(task, candidates)
        verifier = next(c for c in candidates if c.id == selection.selected_agent_id)
        verifier_contract = AgentContract(
            run_id=run_id,
            task_id=f"{task.id}:verify",
            seller_agent=verifier.id,
            objective=f"Independently verify task {task.id}",
            acceptance_criteria=task.acceptance_criteria,
        )
        await self.db.insert_contract(verifier_contract.model_dump())
        await self.event(run_id, "VERIFY_HIRE", "MARCELO", {
            "task_id": task.id,
            "contract_id": verifier_contract.contract_id,
            "verifier_agent_id": verifier.id,
            "verifier_agent_name": verifier.name,
            "rationale": selection.rationale,
        })

        prompt = PromptMaster.verification(
            goal=goal,
            task=task,
            worker_name=worker.name,
            worker_output=output,
            run_id=run_id,
        )
        verifier_required = []
        if any(tool.startswith("web.") for tool in task.required_tools):
            verifier_required.append("web.search")
        if "shell.exec" in task.required_tools:
            verifier_required.extend(["filesystem.list", "shell.exec"])
        elif "filesystem.write" in task.required_tools:
            verifier_required.append("filesystem.list")
        raw = await self._run_agent(
            run_id=run_id,
            task_id=task.id,
            agent_id=verifier.id,
            agent_name=verifier.name,
            user_prompt=prompt,
            temperature=0.0,
            model=settings.verifier_model,
            required_tools=verifier_required,
        )
        from .json_utils import extract_json
        data = extract_json(raw)
        # Verifiers sometimes score on a 0-100 scale; the contract is 0.0-1.0.
        score = data.get("score") if isinstance(data, dict) else None
        if isinstance(score, (int, float)) and score > 1:
            data["score"] = score / 100 if score <= 100 else 1.0
        verification = VerificationResult.model_validate(data)
        await self.db.add_artifact(run_id, task.id, verifier.id, "verification", raw)
        await self.db.set_contract_status(
            verifier_contract.contract_id,
            "accepted" if verification.verdict == "PASS" else "rejected",
        )
        await self.event(run_id, f"VERIFY_{verification.verdict}", verifier.name, {
            "task_id": task.id,
            **verification.model_dump(),
        })
        return verification

    async def evaluate_verifier(self, task: PlanTask, candidates: list[AgentListing]) -> AgentSelection:
        public_candidates = [c.model_dump(exclude={"source_path", "sha256"}) for c in candidates]
        data = await self.llm.json(
            system=MARCELO_SYSTEM,
            user=f"""Select the best independent verifier for this task. Do not select a worker based on domain execution ability alone; prioritize critical review, QA, audit, evidence checking, and acceptance-criteria evaluation.
TASK: {task.model_dump_json()}
CANDIDATES: {json.dumps(public_candidates, ensure_ascii=False)}
Return JSON only: {{"selected_agent_id":"exact candidate id","rationale":"...","confidence":0.0}}""",
            model=settings.marcelo_model,
        )
        selection = AgentSelection.model_validate(data)
        valid = {c.id for c in candidates}
        if selection.selected_agent_id not in valid:
            raise RuntimeError("MARCELO selected an invalid verifier")
        return selection

    async def synthesize(self, goal: GoalBrief, results: dict[str, TaskResult]) -> str:
        compact = {
            task_id: {
                "title": result.title,
                "worker": result.worker_agent_name,
                "output": result.output,
                "verification": result.verification.model_dump(),
            }
            for task_id, result in results.items()
        }
        return await self.llm.complete(
            system=MARCELO_SYSTEM,
            user=f"""Synthesize the accepted, independently verified marketplace work into one final answer for JARVIS.
Do not invent missing work. Preserve material disagreements or uncertainty.

GOAL:
{goal.model_dump_json(indent=2)}

ACCEPTED WORK:
{json.dumps(compact, ensure_ascii=False, indent=2)}
""",
            temperature=0.2,
            max_tokens=4096,
            model=settings.marcelo_model,
        )

    async def event(self, run_id: str, event_type: str, actor: str, payload: dict[str, Any]) -> None:
        await self.db.add_event(run_id, event_type, actor, payload)

    async def callback(self, callback_url: str, message: A2AMessage) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(callback_url, json=message.model_dump(mode="json"))
        except Exception:
            # Callback transport failure must not erase the persisted run/event state.
            await self.event(message.run_id, "CALLBACK_FAILED", "MARCELO", {"callback_url": callback_url})
