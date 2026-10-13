import json
from harness import call


def test_create():
    s, _, b = call("/api/todos", "POST", {"title": "  buy milk  ", "priority": "high"})
    assert s == 201, f"status {s}"
    t = json.loads(b)
    assert t["title"] == "buy milk" and t["priority"] == "high" and t["done"] is False
    s2, _, b2 = call("/api/todos", "POST", {"title": "walk the dog"})
    t2 = json.loads(b2)
    assert s2 == 201 and t2["priority"] == "normal" and t2["id"] == t["id"] + 1
