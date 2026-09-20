import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from neura_marketplace.seller_app import create_seller_app


SELLER = 'http://seller:8020'

COUNTER = json.dumps({
    'reply': 'I can do 5% off if you take the bundle.',
    'action': 'counter',
    'offer': {
        'items': [{'name': 'Whole Milk', 'qty': 4, 'unit_price_cents': 370}],
        'subtotal_cents': 1480,
        'discount_percent': 5,
        'total_cents': 1406,
    },
})

ACCEPT = json.dumps({
    'reply': 'Deal.',
    'action': 'accept',
    'offer': {
        'items': [{'name': 'Whole Milk', 'qty': 4, 'unit_price_cents': 331}],
        'subtotal_cents': 1324,
        'discount_percent': 0,
        'total_cents': 1324,
    },
})


class FakeSellerLLM:
    def __init__(self):
        self.calls = []
        self.responses = [COUNTER, ACCEPT]

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


async def build_seller(tmp_path: Path):
    llm = FakeSellerLLM()
    app = create_seller_app(db_path=tmp_path / 'seller.db', llm=llm, base_url=SELLER)  # type: ignore[arg-type]
    return app, llm


def send_message_params(text: str, negotiation_id: str) -> dict:
    return {
        'message': {'role': 'user', 'parts': [{'kind': 'text', 'text': text}]},
        'metadata': {'negotiation_id': negotiation_id},
    }


@pytest.mark.asyncio
async def test_seller_card_is_spec_shaped(tmp_path: Path):
    app, _ = await build_seller(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=SELLER) as client:
        response = await client.get('/.well-known/agent.json')
    assert response.status_code == 200
    card = response.json()
    assert card['name'] == 'FreshMart Seller'
    assert card['endpoint'] == f'{SELLER}/rpc'
    assert card['skills'][0]['id'] == 'negotiate-grocery-package'


@pytest.mark.asyncio
async def test_seller_catalog_seeded(tmp_path: Path):
    app, _ = await build_seller(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=SELLER) as client:
        response = await client.get('/catalog')
    items = response.json()['items']
    assert len(items) >= 20
    assert all('price_cents' in item for item in items)


@pytest.mark.asyncio
async def test_negotiation_rounds_are_explicit_and_persisted(tmp_path: Path):
    app, llm = await build_seller(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=SELLER) as client:
        first = await client.post('/rpc', json={
            'jsonrpc': '2.0', 'method': 'message/send',
            'params': send_message_params('I need 4 gallons of milk, budget is tight.', 'neg-1'), 'id': 1,
        })
        second = await client.post('/rpc', json={
            'jsonrpc': '2.0', 'method': 'message/send',
            'params': send_message_params('Meet me at 85% of list and we have a deal.', 'neg-1'), 'id': 2,
        })
        history = await client.post('/rpc', json={
            'jsonrpc': '2.0', 'method': 'negotiation/history',
            'params': {'negotiation_id': 'neg-1'}, 'id': 3,
        })

    task_one = first.json()['result']['task']
    assert task_one['state'] == 'completed'
    reply = json.loads(task_one['artifacts'][0]['parts'][0]['text'])
    assert reply['action'] == 'counter'
    assert reply['offer']['total_cents'] == 1406

    reply_two = json.loads(second.json()['result']['task']['artifacts'][0]['parts'][0]['text'])
    assert reply_two['action'] == 'accept'

    messages = history.json()['result']['messages']
    roles = [message['role'] for message in messages]
    assert roles == ['buyer', 'seller', 'buyer', 'seller']
    assert 'budget is tight' in messages[0]['content']

    # The seller saw the catalog context matched from the buyer's message.
    assert 'milk' in json.dumps(llm.calls[0]['messages'][1]['content']).lower()


@pytest.mark.asyncio
async def test_seller_unknown_method_rejected(tmp_path: Path):
    app, _ = await build_seller(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=SELLER) as client:
        response = await client.post('/rpc', json={
            'jsonrpc': '2.0', 'method': 'steal_money', 'params': {}, 'id': 1,
        })
    assert response.json()['error']['code'] == -32601


def test_a2a_call_allowlist_blocks_unknown_destinations():
    from neura_marketplace.runner_app import _allowed_a2a_url

    assert _allowed_a2a_url('http://127.0.0.1:8020/rpc')
    with pytest.raises(HTTPException):
        _allowed_a2a_url('http://evil.example.com/rpc')
    with pytest.raises(HTTPException):
        _allowed_a2a_url('file:///etc/passwd')
