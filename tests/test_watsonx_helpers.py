from app.services.watsonx import extract_json


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_wrapped():
    out = extract_json('Sure, here:\n```json\n{"severity": "P1", "x": [1,2]}\n```')
    assert out == '{"severity": "P1", "x": [1, 2]}'


def test_extract_json_none():
    assert extract_json("no json here") == "no json here"


def test_polyline_decoder():
    from app.services.routes_api import decode_polyline
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert [[round(a, 5), round(b, 5)] for a, b in pts] == [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]
