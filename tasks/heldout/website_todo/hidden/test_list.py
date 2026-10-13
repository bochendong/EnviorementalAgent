import json
from harness import call


def test_order():
    made = []
    for title, pr in [("l-a", "low"), ("l-b", "high"), ("l-c", "normal"), ("l-d", "high"), ("l-e", None)]:
        s, _, b = call("/api/todos", "POST", {"title": title, **({"priority": pr} if pr else {})})
        assert s == 201
        made.append(json.loads(b))
    s, _, b = call("/api/todos")
    assert s == 200
    mine = [t["title"] for t in json.loads(b) if t["title"].startswith("l-")]
    assert mine == ["l-b", "l-d", "l-c", "l-e", "l-a"], mine
