from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version TEXT,
    source_path TEXT NOT NULL,
    skill_md_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_files (
    skill_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (skill_id, relative_path),
    FOREIGN KEY(skill_id)
        REFERENCES skills(id)
        ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS skill_search USING fts5(
    skill_id UNINDEXED,
    name,
    description,
    source
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    final_result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS tasks (
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, task_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    buyer_agent TEXT NOT NULL,
    seller_agent TEXT NOT NULL,
    objective TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL,
    output TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id, task_id);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    division TEXT NOT NULL,
    description TEXT NOT NULL,
    vibe TEXT,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS agent_search USING fts5(
    agent_id UNINDEXED,
    name,
    division,
    description,
    vibe
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def init(self) -> None:
        def op() -> None:
            with self._connect() as db:
                db.executescript(SCHEMA)
                db.commit()
        await asyncio.to_thread(op)

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        def op() -> None:
            with self._connect() as db:
                db.execute(sql, params)
                db.commit()
        await asyncio.to_thread(op)

    async def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        def op() -> None:
            with self._connect() as db:
                db.executemany(sql, params)
                db.commit()
        await asyncio.to_thread(op)

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        def op() -> sqlite3.Row | None:
            with self._connect() as db:
                return db.execute(sql, params).fetchone()
        return await asyncio.to_thread(op)

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        def op() -> list[sqlite3.Row]:
            with self._connect() as db:
                return db.execute(sql, params).fetchall()
        return await asyncio.to_thread(op)

    async def transaction(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        def op() -> None:
            with self._connect() as db:
                for sql, params in statements:
                    db.execute(sql, params)
                db.commit()
        await asyncio.to_thread(op)

    async def create_run(self, run_id: str, session_id: str, objective: str) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO runs(run_id, session_id, objective, status) VALUES (?, ?, ?, 'accepted')",
            (run_id, session_id, objective),
        )

    async def set_run_status(self, run_id: str, status: str, final_result: str | None = None) -> None:
        await self.execute(
            "UPDATE runs SET status=?, final_result=COALESCE(?, final_result), updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (status, final_result, run_id),
        )

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = await self.fetchone("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return dict(row) if row else None

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        await self.execute(
            "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )

    async def get_messages(self, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in reversed(rows)]

    async def add_event(self, run_id: str, event_type: str, actor: str, payload: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO events(run_id, event_type, actor, payload) VALUES (?, ?, ?, ?)",
            (run_id, event_type, actor, json.dumps(payload, ensure_ascii=False)),
        )

    async def events_since(self, run_id: str, seq: int) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT seq, run_id, event_type, actor, payload, created_at FROM events WHERE run_id=? AND seq>? ORDER BY seq ASC",
            (run_id, seq),
        )
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            out.append(item)
        return out

    async def upsert_task(self, run_id: str, task_id: str, title: str, objective: str, status: str, payload: dict[str, Any]) -> None:
        await self.execute(
            """
            INSERT INTO tasks(run_id, task_id, title, objective, status, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, task_id) DO UPDATE SET status=excluded.status, payload=excluded.payload
            """,
            (run_id, task_id, title, objective, status, json.dumps(payload, ensure_ascii=False)),
        )

    async def insert_contract(self, contract: dict[str, Any]) -> None:
        await self.execute(
            """
            INSERT INTO contracts(contract_id, run_id, task_id, buyer_agent, seller_agent, objective, acceptance_criteria, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract["contract_id"], contract["run_id"], contract["task_id"], contract["buyer_agent"],
                contract["seller_agent"], contract["objective"],
                json.dumps(contract["acceptance_criteria"], ensure_ascii=False), contract["status"],
            ),
        )

    async def set_contract_status(self, contract_id: str, status: str) -> None:
        await self.execute("UPDATE contracts SET status=? WHERE contract_id=?", (status, contract_id))

    async def add_artifact(self, run_id: str, task_id: str, agent_id: str, kind: str, content: str) -> None:
        await self.execute(
            "INSERT INTO artifacts(run_id, task_id, agent_id, kind, content) VALUES (?, ?, ?, ?, ?)",
            (run_id, task_id, agent_id, kind, content),
        )
    async def start_tool_call(self, call_id: str, run_id: str, task_id: str, agent_id: str, tool: str, arguments: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO tool_calls(id, run_id, task_id, agent_id, tool, arguments, status) VALUES (?, ?, ?, ?, ?, ?, 'running')",
            (call_id, run_id, task_id, agent_id, tool, json.dumps(arguments, ensure_ascii=False)),
        )

    async def finish_tool_call(self, call_id: str, *, status: str, output: dict[str, Any] | None = None) -> None:
        await self.execute(
            "UPDATE tool_calls SET status=?, output=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, json.dumps(output, ensure_ascii=False) if output is not None else None, call_id),
        )

