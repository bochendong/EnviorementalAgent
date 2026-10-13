#!/usr/bin/env python
"""A stand-in for an OpenAI-compatible chat server, for dry runs of LLM agents without a GPU.

    python scripts/mock_llm_server.py --port 8011 &
    WS_BASE_URL=http://127.0.0.1:8011/v1 WS_MODEL=mock python scripts/run_codeworld.py --policy llm ...

Every request is answered with one call to one of the tools it offers, with arguments that fit the tool's
schema and, where it can, names taken from the conversation (machines like ``bakery.oven``, people like
``dev1``, goal parts like ``g1.2``). The calls are seeded and plausible, not clever: the point is to exercise
the whole loop (tools, budgets, money, goals, replays), not to solve anything.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MACHINE = re.compile(r"\b([a-z]+(?:_[a-z]+)*\.[a-z]+(?:_[a-z]+)*)\b")
PERSON = re.compile(r"\bdev\d+\b")
PART = re.compile(r"\bg\d+\.\d+\b")


def text_of(messages) -> str:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [x.get("text", "") for x in c if isinstance(x, dict)]
    return "\n".join(out)


def fill(schema: dict, words: dict, rng: random.Random, name: str = "") -> object:
    t = schema.get("type")
    if t == "array":
        return [fill(schema.get("items", {}), words, rng, name) for _ in range(rng.randint(1, 4))]
    if t == "integer":
        return rng.randint(0, 100) if name in ("x", "batch") else rng.randint(1, 5)
    if t == "number":
        return round(rng.random() * 5, 2)
    if t == "boolean":
        return rng.random() < .5
    if name in ("function", "program") and words["machines"]:
        return rng.choice(words["machines"])
    if name in ("teammate", "to") and words["people"]:
        return rng.choice(words["people"] + (["treasury"] if name == "to" else []))
    if name == "part" and words["parts"]:
        return rng.choice(words["parts"])
    if name == "law":
        return f"{rng.randint(2, 100)}*x + {rng.randint(0, 100)}"
    if name == "module":
        return ""
    return "hello from the mock"


class Handler(BaseHTTPRequestHandler):
    rng = random.Random(0)

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools = [t["function"] for t in body.get("tools", []) if t.get("type") == "function"]
        txt = text_of(body.get("messages", []))
        words = {"machines": sorted(set(MACHINE.findall(txt)))[:400], "people": sorted(set(PERSON.findall(txt))),
                 "parts": sorted(set(PART.findall(txt)))}
        rng = self.rng
        msg = {"role": "assistant", "content": "I am done."}
        finish = "stop"
        if tools:
            f = rng.choice(tools)
            props = f.get("parameters", {}).get("properties", {})
            args = {k: fill(v, words, rng, k) for k, v in props.items()}
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"call{rng.randrange(1 << 30)}", "type": "function",
                 "function": {"name": f["name"], "arguments": json.dumps(args)}}]}
            finish = "tool_calls"
        resp = {"id": "mock", "object": "chat.completion", "created": 0, "model": body.get("model", "mock"),
                "choices": [{"index": 0, "finish_reason": finish, "message": msg}],
                "usage": {"prompt_tokens": len(txt) // 4, "completion_tokens": 20, "total_tokens": len(txt) // 4 + 20}}
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    Handler.rng = random.Random(a.seed)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
