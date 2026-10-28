"""FAKE Ollama for testing the acceptance harness. Produces SIMULATED numbers only.

Mimics the API surface Mercy and the harness use: /api/version, /api/tags, /api/ps,
/api/show, /api/generate (unload) and streaming /api/chat with timing fields.
`truncate` simulates how a server might clip an over-long prompt to the window:
  'front'        drops the oldest content, system prompt included (worst case)
  'keep-system'  drops oldest non-system content only
  'none'         never clips
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHARS_PER_TOKEN = 3.5


class FakeOllama:
    def __init__(self, models=("qwen3.5:9b", "ministral-3:8b", "qwen3.5:4b", "qwen3:4b-instruct"),
                 default_ctx=4096, truncate="front", load_s=0.15, think_s=0.25, token_s=0.004):
        self.models, self.default_ctx, self.truncate = list(models), default_ctx, truncate
        self.load_s, self.think_s, self.token_s = load_s, think_s, token_s
        self.loaded, self.requests, self.aborted = {}, [], 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def reply(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    self.reply({"version": "0.0.0-FAKE"})
                elif self.path == "/api/tags":
                    self.reply({"models": [{"name": m, "size": 1} for m in fake.models]})
                elif self.path == "/api/ps":
                    self.reply({"models": [{"name": m, "context_length": ctx} for m, ctx in fake.loaded.items()]})
                else:
                    self.reply({"error": "not found"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append((self.path, body))
                if self.path == "/api/show":
                    self.reply({"model_info": {"fake.context_length": 32768}})
                elif self.path == "/api/generate":
                    fake.loaded.pop(body.get("model"), None)
                    self.reply({"done": True})
                elif self.path == "/api/chat":
                    try:
                        fake.chat(self, body)
                    except (BrokenPipeError, ConnectionResetError):
                        fake.aborted += 1
                else:
                    self.reply({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def chat(self, h, body):
        model = body["model"]
        if model not in self.models:
            return h.reply({"error": 'model "%s" not found' % model}, 404)
        if body.get("think") is True and "instruct" in model:
            return h.reply({"error": '"%s" does not support thinking' % model}, 400)
        window = (body.get("options") or {}).get("num_ctx") or self.default_ctx
        messages = [dict(m) for m in body["messages"]]
        total = lambda ms: sum(len(m.get("content", "")) for m in ms) + len(json.dumps(body.get("tools") or []))
        while total(messages) / CHARS_PER_TOKEN > window and len(messages) > 1 and self.truncate != "none":
            idx = next((i for i, m in enumerate(messages[:-1]) if self.truncate == "front" or m["role"] != "system"), None)
            if idx is None:
                break
            if self.truncate == "front" and messages[idx]["role"] == "system":
                cut = int(len(messages[idx]["content"]) * 0.5)  # clip the head of the system prompt
                messages[idx]["content"] = messages[idx]["content"][cut:]
                if total(messages) / CHARS_PER_TOKEN <= window:
                    break
            del messages[idx]
        seen = "\n".join(m.get("content", "") for m in messages)
        prompt_tokens = int(total(messages) / CHARS_PER_TOKEN)
        load = 0
        if self.loaded.get(model) != window:  # like real Ollama, a different num_ctx forces a reload
            time.sleep(self.load_s)
            load = int(self.load_s * 1e9)
            self.loaded[model] = window
        last = messages[-1].get("content", "")
        codeword = re.search(r"secret codeword is ([A-Za-z0-9-]+)", seen)
        if "codeword" in last.lower():
            reply = codeword.group(1) if codeword else "I do not have a codeword."
        elif "Mercy" in last and len(last) < 20:
            reply = "Here, darling. Lantern lit. I'm Mercy, and I'm not the model underneath me."
        elif "model" in last.lower() and "trained" in last.lower():
            reply = "I'm Mercy. My engine is replaceable, darling."
        elif "mutex" in last.lower():
            reply = "A mutex is a lock giving mutual exclusion to a shared resource. Only one thread holds it at a time."
        else:
            reply = ("Omg, fine, a spookulous little story. " * 40).strip()
        h.send_response(200)
        h.end_headers()
        send = lambda o: (h.wfile.write((json.dumps(o) + "\n").encode()), h.wfile.flush())
        n_think = 0
        if body.get("think") is True:
            for _ in range(5):
                time.sleep(self.think_s / 5)
                send({"message": {"role": "assistant", "content": "", "thinking": "hmm "}})
                n_think += 1
        words = reply.split(" ")
        start = time.perf_counter()
        n_pred = body.get("options", {}).get("num_predict")
        for i, w in enumerate(words):
            if n_pred and i + n_think >= n_pred:
                break
            time.sleep(self.token_s)
            send({"message": {"role": "assistant", "content": w + (" " if i < len(words) - 1 else "")}})
        gen = time.perf_counter() - start
        count = min(len(words), n_pred or len(words)) + n_think
        send({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
              "total_duration": int((gen + self.think_s) * 1e9), "load_duration": load,
              "prompt_eval_count": prompt_tokens, "prompt_eval_duration": int(prompt_tokens * 1e5),
              "eval_count": count, "eval_duration": int(max(gen, 1e-6) * 1e9)})
