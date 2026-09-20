import pytest

from neura_marketplace.tool_protocol import parse_action


def test_parse_tool_call():
    action = parse_action('{"type":"tool_call","tool":"web.search","arguments":{"query":"x"}}')
    assert action['type'] == 'tool_call'
    assert action['tool'] == 'web.search'


def test_parse_final():
    action = parse_action('{"type":"final","content":"done"}')
    assert action == {'type': 'final', 'content': 'done'}


def test_reject_unknown_tool():
    with pytest.raises(ValueError):
        parse_action('{"type":"tool_call","tool":"host.root","arguments":{}}')


def test_parse_tool_type_variants_normalize_to_tool_call():
    for action_type in ("tool", "tool_call", "tool_calls"):
        action = parse_action(f'{{"type":"{action_type}","tool":"web.search","arguments":{{"query":"x"}}}}')
        assert action == {'type': 'tool_call', 'tool': 'web.search', 'arguments': {'query': 'x'}}


def test_parse_action_without_type_infers_tool_call():
    action = parse_action('{"tool":"web.search","arguments":{"query":"x"}}')
    assert action == {'type': 'tool_call', 'tool': 'web.search', 'arguments': {'query': 'x'}}
