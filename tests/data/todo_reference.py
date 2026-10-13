"""Reference solution of tasks/heldout/website_todo (for tests only; agents never see it)."""

ROUTES = '''import re
import rules

TODOS = []


def handle(method, path, body):
    if path == "/api/todos" and method == "POST":
        body = body or {}
        try:
            title, priority = rules.clean(body.get("title", ""), body.get("priority"))
        except ValueError as e:
            return "400 Bad Request", {"error": str(e)}
        if any(t["title"].lower() == title.lower() for t in TODOS):
            return "409 Conflict", {"error": "duplicate"}
        t = {"id": len(TODOS) + 1, "title": title, "priority": priority, "done": False}
        TODOS.append(t)
        return "201 Created", t
    if path == "/api/todos" and method == "GET":
        return "200 OK", sorted(TODOS, key=rules.order_key)
    m = re.fullmatch(r"/api/todos/(\\d+)", path)
    if m and method == "PATCH":
        for t in TODOS:
            if t["id"] == int(m.group(1)):
                t["done"] = bool((body or {}).get("done"))
                return "200 OK", t
    return "404 Not Found", {"error": "not found"}
'''

RULES = '''RANK = {"high": 0, "normal": 1, "low": 2}


def clean(title, priority):
    title = (title or "").strip()
    if not title or len(title) > 80:
        raise ValueError("bad title")
    priority = priority or "normal"
    if priority not in RANK:
        raise ValueError("bad priority")
    return title, priority


def order_key(todo):
    return (RANK[todo["priority"]], todo["id"])
'''
