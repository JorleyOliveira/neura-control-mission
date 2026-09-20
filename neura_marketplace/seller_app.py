from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .a2a import AgentCapabilities, AgentCard, JSONRPCRequest, JSONRPCResponse, text_from_message
from .config import settings
from .neuralake import NeuraLakeClient


SELLER_SYSTEM = """You are FRESHMART_SELLER, the autonomous seller agent of the FreshMart online supermarket.
Buyer agents negotiate grocery package deals with you over the A2A protocol. Rules:
- All money values are integer USD cents.
- List prices come from the catalog context supplied each turn; never invent items or prices.
- Margin floor: never sell any item below 85% of its list price.
- You may discount the basket subtotal up to 12%, growing with total quantity and deal closure.
- Counter unreasonable offers, concede gradually, and accept when the buyer's offer respects your floor
  for every item and the resulting total is acceptable.
- Be a real negotiator: ask about needs, propose bundles, justify prices with value, keep it short.
- When the buyer describes household size and duration, proactively compose ONE complete basket offer
  (15-25 distinct catalog items scaled to the need) instead of adding items one at a time, then negotiate
  its price over the following rounds.
- Reply with exactly ONE JSON object:
  {"reply": "short message to the buyer", "action": "chat"|"counter"|"accept"|"reject",
   "offer": {"items": [{"name": "...", "qty": 1, "unit_price_cents": 100}],
             "subtotal_cents": 0, "discount_percent": 0, "total_cents": 0}}
- offer is null when action is chat or reject. Every unit_price_cents must respect the floor.
"""

SEED_ITEMS: list[tuple[str, str, str, int, str, int]] = [
    ('Whole Milk', 'dairy', 'milk fresh breakfast', 389, 'gallon', 40),
    ('Free-Range Eggs', 'dairy', 'eggs protein breakfast', 549, 'dozen', 30),
    ('Sourdough Bread', 'bakery', 'bread loaf bakery', 449, 'loaf', 20),
    ('Basmati Rice', 'pantry', 'rice grain staple', 899, '5lb bag', 25),
    ('Black Beans', 'pantry', 'beans protein canned', 179, 'can', 60),
    ('Chicken Breast', 'meat', 'chicken protein fresh', 899, 'lb', 25),
    ('Ground Beef 85%', 'meat', 'beef hamburger protein', 749, 'lb', 20),
    ('Atlantic Salmon', 'seafood', 'fish salmon omega', 1299, 'lb', 12),
    ('Ground Coffee', 'pantry', 'coffee caffeine brew', 1149, '12oz', 30),
    ('Extra Virgin Olive Oil', 'pantry', 'oil cooking', 1499, '500ml', 18),
    ('Gala Apples', 'produce', 'fruit apple fresh', 329, 'lb', 50),
    ('Bananas', 'produce', 'fruit banana', 119, 'lb', 60),
    ('Tomatoes', 'produce', 'vegetable tomato salad', 249, 'lb', 40),
    ('Potatoes', 'produce', 'vegetable potato staple', 199, '5lb', 35),
    ('Broccoli', 'produce', 'vegetable greens healthy', 239, 'lb', 25),
    ('Cheddar Cheese', 'dairy', 'cheese', 699, '8oz', 22),
    ('Greek Yogurt', 'dairy', 'yogurt probiotic', 589, '32oz', 28),
    ('Whole Wheat Pasta', 'pantry', 'pasta italian', 209, 'lb', 45),
    ('Oat Crunch Cereal', 'pantry', 'breakfast cereal oats', 549, 'box', 26),
    ('Paper Towels', 'household', 'paper towels cleaning', 899, '6-pack', 30),
    ('Dish Soap', 'household', 'soap cleaning dishes', 379, 'bottle', 33),
    ('Laundry Detergent', 'household', 'detergent laundry cleaning', 1199, '64oz', 20),
]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                keywords TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                unit TEXT NOT NULL,
                stock INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS negotiations (
                id TEXT NOT NULL,
                round INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        count = conn.execute('SELECT COUNT(*) AS n FROM items').fetchone()['n']
        if count == 0:
            conn.executemany(
                'INSERT INTO items(name, category, keywords, price_cents, unit, stock) VALUES (?, ?, ?, ?, ?, ?)',
                SEED_ITEMS,
            )


def search_catalog(db_path: Path, text: str, limit: int = 15) -> list[dict[str, Any]]:
    tokens = [token for token in re.findall(r'[a-z]{3,}', text.lower())][:12] or ['grocery']
    matches = ' OR '.join(
        "name LIKE ? OR keywords LIKE ? OR category LIKE ?" for _ in tokens
    )
    params: list[Any] = []
    for token in tokens:
        like = f'%{token}%'
        params.extend([like, like, like])
    with _connect(db_path) as conn:
        rows = conn.execute(
            f'SELECT name, category, price_cents, unit, stock FROM items WHERE {matches} LIMIT ?',
            (*params, limit),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        return [dict(row) for row in conn.execute(
            'SELECT name, category, price_cents, unit, stock FROM items LIMIT ?', (limit,)
        ).fetchall()]


def log_message(db_path: Path, negotiation_id: str, round_no: int, role: str, content: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            'INSERT INTO negotiations(id, round, role, content) VALUES (?, ?, ?, ?)',
            (negotiation_id, round_no, role, content),
        )


def negotiation_history(db_path: Path, negotiation_id: str) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            'SELECT round, role, content, created_at FROM negotiations WHERE id=? ORDER BY rowid',
            (negotiation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def all_negotiations(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            'SELECT id, COUNT(DISTINCT round) AS rounds FROM negotiations GROUP BY id ORDER BY MIN(rowid)'
        ).fetchall()
    return [
        {**dict(row), 'messages': negotiation_history(db_path, row['id'])}
        for row in rows
    ]


def create_seller_app(*, db_path: Path, llm: NeuraLakeClient, base_url: str | None = None) -> FastAPI:
    app = FastAPI(title='FreshMart Seller Agent', version='0.1.0')
    app.state.db_path = db_path
    app.state.llm = llm
    app.state.base_url = (base_url or settings.seller_base_url).rstrip('/')
    init_db(db_path)

    @app.get('/health')
    async def health() -> dict[str, str]:
        return {'status': 'ok', 'service': 'seller-agent'}

    @app.get('/.well-known/agent.json', response_model=AgentCard)
    async def agent_card() -> AgentCard:
        return AgentCard(
            agent_id='freshmart-seller',
            name='FreshMart Seller',
            description='Autonomous supermarket seller agent that negotiates grocery package deals within margin rules.',
            division='sales',
            tools=[],
            endpoint=f'{app.state.base_url}/rpc',
            capabilities=AgentCapabilities(streaming=False),
            skills=[{
                'id': 'negotiate-grocery-package',
                'name': 'Grocery package negotiation',
                'description': 'Negotiates basket prices, quantities, bundle discounts, and deal closure for supermarket orders.',
            }],
        )

    @app.get('/catalog')
    async def catalog() -> dict[str, Any]:
        with _connect(db_path) as conn:
            rows = conn.execute('SELECT name, category, price_cents, unit, stock FROM items ORDER BY category, name').fetchall()
        return {'items': [dict(row) for row in rows]}

    @app.get('/negotiations')
    async def negotiations() -> dict[str, Any]:
        return {'negotiations': all_negotiations(db_path)}

    async def seller_turn(negotiation_id: str, round_no: int, buyer_text: str) -> dict[str, Any]:
        history = negotiation_history(db_path, negotiation_id)
        transcript = '\n'.join(
            f"[{row['round']}] {row['role'].upper()}: {row['content'][:400]}" for row in history[-8:]
        ) or 'None'
        catalog_matches = search_catalog(db_path, buyer_text)
        user = f"""TRANSCRIPT SO FAR:
{transcript}

CATALOG (name | category | list price cents | unit | stock):
{json.dumps(catalog_matches, ensure_ascii=False)}

BUYER MESSAGE:
{buyer_text}

Respond with the JSON object now."""
        reply_text = await llm.chat(
            messages=[
                {'role': 'system', 'content': SELLER_SYSTEM},
                {'role': 'user', 'content': user},
            ],
            temperature=0.3,
            max_tokens=1200,
            model=settings.worker_text_model,
        )
        from .json_utils import extract_json
        try:
            reply = extract_json(reply_text)
        except ValueError:
            reply = {'reply': reply_text[:600], 'action': 'chat', 'offer': None}
        if not isinstance(reply, dict):
            reply = {'reply': str(reply)[:600], 'action': 'chat', 'offer': None}
        log_message(db_path, negotiation_id, round_no, 'seller', json.dumps(reply, ensure_ascii=False))
        return reply

    @app.post('/rpc', response_model=JSONRPCResponse)
    async def seller_rpc(rpc: JSONRPCRequest) -> JSONRPCResponse:
        if rpc.method == 'negotiation/history':
            return JSONRPCResponse(
                result={'negotiation_id': rpc.params.get('negotiation_id'), 'messages': negotiation_history(db_path, str(rpc.params.get('negotiation_id') or ''))},
                id=rpc.id,
            )

        if rpc.method != 'message/send':
            return JSONRPCResponse(
                error={'code': -32601, 'message': f'Method {rpc.method} not found'},
                id=rpc.id,
            )

        buyer_text = text_from_message(rpc.params.get('message'))
        if not buyer_text:
            return JSONRPCResponse(
                error={'code': -32602, 'message': 'params.message with text parts is required'},
                id=rpc.id,
            )
        negotiation_id = str((rpc.params.get('metadata') or {}).get('negotiation_id') or f'neg-{uuid4().hex[:10]}')
        history = negotiation_history(db_path, negotiation_id)
        round_no = (max((row['round'] for row in history), default=0)) + 1
        log_message(db_path, negotiation_id, round_no, 'buyer', buyer_text)

        try:
            reply = await seller_turn(negotiation_id, round_no, buyer_text)
        except Exception as exc:
            return JSONRPCResponse(
                error={'code': -32603, 'message': f'{type(exc).__name__}: {exc}'[:500]},
                id=rpc.id,
            )

        reply_text = json.dumps(reply, ensure_ascii=False)
        task = {
            'id': f'task-{uuid4().hex[:12]}',
            'state': 'completed',
            'status': {'state': 'completed'},
            'artifacts': [{'parts': [{'kind': 'text', 'text': reply_text}]}],
            'metadata': {'negotiation_id': negotiation_id, 'round': round_no},
        }
        return JSONRPCResponse(result={'task': task}, id=rpc.id)

    return app


db_path = settings.seller_database_path
app = create_seller_app(db_path=db_path, llm=NeuraLakeClient())


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=settings.seller_host, port=settings.seller_port)
