from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ORCHESTRATION_EVENTS = {
    "GOAL_DELEGATED": ("JARVIS  -> MARCELO", "A2A_JOB", "goal submitted (HTTP POST /a2a/jobs)"),
    "GOAL_RECEIVED": ("MARCELO", "internal", "orchestrator picked up the goal"),
    "PLAN_CREATED": ("MARCELO", "internal", None),
    "DISCOVER": ("MARCELO -> GATEWAY", "A2A_SEARCH", None),
    "EVALUATE": ("MARCELO", "LLM", None),
    "HIRE": ("MARCELO", "contract", None),
    "DELEGATE": ("MARCELO -> WORKER", "JSON-RPC", None),
    "WORKER_PROGRESS": ("WORKER -> MARCELO", "progress", None),
    "WORKER_RESULT": ("WORKER -> MARCELO", "JSON-RPC", None),
    "WORK_SUBMITTED": ("MARCELO", "internal", None),
    "VERIFY_DISCOVER": ("MARCELO -> GATEWAY", "A2A_SEARCH", "searching for an independent verifier"),
    "VERIFY_HIRE": ("MARCELO", "contract", None),
    "VERIFY_PASS": ("VERIFIER -> MARCELO", "verdict", None),
    "VERIFY_FAIL": ("VERIFIER -> MARCELO", "verdict", None),
    "REJECT_AND_REHIRE": ("MARCELO", "internal", None),
    "FINAL_RESULT": ("MARCELO -> JARVIS", "A2A_CALLBACK", "final answer (HTTP POST /a2a/messages)"),
    "RUN_FAILED": ("MARCELO", "internal", None),
    "CALLBACK_FAILED": ("MARCELO -> JARVIS", "A2A_CALLBACK", None),
}

GATEWAY_EVENTS = {
    "AGENT_STARTED": ("[gateway] WORKER", "execute", None),
    "AGENT_COMPLETED": ("[gateway] WORKER", "execute", None),
    "AGENT_ACTION_INVALID": ("[gateway] WORKER", "recover", None),
    "AGENT_FINAL_BLOCKED": ("[gateway] WORKER", "enforce", None),
    "TOOL_REQUESTED": ("[gateway] -> RUNNER", "TOOL_RPC", None),
    "TOOL_COMPLETED": ("[gateway] <- RUNNER", "TOOL_RPC", None),
    "TOOL_FAILED": ("[gateway] <- RUNNER", "TOOL_RPC", None),
}


def load_events(db_path: Path, run_id: str, rank: int, after_seq: int = 0) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT seq, event_type, actor, payload, created_at FROM events WHERE run_id=? AND seq>? ORDER BY seq",
        (run_id, after_seq),
    ).fetchall()
    conn.close()
    return [
        {
            "seq": row["seq"],
            "event_type": row["event_type"],
            "actor": row["actor"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
            "rank": rank,
        }
        for row in rows
    ]


def detail_for(event: dict) -> str:
    kind, payload, actor = event["event_type"], event["payload"], event["actor"]
    if kind == "PLAN_CREATED":
        return f"planned {len(payload.get('tasks', []))} tasks (DAG)"
    if kind == "DISCOVER":
        return f"query={payload.get('query', '')!r:.60} -> {len(payload.get('candidates', []))} candidates"
    if kind == "EVALUATE":
        return f"selected {payload.get('selected_agent_id')} confidence={payload.get('confidence')}"
    if kind == "HIRE":
        return f"contract with {payload.get('agent_name')} [{payload.get('agent_id')}]"
    if kind == "DELEGATE":
        return (
            f"execute_task -> {payload.get('agent_name')} "
            f"(task={payload.get('task_id')}, attempt={payload.get('attempt')})"
        )
    if kind == "WORKER_RESULT":
        return (
            f"result from {actor}: model={payload.get('model')} "
            f"used_tools={payload.get('used_tools')} status={payload.get('status')}"
        )
    if kind == "WORK_SUBMITTED":
        return f"task {payload.get('task_id')} output accepted for verification"
    if kind == "VERIFY_HIRE":
        return f"verifier: {payload.get('verifier_agent_name')}"
    if kind == "VERIFY_PASS":
        return f"{actor}: PASS score={payload.get('score')}"
    if kind == "VERIFY_FAIL":
        return f"{actor}: FAIL criteria={payload.get('failed_criteria')}"
    if kind == "REJECT_AND_REHIRE":
        return f"rejected {payload.get('rejected_agent_id')}; rehiring (attempt {payload.get('next_attempt')})"
    if kind == "RUN_FAILED":
        return f"error: {str(payload.get('error'))[:120]}"
    if kind == "AGENT_STARTED":
        return (
            f"{actor} started | model={payload.get('model')} "
            f"required_tools={payload.get('required_tools')}"
        )
    if kind == "AGENT_COMPLETED":
        return f"{actor} finished | used_tools={payload.get('used_tools')}"
    if kind in {"TOOL_REQUESTED", "TOOL_COMPLETED", "TOOL_FAILED"}:
        arguments = payload.get("arguments") or {}
        hint = arguments.get("query") or arguments.get("url") or arguments.get("path") or arguments.get("command") or ""
        return f"{payload.get('tool')} {str(hint)[:70]}".strip()
    if kind == "WORKER_PROGRESS":
        bits = [str(payload.get("worker_event_type", ""))]
        if payload.get("tool"):
            bits.append(str(payload["tool"]))
        if payload.get("model"):
            bits.append(f"model={payload['model']}")
        if payload.get("used_tools"):
            bits.append(f"used_tools={payload['used_tools']}")
        arguments = payload.get("arguments") or {}
        hint = arguments.get("query") or arguments.get("url") or arguments.get("command") or ""
        if hint:
            bits.append(str(hint)[:60])
        return " ".join(bit for bit in bits if bit)
    if kind == "AGENT_ACTION_INVALID":
        return f"{actor}: {str(payload.get('error'))[:80]} -> asked to re-emit valid JSON"
    if kind == "AGENT_FINAL_BLOCKED":
        return f"{actor}: final blocked ({', '.join(payload.keys() & {'missing_required', 'pending_skill_read'})})"
    return ""


def format_event(event: dict) -> str:
    mapping = ORCHESTRATION_EVENTS if event["rank"] == 0 else GATEWAY_EVENTS
    arrow, channel, fixed = mapping.get(event["event_type"], (event["event_type"], "", ""))
    detail = detail_for(event) or fixed or ""
    return f"{event['created_at']}  {arrow:<24} {channel:<12} {event['event_type']:<20} {detail[:150]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the full A2A communication transcript for a run.")
    parser.add_argument("run_id")
    parser.add_argument("--orchestration-db", type=Path, default=Path("./neura.db"))
    parser.add_argument("--gateway-db", type=Path, default=Path("./neura-worker.db"))
    parser.add_argument("--follow", action="store_true", help="stream events live until the run reaches a terminal state")
    args = parser.parse_args()

    if args.follow:
        import time
        cursors = {0: 0, 1: 1}
        while True:
            fresh: list[dict] = []
            for rank, db_path in ((0, args.orchestration_db), (1, args.gateway_db)):
                batch = load_events(db_path, args.run_id, rank, after_seq=cursors[rank])
                if batch:
                    cursors[rank] = batch[-1]["seq"]
                    fresh.extend(batch)
            for event in sorted(fresh, key=lambda e: (e["created_at"], e["rank"], e["seq"])):
                print(format_event(event), flush=True)
            conn = sqlite3.connect(args.orchestration_db)
            row = conn.execute("SELECT status FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
            conn.close()
            if row and row[0] in {"completed", "failed"} and not fresh:
                print(f"RUN STATUS: {row[0]}")
                break
            time.sleep(2.0)

    events = load_events(args.orchestration_db, args.run_id, rank=0)
    events += load_events(args.gateway_db, args.run_id, rank=1)
    events.sort(key=lambda e: (e["created_at"], e["rank"], e["seq"]))

    if not events:
        raise SystemExit(f"No events found for run {args.run_id}")

    conn = sqlite3.connect(args.orchestration_db)
    conn.row_factory = sqlite3.Row
    run = conn.execute("SELECT objective, status, session_id FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
    final_message = None
    if run and run["session_id"]:
        row = conn.execute(
            "SELECT content FROM messages WHERE session_id=? AND role='assistant' ORDER BY seq DESC LIMIT 1",
            (run["session_id"],),
        ).fetchone()
        final_message = row["content"] if row else None
    conn.close()

    print("=" * 100)
    print("A2A COMMUNICATION TRANSCRIPT")
    print(f"Run: {args.run_id}   Status: {run['status'] if run else 'unknown'}")
    print(f"Objective: {(run['objective'] if run else '')[:150]}")
    print("Services: JARVIS | MARCELO | A2A Worker Gateway | Tool Runner  (4 independent processes)")
    print("Every line below was recorded by the receiving service, merged from both databases.")
    print("=" * 100)

    for event in events:
        print(format_event(event))

    print("=" * 100)
    worker_results = [e for e in events if e["event_type"] == "WORKER_RESULT"]
    models = sorted({e["payload"].get("model") for e in worker_results if e["payload"].get("model")})
    tools = sorted({tool for e in worker_results for tool in (e["payload"].get("used_tools") or [])})
    agents = sorted({e["actor"] for e in worker_results})
    passes = sum(1 for e in events if e["event_type"] == "VERIFY_PASS")
    fails = sum(1 for e in events if e["event_type"] == "VERIFY_FAIL")
    print("SUMMARY")
    print(f"  Worker executions completed over JSON-RPC 2.0 : {len(worker_results)}")
    print(f"  Distinct marketplace agents that executed     : {len(agents)} -> {', '.join(agents)}")
    print(f"  NeuraLake models used by workers              : {', '.join(models)}")
    print(f"  Real tools executed via the runner            : {', '.join(tools)}")
    print(f"  Independent verification verdicts             : {passes} PASS / {fails} FAIL")
    if final_message:
        print("-" * 100)
        print("JARVIS -> HUMAN (final delivered answer, first 400 chars):")
        print(final_message[:400])
    print("=" * 100)


if __name__ == "__main__":
    main()
