from pathlib import Path

import json

import pytest

from neura_marketplace.db import Database
from neura_marketplace.executor import AgentExecutor
from neura_marketplace.marketplace import AgentMarketplace


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.responses = [
            '{"type":"tool_call","tool":"filesystem.write","arguments":{"path":"x.txt","content":"ok"}}',
            '{"type":"final","content":"worker result"}',
        ]

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeRunner:
    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return {'ok': True, 'tool': kwargs['tool'], 'result': {'path': 'x.txt', 'bytes': 2}}


class ScriptedLLM:
    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class ScriptedRunner:
    def __init__(self, results):
        self.calls = []
        self.results = list(results)

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return {'ok': True, 'tool': kwargs['tool'], 'result': self.results.pop(0)}


@pytest.mark.asyncio
async def test_executor_preserves_system_and_runs_tool(tmp_path: Path):
    agents = tmp_path / 'agents'
    agents.mkdir()
    raw = '---\nname: Exact Agent\ndescription: code engineering\n---\nEXACT SYSTEM PROMPT\n'
    (agents / 'exact.md').write_text(raw, encoding='utf-8')
    db = Database(tmp_path / 'test.db')
    marketplace = AgentMarketplace(db, agents)
    await marketplace.index()
    llm = FakeLLM()
    runner = FakeRunner()
    executor = AgentExecutor(marketplace, llm, db, runner=runner)  # type: ignore[arg-type]
    await db.create_run('run', 'session', 'test')

    result = await executor.run(
        run_id='run', task_id='task', agent_id='exact', user_prompt='TASK',
        required_tools=['filesystem.write'],
    )

    assert result == 'worker result'
    assert llm.calls[0]['messages'][0]['content'] == raw
    assert runner.calls[0]['tool'] == 'filesystem.write'
    row = await db.fetchone('SELECT status, tool FROM tool_calls WHERE run_id=?', ('run',))
    assert row['status'] == 'completed'
    assert row['tool'] == 'filesystem.write'


@pytest.mark.asyncio
async def test_truncated_skill_invoke_requires_continuation_read(tmp_path: Path):
    agents = tmp_path / 'agents'
    agents.mkdir()
    raw = '---\nname: Exact Agent\ndescription: research\n---\nEXACT SYSTEM PROMPT\n'
    (agents / 'exact.md').write_text(raw, encoding='utf-8')
    db = Database(tmp_path / 'test.db')
    marketplace = AgentMarketplace(db, agents)
    await marketplace.index()
    llm = ScriptedLLM([
        '{"type":"tool_call","tool":"skill.invoke","arguments":{"skill_id":"prompt-master","input":"prepare"}}',
        '{"type":"final","content":"premature finish"}',
        '{"type":"tool_call","tool":"skill.read","arguments":{"skill_id":"prompt-master","path":"SKILL.md","offset":20000,"max_chars":20000}}',
        '{"type":"final","content":"done after full skill"}',
    ])
    runner = ScriptedRunner([
        {'skill_id': 'prompt-master', 'path': 'SKILL.md', 'truncated': True, 'next_offset': 20000},
        {'skill_id': 'prompt-master', 'path': 'SKILL.md', 'truncated': False, 'next_offset': None},
    ])
    executor = AgentExecutor(marketplace, llm, db, runner=runner)  # type: ignore[arg-type]
    await db.create_run('run2', 'session', 'test')

    result = await executor.run(
        run_id='run2', task_id='task', agent_id='exact', user_prompt='TASK',
    )

    assert result == 'done after full skill'
    assert runner.calls[1]['tool'] == 'skill.read'
    assert runner.calls[1]['arguments']['offset'] == 20000

    rows = await db.fetchall("SELECT event_type, payload FROM events WHERE run_id='run2' ORDER BY seq")
    by_type = {}
    for row in rows:
        by_type.setdefault(row['event_type'], []).append(json.loads(row['payload']))

    assert by_type['AGENT_STARTED'][0]['model'] == 'text'
    assert len(by_type['AGENT_FINAL_BLOCKED']) == 1
    assert by_type['AGENT_FINAL_BLOCKED'][0]['pending_skill_read']['offset'] == 20000
    assert by_type['AGENT_COMPLETED'][0]['used_tools'] == ['skill.invoke', 'skill.read']
