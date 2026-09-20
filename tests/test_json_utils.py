from neura_marketplace.json_utils import extract_json


def test_extract_json_from_fenced_block():
    assert extract_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_extract_json_embedded():
    assert extract_json('Result: {"x": 1} done') == {"x": 1}
