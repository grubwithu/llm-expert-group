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


def test_extract_json_object_uses_last_concatenated_action():
    assert extract_json_object('{"action":"ask_secretary","question":"check"}{"action":"final","content":"answer"}') == {
        "action": "final",
        "content": "answer",
    }


def test_extract_json_object_recovers_final_with_unescaped_newlines_and_quotes():
    raw = '{"action":"final","content":"First line\nA malformed "quoted" phrase."}'

    assert extract_json_object(raw) == {
        "action": "final",
        "content": 'First line\nA malformed "quoted" phrase.',
    }


def test_extract_json_object_recovers_truncated_final_content():
    raw = '```json\n{"action":"final","content":"Useful answer\\nthat ended before the JSON wrapper closed'

    assert extract_json_object(raw) == {
        "action": "final",
        "content": "Useful answer\nthat ended before the JSON wrapper closed",
    }
