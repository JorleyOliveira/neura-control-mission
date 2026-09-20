from __future__ import annotations

from .models import GoalBrief, PlanTask


class PromptMaster:
    @staticmethod
    def delegation(*, goal: GoalBrief, task: PlanTask, dependency_outputs: dict[str, str], retry_feedback: list[str] | None = None, run_id: str = '') -> str:
        deps = '\n\n'.join(f'### Dependency: {task_id}\n{output}' for task_id, output in dependency_outputs.items()) or 'None'
        criteria = '\n'.join(f'- {item}' for item in task.acceptance_criteria) or '- Complete the stated objective.'
        constraints = '\n'.join(f'- {item}' for item in goal.constraints) or '- No additional constraints supplied.'
        feedback = '\n'.join(f'- {item}' for item in (retry_feedback or [])) or 'None'
        required = '\n'.join(f'- {item}' for item in task.required_tools) or '- none'

        negotiation_note = ''
        if 'a2a.call' in task.required_tools:
            negotiation_note = f'''
## A2A Negotiation Contract
- The runtime pins negotiation_id to '{run_id}:{task.id}' on every a2a.call message/send; all rounds continue that one negotiation.
- Never web.fetch or web.search the seller; internal A2A agents are reachable ONLY via a2a.call. Copy this call pattern exactly (change only the text):
  {{"type":"tool_call","tool":"a2a.call","arguments":{{"url":"http://seller:8020/rpc","method":"message/send","params":{{"message":{{"role":"user","parts":[{{"kind":"text","text":"your negotiation message"}}]}}}}}}}}
- Your report must contain ONLY offers the seller agent actually returned; the verifier will cross-check the seller's negotiation/history record and any invented deal fails verification.
'''

        return f'''## Objective
{task.objective}

## Parent Goal
{goal.objective}

## Target User
{goal.target_user or 'Not specified'}

## Inputs From Completed Dependencies
{deps}

## Constraints
{constraints}

## Acceptance Criteria
{criteria}

## Required Real-World Capabilities
{required}

## Retry Feedback
{feedback}
{negotiation_note}
## Action Boundaries
- Work only on this delegated task.
- Do not redefine the parent objective.
- Do not choose or delegate to another marketplace agent.
- Do not claim external evidence you did not actually obtain through runtime tools.
- Current claims must be grounded with web tools when available.
- Implementation/test claims must be grounded with filesystem/shell tools when applicable.
- Produce a concrete deliverable that downstream agents can consume.
'''

    @staticmethod
    def verification(*, goal: GoalBrief, task: PlanTask, worker_name: str, worker_output: str, run_id: str = '') -> str:
        criteria = '\n'.join(f'- {item}' for item in task.acceptance_criteria) or '- Complete the stated objective.'
        negotiation_check = ''
        if 'a2a.call' in task.required_tools:
            negotiation_check = f'''
GROUND TRUTH CHECK (mandatory before your verdict):
- The worker claims a negotiated deal. Query the seller's authoritative record yourself with a2a.call:
  url http://seller:8020/rpc, method negotiation/history, params {{"negotiation_id": "{run_id}:{task.id}"}}
- FAIL the work if the seller's record does not show the rounds and the accepted offer the worker claims, or if the negotiation never happened.
'''
        return f'''You are independently verifying another marketplace agent's submitted work.

PARENT GOAL:
{goal.objective}

TASK:
{task.objective}

WORKER:
{worker_name}

ACCEPTANCE CRITERIA:
{criteria}

WORKER OUTPUT:
---
{worker_output}
---

Your final content MUST be exactly one JSON object with this shape:
{{
  "verdict": "PASS" | "FAIL",
  "score": 0.0,
  "failed_criteria": ["..."],
  "feedback": ["specific correction..."]
}}

You may use runtime tools before the final action to independently validate external claims or run checks.
{negotiation_check}
PASS only when every critical acceptance criterion is materially satisfied.
'''
