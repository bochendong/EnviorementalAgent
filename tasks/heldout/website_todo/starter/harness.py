"""Call the WSGI app in app.py without a server: status, headers and body of one request."""
import io, json
from app import app


def call(path, method="GET", body=None):
    data = b"" if body is None else json.dumps(body).encode()
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(data)),
           "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(data)}
    out = {}

    def start_response(status, headers):
        out["status"], out["headers"] = status, dict(headers)

    chunks = app(env, start_response)
    text = b"".join(chunks).decode()
    return int(out["status"].split()[0]), out["headers"], text
