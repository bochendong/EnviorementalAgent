"""The to-do web app. The API lives in routes.py (do not change this file)."""
import json
import routes


def app(environ, start_response):
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = json.loads(environ["wsgi.input"].read(size) or b"null") if size else None
    status, data = routes.handle(environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/"), body)
    start_response(status, [("Content-Type", "application/json")])
    return [json.dumps(data).encode()]
