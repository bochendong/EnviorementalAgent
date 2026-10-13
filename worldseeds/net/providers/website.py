"""Building software as a task provider: a shared, versioned workspace, tests run in a sandbox, a client.

The team edits one workspace (every write makes a new version; any version can be read or submitted).
Roles own parts of it (``write`` path prefixes) and hold different tools: by default only the product
manager can ask the client what they want, so requirements must travel through the network.

    ls / read / write / log    the workspace
    run_tests                  the public tests (and any the team wrote under tests/), in a sandbox
    ask_client                 the client answers questions about what they want (from hidden notes)

Tasks are features; each has hidden acceptance tests run on the submitted version (the artifact is a
version number, default the latest). The final task, ``release``, runs every hidden test.

The built-in task is a small shop website (WSGI, standard library only) whose details (name, hours,
products, discount) are drawn from the seed and known only to the client. ``change`` is the chance per
round that the client changes their mind about a price (a public notice says something changed).

Any task can be loaded from a directory instead::

    task.json   {"title": ..., "roles": [{"name", "doc", "write": [...], "ops": [...], "count"}],
                 "client": [{"keywords": [...], "answer": "..."}],
                 "features": [{"id", "text", "deps": [...], "tests": "hidden/test_x.py"}]}
    starter/    the files the workspace starts with (public tests in starter/tests/)
    hidden/     the acceptance tests

Tests are plain Python files with ``test_*`` functions. The sandbox is a temporary directory, a separate
``python -I`` process, CPU, memory and time limits, and a stripped environment; it is not a security
boundary against hostile code, so run untrusted agents inside a container.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core import OpSpec, Role, Score, Task, TaskProvider

RUNNER = r'''
import importlib.util, json, os, sys, traceback, pathlib
sys.path.insert(0, os.getcwd())
res = {"passed": [], "failed": []}
for path in sys.argv[1:]:
    p = pathlib.Path(path)
    try:
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException as e:
        res["failed"].append({"test": p.name, "error": "cannot load: " + "".join(traceback.format_exception_only(type(e), e)).strip()[-400:]})
        continue
    for name in sorted(dir(mod)):
        if name.startswith("test_") and callable(getattr(mod, name)):
            try:
                getattr(mod, name)()
                res["passed"].append(p.stem + "::" + name)
            except BaseException as e:
                msg = "".join(traceback.format_exception_only(type(e), e)).strip()
                res["failed"].append({"test": p.stem + "::" + name, "error": msg[-400:]})
print("@@RESULT@@" + json.dumps(res))
'''


def _limits(cpu: int, mem_mb: int):
    def f():
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        os.setsid()
    return f


def sandbox_run(files: dict[str, str], tests: list[str], timeout: float = 10.0, extra: dict | None = None) -> dict:
    """Write ``files`` (and ``extra``) to a temporary directory and run the test files ``tests`` there."""
    with tempfile.TemporaryDirectory(prefix="ws-sandbox-") as d:
        for path, text in {**files, **(extra or {})}.items():
            p = Path(d) / path
            if not p.resolve().is_relative_to(Path(d).resolve()):
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (Path(d) / "_runner.py").write_text(RUNNER)
        try:
            r = subprocess.run([sys.executable, "-I", "_runner.py", *tests], cwd=d, capture_output=True, text=True,
                               timeout=timeout, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": d, "HOME": d},
                               preexec_fn=_limits(int(timeout) + 1, 1024))
        except subprocess.TimeoutExpired:
            return {"passed": [], "failed": [{"test": "*", "error": f"timed out after {timeout}s"}]}
        out = r.stdout
        if "@@RESULT@@" not in out:
            return {"passed": [], "failed": [{"test": "*", "error": (r.stderr or out)[-800:] or "crashed"}]}
        res = json.loads(out.split("@@RESULT@@")[-1])
        res["stdout"] = out.split("@@RESULT@@")[0][-800:]
        return res


# ------------------------------------------------------------------ the built-in shop
HARNESS = '''"""Call the WSGI app in app.py without a server: status, headers and body of one request."""
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
'''

APP = '''"""The shop's web app. It sends pages to pages.py and the API to api.py (do not change this file)."""
import json
import pages
import api


def app(environ, start_response):
    path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
    if path.startswith("/api/"):
        size = int(environ.get("CONTENT_LENGTH") or 0)
        body = json.loads(environ["wsgi.input"].read(size) or b"null") if size else None
        status, data = api.handle(method, path, body)
        start_response(status, [("Content-Type", "application/json")])
        return [json.dumps(data).encode()]
    status, html = pages.handle(path)
    start_response(status, [("Content-Type", "text/html")])
    return [html.encode()]
'''

PAGES = '''def handle(path):
    """Return (status, html) for a page."""
    return "200 OK", "<p>under construction</p>"
'''

API = '''def handle(method, path, body):
    """Return (status, json-able data) for an API call."""
    return "200 OK", None
'''

PUBLIC_TESTS = '''from harness import call


def test_home_answers():
    status, headers, body = call("/")
    assert status == 200 and "text/html" in headers["Content-Type"]


def test_items_is_a_list():
    import json
    status, _, body = call("/api/items")
    assert status == 200 and isinstance(json.loads(body), list)
'''

NAMES = ["Moss & Fern Tea", "The Copper Kettle", "Blue Heron Books", "Lantern Bakery", "Pine Cone Crafts"]
GOODS = ["green tea", "black tea", "honey", "scone", "mug", "teapot", "notebook", "candle", "jam", "biscuit"]
DAYS = ["Mondays", "Tuesdays", "Sundays"]


def shop_spec(seed: int) -> dict:
    rng = random.Random(f"shop/{seed}")
    goods = rng.sample(GOODS, 4)
    return {"name": rng.choice(NAMES), "open": rng.choice([8, 9, 10]), "close": rng.choice([17, 18, 19]),
            "closed": rng.choice(DAYS), "items": {g: rng.choice([2, 3, 4, 5, 6, 8, 12]) for g in goods},
            "over": rng.choice([15, 20, 25]), "off": rng.choice([10, 20])}


def shop_hidden(s: dict) -> dict[str, str]:
    items = sorted(s["items"].items(), key=lambda kv: (kv[1], kv[0]))
    want = [{"name": n, "price": p} for n, p in items]
    return {
        "hidden/test_home.py": f'''from harness import call
def test_home_heading():
    status, h, body = call("/")
    assert status == 200 and "text/html" in h["Content-Type"]
    assert "<h1>{s["name"]}</h1>" in body.replace("&amp;", "&"), "the main heading must be the shop's name"
''',
        "hidden/test_about.py": f'''from harness import call
def test_about_hours():
    status, _, body = call("/about")
    assert status == 200
    assert "{s["open"]}:00" in body and "{s["close"]}:00" in body, "opening hours missing"
    assert "{s["closed"]}" in body, "closing day missing"
''',
        "hidden/test_items.py": f'''import json
from harness import call
def test_items_exact():
    status, _, body = call("/api/items")
    assert status == 200
    assert json.loads(body) == {want!r}, "items, prices or order differ from what the client wants"
''',
        "hidden/test_cart.py": f'''import json
from harness import call
PRICES = {s["items"]!r}
def total(names):
    t = sum(PRICES[n] for n in names)
    return round(t * (100 - {s["off"]}) / 100, 2) if t > {s["over"]} else t
def test_cart_totals():
    names = sorted(PRICES)
    for basket in ([names[0]], names[:2], names, names * 3):
        status, _, body = call("/api/cart", "POST", {{"items": basket}})
        assert status == 200
        got = json.loads(body)["total"]
        assert abs(got - total(basket)) < 1e-6, f"wrong total for {{basket}}: {{got}}"
def test_cart_unknown_item():
    status, _, _ = call("/api/cart", "POST", {{"items": ["unicorn"]}})
    assert status == 400
''',
        "hidden/test_missing.py": '''from harness import call
def test_not_found():
    assert call("/no/such/page")[0] == 404
    assert call("/api/nothing")[0] == 404
''',
    }


def shop_task(seed: int) -> dict:
    s = shop_spec(seed)
    items = ", ".join(f"{n} ({p} coins)" for n, p in s["items"].items())
    return {
        "title": "a small shop website",
        "spec": s,
        "files": {"app.py": APP, "harness.py": HARNESS, "pages.py": PAGES, "api.py": API,
                  "tests/test_public.py": PUBLIC_TESTS},
        "readonly": ["app.py", "harness.py"],
        "roles": [
            {"name": "pm", "doc": "Product manager: talks to the client and checks the work.", "write": ["tests/"],
             "ops": ["ls", "read", "log", "run_tests", "ask_client", "write"]},
            {"name": "frontend", "doc": "Writes the pages (pages.py).", "write": ["pages.py", "tests/"],
             "ops": ["ls", "read", "log", "write", "run_tests"]},
            {"name": "backend", "doc": "Writes the API (api.py).", "write": ["api.py", "tests/"],
             "ops": ["ls", "read", "log", "write", "run_tests"]},
        ],
        "client": [
            {"keywords": ["name", "called", "heading", "title", "brand", "home"],
             "answer": f"The shop is called \"{s['name']}\". The home page should have exactly that as its <h1>."},
            {"keywords": ["hours", "open", "opening", "close", "closed", "about", "day"],
             "answer": f"We open at {s['open']}:00 and close at {s['close']}:00, and we are closed on "
                       f"{s['closed']}. Put that on the /about page (write the times like {s['open']}:00)."},
            {"keywords": ["items", "products", "sell", "price", "prices", "catalog", "menu", "list"],
             "answer": f"We sell: {items}. /api/items should return a JSON list of {{\"name\", \"price\"}} "
                       "objects, cheapest first (ties by name)."},
            {"keywords": ["cart", "total", "discount", "basket", "order", "checkout", "sale"],
             "answer": f"POST /api/cart with {{\"items\": [names]}} returns {{\"total\": ...}}. Orders over "
                       f"{s['over']} coins get {s['off']}% off (round to 2 decimals). Unknown items: status 400."},
            {"keywords": ["404", "missing", "unknown", "error", "not found"],
             "answer": "Any page or API path we did not talk about should answer 404."},
        ],
        "features": [
            {"id": "home", "text": "The home page shows the shop's name as its main heading.",
             "tests": "hidden/test_home.py"},
            {"id": "about", "text": "An /about page with the opening hours.", "tests": "hidden/test_about.py"},
            {"id": "items", "text": "GET /api/items lists what the shop sells, with prices.",
             "tests": "hidden/test_items.py"},
            {"id": "cart", "text": "POST /api/cart totals a basket the way the client wants.",
             "tests": "hidden/test_cart.py", "deps": ["items"], "reward": 2},
            {"id": "missing", "text": "Unknown pages and API paths answer 404.", "tests": "hidden/test_missing.py"},
        ],
        "hidden": shop_hidden(s),
    }


def load_task_dir(path: str) -> dict:
    root = Path(path)
    t = json.loads((root / "task.json").read_text())
    files = {str(p.relative_to(root / "starter")): p.read_text() for p in (root / "starter").rglob("*") if p.is_file()}
    hidden = {str(p.relative_to(root)): p.read_text() for p in (root / "hidden").rglob("*") if p.is_file()}
    return {**t, "files": files, "hidden": hidden}


class WebsiteProvider(TaskProvider):
    name = "website"

    def __init__(self, task_dir: str = "", counts: dict | None = None, free_roles: bool = False,
                 change: float = 0.0, test_cost: int = 3, timeout: float = 10.0):
        self.task_dir, self.counts, self.free = task_dir, counts or {}, free_roles
        self.change, self.test_cost, self.timeout = change, test_cost, timeout

    def reset(self, seed: int = 0) -> dict:
        self.seed = seed
        self.rng = random.Random(f"website/{seed}")
        self.t = load_task_dir(self.task_dir) if self.task_dir else shop_task(seed)
        self.versions: list[dict] = [{"files": dict(self.t["files"]), "by": "starter", "note": "starter files"}]
        self.asked: dict[str, int] = {}
        return {"world": "website", "task": self.t["title"], "files": sorted(self.t["files"]),
                "features": len(self.t["features"])}

    @property
    def files(self) -> dict[str, str]:
        return self.versions[-1]["files"]

    def roles(self) -> list[Role]:
        if self.free:
            return [Role("developer", "Can do everything.", None, self.counts.get("developer", 3),
                         {"write": [""]})]
        return [Role(r["name"], r.get("doc", ""), tuple(r["ops"]) if r.get("ops") else None,
                     self.counts.get(r["name"], r.get("count", 1)), {"write": r.get("write", [""])})
                for r in self.t["roles"]]

    def ops(self) -> list[OpSpec]:
        S, I = {"type": "string"}, {"type": "integer"}
        return [
            OpSpec("ls", "List the files of the workspace (latest version, or a given one).", {"version": I}),
            OpSpec("read", "Read a file.", {"path": S, "version": I}, ("path",)),
            OpSpec("write", "Write a whole file (a new version of the workspace). Only paths your role owns.",
                   {"path": S, "content": S, "note": S}, ("path", "content")),
            OpSpec("log", "The versions of the workspace: who wrote what."),
            OpSpec("run_tests", "Run the public tests and tests/ on a version (default latest), in a sandbox.",
                   {"version": I, "path": {**S, "description": "only this test file"}}, cost=self.test_cost),
            OpSpec("ask_client", "Ask the client a question about what they want.", {"question": S},
                   ("question",)),
        ]

    def artifact_schema(self) -> dict:
        return {"type": "integer", "description": "a workspace version (default: the latest)"}

    def _version(self, v) -> dict:
        v = -1 if v is None else int(v)
        if not -len(self.versions) <= v < len(self.versions):
            raise ValueError(f"versions are 0..{len(self.versions) - 1}")
        return self.versions[v]["files"]

    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict:
        if op == "ls":
            fs = self._version(args.get("version"))
            return {"files": {p: len(c) for p, c in sorted(fs.items())}, "version": len(self.versions) - 1}
        if op == "read":
            fs = self._version(args.get("version"))
            if args["path"] not in fs:
                return {"error": f"no file {args['path']!r}"}
            return {"path": args["path"], "content": fs[args["path"]]}
        if op == "write":
            path, content = args["path"].lstrip("/"), args["content"]
            if ".." in path.split("/") or path.startswith("hidden"):
                return {"error": "not a workspace path"}
            if path in self.t.get("readonly", ()):
                return {"error": f"{path} is read-only"}
            if not any(path.startswith(pre) for pre in role.scope.get("write", [""])):
                return {"error": f"your role ({role.name}) may only write {role.scope.get('write')}"}
            if len(content) > 100_000:
                return {"error": "file too large"}
            self.versions.append({"files": {**self.files, path: content}, "by": agent,
                                  "note": args.get("note", f"write {path}")})
            return {"version": len(self.versions) - 1}
        if op == "log":
            return {"versions": [{"version": i, "by": v["by"], "note": v["note"]}
                                 for i, v in enumerate(self.versions)][-30:]}
        if op == "run_tests":
            fs = self._version(args.get("version"))
            tests = [p for p in fs if p.startswith("tests/") and p.endswith(".py")]
            if args.get("path"):
                tests = [p for p in tests if p == args["path"]]
            if not tests:
                return {"error": "no tests to run"}
            res = sandbox_run(fs, tests, self.timeout)
            return {"passed": len(res["passed"]), "failed": res["failed"][:10], "stdout": res.get("stdout", "")}
        if op == "ask_client":
            return {"answer": self._answer(args["question"])}
        return {"error": f"unknown op {op}"}

    def _answer(self, q: str) -> str:
        words = set(re.findall(r"[a-z0-9]+", q.lower()))
        best, hit = None, 0
        for c in self.t["client"]:
            n = sum(1 for k in c["keywords"] if k in words or (" " in k and k in q.lower()))
            if n > hit:
                best, hit = c, n
        if best is None:
            topics = sorted({c["keywords"][0] for c in self.t["client"]})
            return f"Sorry, I am not sure what you mean. You can ask me about: {', '.join(topics)}."
        return best["answer"]

    def tasks(self) -> list[Task]:
        fs = self.t["features"]
        out = [Task(f["id"], f["text"], "feature", tuple(f.get("deps", ())), f.get("reward", 1.0)) for f in fs]
        out.append(Task("release", "Every feature works together in one version.", "release",
                        tuple(f["id"] for f in fs), 3.0, final=True))
        return out

    def verify(self, task: Task, artifact, agent: str) -> Score:
        try:
            fs = self._version(artifact)
        except (ValueError, TypeError) as e:
            return Score(False, 0.0, {"error": str(e)})
        hidden = self.t["hidden"]
        if task.id == "release":
            tests = [f["tests"] for f in self.t["features"]]
        else:
            tests = [next(f["tests"] for f in self.t["features"] if f["id"] == task.id)]
        res = sandbox_run(fs, tests, self.timeout, extra={p: hidden[p] for p in tests})
        n_ok, n = len(res["passed"]), len(res["passed"]) + len(res["failed"])
        ok = n > 0 and not res["failed"]
        # say which acceptance test failed and its assertion message, not the test's code
        return Score(ok, 1.0 if ok else n_ok / max(n, 1),
                     {"passed": n_ok, "of": n, "failed": [f["test"] + ": " + f["error"][-200:] for f in res["failed"]][:5]})

    def tick(self, round: int) -> list[dict]:
        if not self.change or self.task_dir or self.rng.random() >= self.change:
            return []
        s = self.t["spec"]
        good = self.rng.choice(sorted(s["items"]))
        s["items"][good] = self.rng.choice([p for p in (2, 3, 4, 5, 6, 8, 12) if p != s["items"][good]])
        self.t["hidden"] = shop_hidden(s)
        items = ", ".join(f"{n} ({p} coins)" for n, p in s["items"].items())
        for c in self.t["client"]:
            if "items" in c["keywords"]:
                c["answer"] = re.sub(r"We sell: .*?\. ", f"We sell: {items}. ", c["answer"])
        return [{"kind": "change", "public": True, "text": "The client has changed their mind about a price."}]

    def summary(self) -> dict:
        return {"versions": len(self.versions)}
