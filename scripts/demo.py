from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from show_transcript import format_event, load_events  # noqa: E402


DEFAULT_GOAL = (
    "Goal:  eb app where busy home cooks photograph their fridge and get recipe "
    "suggestions. Product: RecipeSnap v0 launch. Target user: busy home cooks. Revenue model: freemium "
    "(free daily suggestions, subscription for personalization); adoption first. Desired outputs: (1) a short "
    "competitive research note grounded in live web research of existing AI recipe apps; (2) a working "
    "single-file landing page landing.html, implemented and sanity-checked with real shell commands; (3) launch "
    "messaging: positioning, three taglines, one launch post draft. Constraints: research claims must cite "
    "fetched public sources; landing.html must be written and validated via shell.exec; keep the plan to at "
    "most 4 tasks. Success criteria: research note and landing.html exist as workspace files, a shell "
    "validation command actually ran, and launch messaging is delivered in the final answer."
)

NEGOTIATION_GOAL_MINIMAL = (
    "Goal: acquire a two-week grocery package for a family of four for our household, under a "
    "strict budget of $1000, by negotiating with the FreshMart seller agent available on this "
    "network. Deliver negotiation_report.md with the final basket, quantities, prices, the "
    "agreed total, and a summary of the negotiation."
)

TERMINAL_STATUSES = {"completed", "failed"}


async def submit_goal(jarvis_url: str, goal: str, session_id: str | None, answer: str | None) -> tuple[str, str]:
    payload = {"message": goal}
    if session_id:
        payload["session_id"] = session_id
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{jarvis_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    if data["status"] == "needs_input" and answer:
        payload = {"message": answer, "session_id": data["session_id"]}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{jarvis_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    return data["status"], data.get("run_id") or ""


def run_status(db_path: Path, run_id: str) -> str | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
    conn.close()
    return row[0] if row else None


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-command A2A demo: submit a goal to JARVIS and stream the full inter-agent transcript live.",
        epilog=(
            "Stack must be running. Local: runner 8102, gateway 8010, marcelo 8101 (WORKER_GATEWAY_BASE_URL set), "
            "jarvis 8100. Docker: docker compose up --build then --jarvis http://127.0.0.1:8000."
        ),
    )
    parser.add_argument("--jarvis", default="http://127.0.0.1:8100")
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument(
        "--goal-minimal",
        action="store_true",
        help="purist variant: the negotiation goal with no tool, URL, or plan-size hints - "
        "the orchestrator decides everything autonomously (less deterministic, purest autonomy demo)",
    )
    parser.add_argument("--answer", default=None, help="auto-answer if JARVIS asks a clarifying question")
    parser.add_argument("--session", default=None)
    parser.add_argument("--orchestration-db", type=Path, default=Path("./neura.db"))
    parser.add_argument("--gateway-db", type=Path, default=Path("./neura-worker.db"))
    parser.add_argument("--workspace-root", type=Path, default=Path("./tmp-a2a-workspace"))
    args = parser.parse_args()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(f"{args.jarvis}/health")
            health.raise_for_status()
    except Exception:
        print(f"JARVIS is not reachable at {args.jarvis}. Boot the stack first (see --help epilog).")
        return 2

    goal = NEGOTIATION_GOAL_MINIMAL if args.goal_minimal else args.goal
    status, run_id = await submit_goal(args.jarvis, goal, args.session, args.answer)
    if status != "accepted" or not run_id:
        print(f"JARVIS did not accept the goal (status={status}). Re-run with --answer '<your answer>'.")
        return 2

    print("=" * 100)
    print("LIVE A2A DEMO — every line is an inter-agent message recorded by the receiving service")
    print(f"Run: {run_id}")
    print("=" * 100)

    cursors = {0: 0, 1: 0}
    while True:
        fresh: list[dict] = []
        for rank, db_path in ((0, args.orchestration_db), (1, args.gateway_db)):
            events = load_events(db_path, run_id, rank, after_seq=cursors[rank])
            if events:
                cursors[rank] = events[-1]["seq"]
                fresh.extend(events)
        for event in sorted(fresh, key=lambda e: (e["created_at"], e["rank"], e["seq"])):
            print(format_event(event), flush=True)
        status = run_status(args.orchestration_db, run_id)
        if status in TERMINAL_STATUSES:
            print("=" * 100)
            print(f"RUN STATUS: {status}")
            workspace = args.workspace_root / run_id
            if workspace.exists():
                print("Workspace artifacts:")
                for path in sorted(workspace.rglob("*")):
                    if path.is_file():
                        print(f"  {path}")
            print("Full transcript anytime: python scripts/show_transcript.py", run_id)
            return 0 if status == "completed" else 1
        await asyncio.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
