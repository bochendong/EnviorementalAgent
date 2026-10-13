"""A small HTTP JSON API around one NetworkEnv, so agents in any language or framework can take part.

    GET  /info                  provider, problem, agents and the network's rules (config)
    POST /reset   {"seed": 0}
    GET  /ops?agent=a0          the agent's operations (and the same as OpenAI "tools")
    GET  /observe?agent=a0      free summary of the agent's state
    POST /step    {"agent": "a0", "op": "send", "args": {...}}  -> the observation
    GET  /events?since=0        the event log
    GET  /metrics

Requests are served one at a time (the environment is a sequential simulator).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .env import NetworkEnv


def make_handler(env: NetworkEnv):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, data):
            body = json.dumps(data, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _agent(self, q):
            a = (q.get("agent") or [""])[0]
            if a not in env.agents:
                raise KeyError(f"no agent {a!r}")
            return a

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == "/info":
                    return self._send(200, env.public())
                if u.path == "/ops":
                    ops = env.ops(self._agent(q))
                    return self._send(200, {"ops": [s.to_dict() for s in ops], "tools": [s.to_openai() for s in ops]})
                if u.path == "/observe":
                    return self._send(200, env.observe(self._agent(q)))
                if u.path == "/events":
                    since = int((q.get("since") or ["0"])[0])
                    return self._send(200, {"events": env.events[since:]})
                if u.path == "/metrics":
                    return self._send(200, env.metrics())
            except KeyError as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "unknown path"})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body is not JSON"})
            if u.path == "/reset":
                return self._send(200, env.reset(body.get("seed")))
            if u.path == "/step":
                if body.get("agent") not in env.agents:
                    return self._send(400, {"error": f"no agent {body.get('agent')!r}"})
                return self._send(200, env.step(body["agent"], str(body.get("op", "")), body.get("args") or {}))
            self._send(404, {"error": "unknown path"})

    return Handler


def serve(env: NetworkEnv, host: str = "127.0.0.1", port: int = 8090):
    HTTPServer((host, port), make_handler(env)).serve_forever()
