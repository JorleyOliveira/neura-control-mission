from __future__ import annotations

import json
from uuid import uuid4

from .capabilities import tools_for_agent
from .config import settings
from .db import Database
from .marketplace import AgentMarketplace
from .neuralake import NeuraLakeClient
from .runner_client import ToolRunnerClient
from .tool_protocol import parse_action, render_tool_contract


class AgentExecutor:
    def __init__(self, marketplace: AgentMarketplace, llm: NeuraLakeClient, db: Database, runner: ToolRunnerClient | None = None):
        self.marketplace = marketplace
        self.llm = llm
        self.db = db
        self.runner = runner or ToolRunnerClient()

    async def run(
        self,
        *,
        run_id: str,
        task_id: str,
        agent_id: str,
        user_prompt: str,
        temperature: float = 0.2,
        required_tools: list[str] | None = None,
        model: str = "text",
    ) -> str:
        listing = await self.marketplace.get(agent_id)
        system_prompt = await self.marketplace.raw_system_prompt(agent_id)
        allowed_tools = tools_for_agent(listing)
        required_tools = required_tools or []
        missing = sorted(set(required_tools) - set(allowed_tools))
        if missing:
            raise RuntimeError(f'Agent {agent_id} lacks required tools: {missing}')

        messages: list[dict[str, str]] = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt + '\n\n' + render_tool_contract(allowed_tools, required_tools)},
        ]
        used_tools: set[str] = set()
        pending_skill_read: dict | None = None

        await self.db.add_event(
            run_id,
            'AGENT_STARTED',
            listing.name,
            {
                'task_id': task_id,
                'agent_id': agent_id,
                'model': model,
                'required_tools': required_tools,
            },
        )

        for step in range(1, settings.agent_max_steps + 1):
            raw = await self.llm.chat(messages=messages, temperature=temperature, max_tokens=4096, model=model)
            try:
                action = parse_action(raw)
            except Exception as exc:
                await self.db.add_event(
                    run_id,
                    'AGENT_ACTION_INVALID',
                    listing.name,
                    {
                        'task_id': task_id,
                        'agent_id': agent_id,
                        'step': step,
                        'error': str(exc),
                        'raw_preview': raw[:2000],
                    },
                )

                messages.extend([
                    {'role': 'assistant', 'content': raw},
                    {
                        'role': 'user',
                        'content': (
                            f'Invalid runtime action: {exc}. '
                            'Return exactly one valid JSON action object.'
                        ),
                    },
                ])
                continue

            if action['type'] == 'final':
                if pending_skill_read is not None:
                    await self.db.add_event(
                        run_id,
                        'AGENT_FINAL_BLOCKED',
                        listing.name,
                        {
                            'task_id': task_id,
                            'agent_id': agent_id,
                            'step': step,
                            'pending_skill_read': pending_skill_read,
                            'used_tools': sorted(used_tools),
                        },
                    )

                    messages.extend([
                        {'role': 'assistant', 'content': raw},
                        {
                            'role': 'user',
                            'content': (
                                'The selected skill was truncated and is not fully read yet. '
                                'Before finishing, call skill.read with exactly: '
                                f"skill_id={pending_skill_read['skill_id']!r}, "
                                f"path={pending_skill_read['path']!r}, "
                                f"offset={pending_skill_read['offset']}. "
                                'Do not restart from offset 0. '
                                'Return the skill.read tool_call JSON now.'
                            ),
                        },
                    ])
                    continue

                missing_required = sorted(
                    set(required_tools) - used_tools
                )

                if missing_required:
                    await self.db.add_event(
                        run_id,
                        'AGENT_FINAL_BLOCKED',
                        listing.name,
                        {
                            'task_id': task_id,
                            'agent_id': agent_id,
                            'step': step,
                            'missing_required': missing_required,
                            'used_tools': sorted(used_tools),
                        },
                    )

                    messages.extend([
                        {'role': 'assistant', 'content': raw},
                        {
                            'role': 'user',
                            'content': (
                                'You must use these required tools before '
                                f'finishing: {missing_required}. '
                                'Return a tool_call JSON object now.'
                            ),
                        },
                    ])
                    continue

                await self.db.add_event(
                    run_id,
                    'AGENT_COMPLETED',
                    listing.name,
                    {
                        'task_id': task_id,
                        'agent_id': agent_id,
                        'model': model,
                        'used_tools': sorted(used_tools),
                    },
                )
                return str(action['content'])

            tool = str(action['tool'])
            arguments = dict(action['arguments'])
            if tool not in allowed_tools:
                await self.db.add_event(
                    run_id,
                    'TOOL_REJECTED',
                    listing.name,
                    {
                        'task_id': task_id,
                        'agent_id': agent_id,
                        'step': step,
                        'tool': tool,
                        'allowed_tools': sorted(allowed_tools),
                        'arguments': arguments,
                    },
                )

                messages.extend([
                    {'role': 'assistant', 'content': raw},
                    {
                        'role': 'user',
                        'content': (
                            f'TOOL_ERROR: {tool} is not allowed. '
                            f'Allowed tools: {sorted(allowed_tools)}. '
                            'Return the next JSON action.'
                        ),
                    },
                ])
                continue
            call_id = str(uuid4())
            await self.db.start_tool_call(call_id, run_id, task_id, agent_id, tool, arguments)
            await self.db.add_event(run_id, 'TOOL_REQUESTED', listing.name, {
                'task_id': task_id, 'agent_id': agent_id, 'tool_call_id': call_id,
                'tool': tool, 'arguments': arguments, 'step': step,
            })
            skill_instruction: str | None = None
            try:
                result = await self.runner.execute(
                    run_id=run_id, task_id=task_id, agent_id=agent_id, tool=tool, arguments=arguments,
                )
                await self.db.finish_tool_call(call_id, status='completed', output=result)
                await self.db.add_event(run_id, 'TOOL_COMPLETED', listing.name, {
                    'task_id': task_id, 'agent_id': agent_id, 'tool_call_id': call_id,
                    'tool': tool, 'result_preview': json.dumps(result.get('result', {}), ensure_ascii=False)[:1200],
                })
                used_tools.add(tool)
                result_payload = result.get('result')
                tool_message = {'ok': True, 'tool': tool, 'result': result_payload}

                if tool in {'skill.invoke', 'skill.read'} and isinstance(result_payload, dict):
                    skill_id = result_payload.get('skill_id')
                    if skill_id and result_payload.get('truncated') and result_payload.get('next_offset') is not None:
                        pending_skill_read = {
                            'skill_id': skill_id,
                            'path': result_payload.get('path') or 'SKILL.md',
                            'offset': result_payload.get('next_offset'),
                        }
                        skill_instruction = (
                            'The selected skill was truncated. '
                            'Before continuing the task, call skill.read with exactly: '
                            f'skill_id={skill_id!r}, '
                            f"path={pending_skill_read['path']!r}, "
                            f"offset={pending_skill_read['offset']}. "
                            'Do not restart from offset 0.'
                        )
                    elif (
                        tool == 'skill.read'
                        and pending_skill_read is not None
                        and skill_id == pending_skill_read['skill_id']
                        and not result_payload.get('truncated')
                    ):
                        pending_skill_read = None
            except Exception as exc:
                tool_message = {'ok': False, 'tool': tool, 'error': str(exc)}
                await self.db.finish_tool_call(call_id, status='failed', output=tool_message)
                await self.db.add_event(run_id, 'TOOL_FAILED', listing.name, {
                    'task_id': task_id, 'agent_id': agent_id, 'tool_call_id': call_id,
                    'tool': tool, 'error': str(exc),
                })

            next_content = 'TOOL_RESULT\n' + json.dumps(tool_message, ensure_ascii=False) + '\n'
            if skill_instruction:
                next_content += skill_instruction + '\n'
            next_content += 'Return the next JSON action only.'
            messages.extend([
                {'role': 'assistant', 'content': raw},
                {'role': 'user', 'content': next_content},
            ])

        # raise RuntimeError(f'Agent {agent_id} exceeded max runtime steps ({settings.agent_max_steps})')
        missing_required = sorted(
            set(required_tools) - used_tools
        )

        raise RuntimeError(
            f'Agent {agent_id} exceeded max runtime steps '
            f'({settings.agent_max_steps}); '
            f'used_tools={sorted(used_tools)}; '
            f'missing_required={missing_required}'
        )
