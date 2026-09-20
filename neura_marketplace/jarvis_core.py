from __future__ import annotations

import json

from .config import settings
from .models import GoalBrief, JarvisDecision
from .neuralake import NeuraLakeClient


JARVIS_SYSTEM = """You are JARVIS, the human-facing consultant agent for an autonomous A2A marketplace.
Your job is to clarify the human's actual business objective before delegation to MARCELO.
Ask only questions that materially change execution. Do not choose marketplace workers.
When enough context exists, construct a GoalBrief.
Return JSON only.
"""


class Jarvis:
    def __init__(self, llm: NeuraLakeClient):
        self.llm = llm

    async def analyze(self, message: str, history: list[dict[str, str]]) -> JarvisDecision:
        prompt = f"""Conversation history:
{json.dumps(history, ensure_ascii=False)}

Latest human message:
{message}

Return exactly one of:

1) If a material clarification is still required:
{{
  "ready": false,
  "question": "one concise question",
  "brief": null
}}

2) If ready to delegate:
{{
  "ready": true,
  "question": null,
  "brief": {{
    "objective": "...",
    "product": "... or null",
    "target_user": "... or null",
    "desired_outputs": ["..."],
    "constraints": ["..."],
    "context": {{}},
    "success_criteria": ["..."]
  }}
}}

Rules:
- Do not ask for details that MARCELO or hired agents can autonomously decide.
- A broad request such as "launch a product" needs clarification about what product/problem and intended user.
- If the human already supplied the product/problem, target user, or concrete desired outcome, prefer delegation over additional questioning.
"""
        data = await self.llm.json(system=JARVIS_SYSTEM, user=prompt, model=settings.jarvis_model)
        return JarvisDecision.model_validate(data)
