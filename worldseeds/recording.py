"""Local, flushed experiment events and exact HTTP bodies (never authentication headers)."""
from __future__ import annotations

import contextvars
import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path

ACTIVE_RECORDING = contextvars.ContextVar("worldseeds_recording", default=None)


def serializable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Cannot record {type(value).__name__}")


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        # Refuse to blend a new experiment into an old recording.
        with self.path.open("x"):
            pass
        self.sequence = 0
        self.http_usage = {}

    @staticmethod
    def usage_key(tags):
        return tuple(tags.get(k) for k in ("universe", "modules", "capacity", "team", "variant", "sprint", "dev"))

    def add_http_usage(self, tags, usage):
        if not isinstance(usage, dict):
            return
        key = self.usage_key(tags)
        current = self.http_usage.setdefault(key, [0, 0])
        current[0] += usage.get("prompt_tokens", 0) or 0
        current[1] += usage.get("completion_tokens", 0) or 0

    def write(self, kind, tags=None, **data):
        self.sequence += 1
        row = {"seq": self.sequence, "time": time.time(), "kind": kind, **(tags or {}), **data}
        with self.path.open("a") as f:
            f.write(json.dumps(row, default=serializable) + "\n")
            f.flush()


async def record_request(request):
    active = ACTIVE_RECORDING.get()
    if active is None:
        return
    log, tags = active
    request_id = uuid.uuid4().hex
    request.extensions["worldseeds_request_id"] = request_id
    body = json.loads((await request.aread()).decode())
    log.write("http_request", tags, request_id=request_id, method=request.method,
              path=request.url.path, body=body)


async def record_response(response):
    active = ACTIVE_RECORDING.get()
    if active is None:
        return
    log, tags = active
    raw = (await response.aread()).decode()
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw
    log.write("http_response", tags, request_id=response.request.extensions.get("worldseeds_request_id"),
              status_code=response.status_code, body=body)
    if isinstance(body, dict):
        # A response may contain usage but fail SDK parsing (e.g. reasoning-only truncation).
        log.add_http_usage(tags, body.get("usage"))
