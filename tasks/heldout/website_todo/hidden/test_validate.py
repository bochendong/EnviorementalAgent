from harness import call


def test_bad_titles():
    assert call("/api/todos", "POST", {"title": "   "})[0] == 400
    assert call("/api/todos", "POST", {"title": "x" * 81})[0] == 400
    assert call("/api/todos", "POST", {"title": "y" * 80})[0] == 201


def test_bad_priority():
    assert call("/api/todos", "POST", {"title": "pay rent", "priority": "urgent"})[0] == 400


def test_duplicates():
    assert call("/api/todos", "POST", {"title": "Call Mum"})[0] == 201
    assert call("/api/todos", "POST", {"title": "call mum "})[0] == 409
