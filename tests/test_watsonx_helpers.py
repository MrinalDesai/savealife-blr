from app.services.watsonx import extract_json


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_wrapped():
    out = extract_json('Sure, here:\n```json\n{"severity": "P1", "x": [1,2]}\n```')
    assert out == '{"severity": "P1", "x": [1, 2]}'


def test_extract_json_none():
    assert extract_json("no json here") == "no json here"
