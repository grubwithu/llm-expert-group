from app.protocol import extract_json_object


def test_extract_json_object_accepts_fenced_json():
    assert extract_json_object('```json\n{"action":"final","content":"ok"}\n```') == {
        "action": "final",
        "content": "ok",
    }


def test_extract_json_object_finds_embedded_object():
    assert extract_json_object('prefix {"action":"ask_secretary","question":"q"} suffix') == {
        "action": "ask_secretary",
        "question": "q",
    }


def test_extract_json_object_rejects_non_object_json():
    assert extract_json_object('[1, 2, 3]') is None
