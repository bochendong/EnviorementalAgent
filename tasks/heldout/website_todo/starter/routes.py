import rules  # noqa: F401  (validation and ordering live there)


def handle(method, path, body):
    """Return (status, json-able data) for one request."""
    return "404 Not Found", {"error": "not implemented"}
