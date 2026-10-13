import json
from harness import call


def test_create_answers_json():
    status, headers, body = call("/api/todos", "POST", {"title": "public smoke test"})
    assert "application/json" in headers["Content-Type"]
    json.loads(body)
