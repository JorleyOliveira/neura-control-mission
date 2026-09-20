from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from neura_marketplace.config import settings
from neura_marketplace.db import Database
from neura_marketplace.executor import AgentExecutor
from neura_marketplace.marketplace import AgentMarketplace
from neura_marketplace.neuralake import NeuraLakeClient


REQUIRED_TOOLS = [
    "skill.invoke",
    "web.search",
    "web.fetch",
    "filesystem.write",
]

SELECTED_SKILLS = [
    "prompt-master",
]


def build_user_prompt(selected_skills: list[str]) -> str:
    skills = "\n".join(f"- {skill_id}" for skill_id in selected_skills)

    return f"""\
            Research the NeuraLake inference platform used by this project and write the final research artifact to research.md.

            Entity disambiguation:
            - Target: NeuraLake, the inference provider for the agent economy.
            - The target provides an OpenAI-compatible inference API with capability-based models such as text, code, reasoning, multimodal, and auto.
            - Do NOT research unrelated companies that happen to use the Neuralake/NeuraLake name.
            - Verify the selected website matches this description before relying on it.

            This is a runtime smoke test. The following skills have already been selected for this task:

            {skills}

            Skill requirements:
            - Invoke the selected skill before doing the research.
            - When calling skill.invoke, use one of the exact skill IDs listed above.
            - For this task, use prompt-master to prepare a concise research prompt/plan for researching the target NeuraLake with the live web.
            - Do not invent or substitute another skill ID.

            Research requirements:
            - Search the live web for the target NeuraLake.
            - Inspect search results and identify the result matching the entity description above.
            - Fetch at least one relevant public source for that exact entity.
            - Base the research on tool results rather than prior knowledge alone.
            - Write the completed research artifact to research.md.
            - Do not finish until all required tools have completed successfully.
            - Once all requirements are satisfied, return the final result immediately.
            """

async def main(agent_id: str, use_gateway: bool = False) -> None:
    db = Database(settings.database_path)
    await db.init()

    marketplace = AgentMarketplace(
        db,
        settings.effective_agent_dataset_dir,
    )
    await marketplace.index()

    executor = AgentExecutor(
        marketplace,
        NeuraLakeClient(),
        db,
    )

    run_id = f"runtime-smoke-{uuid4()}"

    await db.create_run(
        run_id,
        "runtime-smoke",
        "Prove real-world agent tool execution",
    )

    if use_gateway:
        from neura_marketplace.a2a_client import A2AMeshClient

        mesh = A2AMeshClient()
        result_payload = await mesh.execute_task(
            agent_id=agent_id,
            prompt=build_user_prompt(SELECTED_SKILLS),
            required_tools=REQUIRED_TOOLS,
            model=settings.worker_text_model,
            run_id=run_id,
            task_id="research-smoke",
        )
        result = str(result_payload.get("output", ""))
    else:
        result = await executor.run(
            run_id=run_id,
            task_id="research-smoke",
            agent_id=agent_id,
            required_tools=REQUIRED_TOOLS,
            user_prompt=build_user_prompt(SELECTED_SKILLS),
            model=settings.worker_text_model,
        )

    print(f"RUN_ID={run_id}")
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent",
        default="research:research-synthesist",
    )
    parser.add_argument(
        "--gateway",
        action="store_true",
        help="delegate execution to the A2A worker gateway instead of the in-process executor",
    )
    args = parser.parse_args()

    asyncio.run(main(args.agent, use_gateway=args.gateway))
