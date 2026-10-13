import json
from harness import call


def test_done_and_missing():
    t = json.loads(call("/api/todos", "POST", {"title": "d-water plants"})[2])
    s, _, b = call(f"/api/todos/{t['id']}", "PATCH", {"done": True})
    assert s == 200 and json.loads(b)["done"] is True
    s, _, b = call(f"/api/todos/{t['id']}", "PATCH", {"done": False})
    assert json.loads(b)["done"] is False
    assert call("/api/todos/9999", "PATCH", {"done": True})[0] == 404
    assert call("/nowhere")[0] == 404
