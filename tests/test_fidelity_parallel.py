import concurrent.futures
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from netagents import fidelity


class FidelityParallelTests(unittest.TestCase):
    def test_out_of_order_questions_and_resume_keep_scores_and_costs(self):
        calls = []

        def question(task):
            arm, q, _, _ = task
            calls.append((arm, q["answer"]))
            time.sleep(0.02 if q["answer"] == "0" else 0.001)
            return {"correct": q["answer"] != "1", "seconds": 1, "output_tokens": 7}

        qs = [{"question": str(i), "answer": str(i)} for i in range(3)]
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = str(Path(directory) / "progress.json")
            # Exercise completion ordering while keeping this bookkeeping test independent of a model.
            with patch.object(fidelity.concurrent.futures, "ProcessPoolExecutor",
                              side_effect=lambda max_workers, **_: concurrent.futures.ThreadPoolExecutor(max_workers)), \
                    patch.object(fidelity, "_question", question):
                arms, costs = fidelity.run_arms(qs, 6, directory, 2, checkpoint, {"thinking": True})
                self.assertEqual(len(calls), 12)
                self.assertTrue(all(v == [True, False, True] for v in arms.values()))
                self.assertTrue(all(v["output_tokens"] == 21 for v in costs.values()))
                resumed = fidelity.run_arms(qs, 6, directory, 2, checkpoint, {"thinking": True})
                self.assertEqual(resumed, (arms, costs))
                self.assertEqual(len(calls), 12)
                with self.assertRaisesRegex(ValueError, "differ"):
                    fidelity.run_arms(qs, 6, directory, 2, checkpoint, {"thinking": False})

    def test_partial_checkpoint_skips_only_completed_questions(self):
        qs = [{"question": "q", "answer": "1"}]
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "progress.json"
            progress = {"identity": {"version": 1, "questions": qs, "calls": 6, "settings": {}},
                        "records": {arm: {} for arm in fidelity.ARMS},
                        "seconds": {arm: 0 for arm in fidelity.ARMS}}
            progress["records"]["official-single"]["0"] = {"correct": True, "seconds": 2, "output_tokens": 5}
            p.write_text(json.dumps(progress))
            with patch.object(fidelity.concurrent.futures, "ProcessPoolExecutor",
                              side_effect=lambda max_workers, **_: concurrent.futures.ThreadPoolExecutor(max_workers)), \
                    patch.object(fidelity, "_question", return_value={"correct": False, "seconds": 1,
                                                                      "output_tokens": 3}) as worker:
                arms, costs = fidelity.run_arms(qs, 6, directory, 2, str(p), {})
            self.assertEqual(worker.call_count, 3)
            self.assertEqual(arms["official-single"], [True])
            self.assertEqual(costs["official-single"]["output_tokens"], 5)

    def test_real_spawned_workers_preserve_official_request_counts(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                data = json.dumps({"id": "test", "object": "chat.completion", "created": 0,
                                   "model": "qwen3-8b", "choices": [{"index": 0, "finish_reason": "stop",
                                   "message": {"role": "assistant", "content": "\\boxed{42}"}}],
                                   "usage": {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 4}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "debate"
                cache.mkdir()
                (cache / "gen_gsm.py").write_text(
                    'def construct_message(*args): return {"role": "user", "content": "Reconsider."}\n')
                with patch.dict(os.environ, {"WS_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}):
                    with concurrent.futures.ProcessPoolExecutor(max_workers=2,
                            mp_context=multiprocessing.get_context("spawn")) as pool:
                        futures = [pool.submit(fidelity._question,
                            (arm, {"question": "6*7?", "answer": "42"}, 6, directory))
                            for arm in ("official-single", "official-debate")]
                        results = [f.result(timeout=30) for f in futures]
                self.assertTrue(all(r["correct"] for r in results))
                self.assertEqual([r["output_tokens"] for r in results], [3, 18])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
