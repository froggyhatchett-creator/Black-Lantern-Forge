"""Mercy real-model acceptance + benchmark. Standard library only.

Run against YOUR Ollama:   python tools/real_model_acceptance.py
Self-test with a fake:     python tools/real_model_acceptance.py --simulate   (SIMULATED numbers, proves nothing about models)

Safety: uses a throwaway Mercy profile in a temp directory (never your real profile), never pulls or
installs models, never changes your Ollama configuration. It only unloads models (keep_alive 0) so
the first run of each series is a genuine cold start. Tool requests from models are auto-DENIED.
"""
import argparse
import json
import os
import platform
import queue
import random
import re
import statistics
import string
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mercy import __version__  # noqa: E402
from mercy.application import ApplicationService  # noqa: E402
from mercy.context import ContextBuilder  # noqa: E402

DEFAULT_MODELS = ["qwen3.5:9b", "ministral-3:8b", "qwen3.5:4b", "qwen3:4b-instruct"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route localhost via a proxy
RESULTS = []  # (stage, name, status, detail)


def record(stage, name, status, detail=""):
    RESULTS.append({"stage": stage, "name": name, "status": status, "detail": detail})
    print("[%-4s] %s | %s %s" % (status, stage, name, ("- " + str(detail)) if detail else ""), flush=True)


def http(endpoint, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(endpoint + path, data=data, headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read())


def unload(endpoint, model):
    try:
        http(endpoint, "/api/generate", {"model": model, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def raw_chat(endpoint, model, messages, think, num_ctx=0, num_predict=400, tools=None, timeout=300):
    """One streamed /api/chat call with wall-clock timings. Reasoning tokens are timed but discarded."""
    payload = {"model": model, "messages": messages, "stream": True, "think": think, "keep_alive": "5m",
               "options": {"num_predict": num_predict}}
    if num_ctx:
        payload["options"]["num_ctx"] = num_ctx
    if tools:
        payload["tools"] = tools
    out = {"text": "", "t_first_any": None, "t_first_text": None, "chunks": 0, "error": None}
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(endpoint + "/api/chat", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=timeout) as r:
            for line in r:
                item = json.loads(line)
                now = time.perf_counter() - t0
                msg = item.get("message", {})
                if (msg.get("thinking") or msg.get("content")) and out["t_first_any"] is None:
                    out["t_first_any"] = now
                if msg.get("content"):
                    out["text"] += msg["content"]
                    out["chunks"] += 1
                    if out["t_first_text"] is None:
                        out["t_first_text"] = now
                if item.get("done"):
                    for k in ("eval_count", "eval_duration", "load_duration", "prompt_eval_count", "done_reason"):
                        out[k] = item.get(k)
    except urllib.error.HTTPError as exc:
        out["error"] = "HTTP %d: %s" % (exc.code, exc.read(300).decode("utf-8", "replace"))
    except Exception as exc:
        out["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    out["total"] = time.perf_counter() - t0
    if out.get("eval_count") and out.get("eval_duration"):
        out["tok_s"] = out["eval_count"] / (out["eval_duration"] / 1e9)
    return out


def med(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 3) if values else None


# ---------------------------------------------------------------- Mercy (real application path)
class Harness:
    def __init__(self, endpoint, timeout):
        self.endpoint, self.timeout = endpoint, timeout
        self.dir = Path(tempfile.mkdtemp(prefix="mercy-acceptance-"))
        self.service = ApplicationService(self.dir / "profile")

    def configure(self, model, think, num_ctx=0):
        s = self.service
        s.configure({**s.config, "provider": "ollama", "model": model, "endpoint": self.endpoint,
                     "think": think, "num_ctx": num_ctx, "generation_timeout": self.timeout, "status_timeout": 10})

    def drain(self):
        while not self.service.events.empty():
            self.service.events.get_nowait()

    def turn(self, text, cancel_after_first=False, patience=None):
        """Send through ApplicationService -> MercyCore -> ManagedProvider (subprocess) -> Ollama."""
        s, t0 = self.service, time.perf_counter()
        self.drain()
        s.send(text)
        r = {"text": "", "ttft": None, "total": None, "error": None, "permissions": 0, "events": 0, "cancel_latency": None}
        t_cancel = None
        while time.perf_counter() - t0 < (patience or self.timeout) + 15:
            try:
                kind, value = s.events.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "text":
                r["events"] += 1
                r["text"] += value
                if r["ttft"] is None:
                    r["ttft"] = time.perf_counter() - t0
                if cancel_after_first and t_cancel is None:
                    t_cancel = time.perf_counter()
                    s.cancel()
            elif kind == "permission":
                r["permissions"] += 1
                s.respond(value.id, False)  # acceptance never grants tool power
            elif kind == "error":
                r["error"] = value
            elif kind == "done":
                break
        r["total"] = time.perf_counter() - t0
        if t_cancel:
            r["cancel_latency"] = time.perf_counter() - t_cancel
        return r

    def last_turn_state(self):
        return self.service.store.turns(self.service.config["conversation_id"])[-1]["state"]


# ---------------------------------------------------------------- stages
def stage_discovery(a, h):
    try:
        version = http(a.endpoint, "/api/version", timeout=10).get("version")
        record("1-discovery", "/api/version", "PASS", version)
        tags = [m["name"] for m in http(a.endpoint, "/api/tags", timeout=10)["models"]]
        record("1-discovery", "/api/tags", "PASS", ", ".join(tags))
    except Exception as exc:
        record("1-discovery", "Ollama reachable", "FAIL", "%s: %s" % (type(exc).__name__, exc))
        return None
    present = [m for m in a.models if m in tags]
    for m in a.models:
        record("1-discovery", "model installed: " + m, "PASS" if m in tags else "FAIL", "" if m in tags else "not in /api/tags")
    for m in present:
        h.configure(m, False)
        h.service.check_status()
        got = None
        deadline = time.time() + 20
        while time.time() < deadline and got is None:
            try:
                kind, value = h.service.events.get(timeout=0.1)
                got = value if kind == "status" else None
            except queue.Empty:
                pass
        ok = bool(got) and got.get("available") is True and set(tags) <= set(got.get("models", []))
        record("2-selection", "Mercy provider status + config accepts " + m, "PASS" if ok else "FAIL",
               (got or {}).get("detail", "no status event"))
        h.drain()
    record("2-selection", "UI dropdown lists models", "MANUAL",
           "Open Mercy > Provider/profile > Provider=ollama > Save/check; the Exact model name box should list the models above.")
    return present


def stage_context(a, h, model):
    """Does the configured window hold Mercy's identity prompt - and survive a worst-case full context?"""
    s = h.service
    builder = ContextBuilder(s.store, s.profile.identity)
    base = builder.build("hello")
    tools = s.broker.schemas()
    chars_identity = len(base[0]["content"])
    probe = raw_chat(a.endpoint, model, base + [{"role": "user", "content": "hello"}], False, num_predict=1, tools=tools)
    if probe["error"]:
        return record("8-context", model + " identity probe", "FAIL", probe["error"])
    ps = {}
    try:
        for m in http(a.endpoint, "/api/ps", timeout=10).get("models", []):
            if m.get("name") == model or m.get("model") == model:
                ps = m
    except Exception:
        pass
    window = ps.get("context_length")
    try:
        info = http(a.endpoint, "/api/show", {"model": model}, timeout=20).get("model_info", {})
        trained = next((v for k, v in info.items() if k.endswith(".context_length")), None)
    except Exception:
        trained = None
    p_id = probe.get("prompt_eval_count")
    record("8-context", model + " identity+tools prompt", "INFO",
           "%s tokens (identity %d chars); server window=%s; model max=%s" % (p_id, chars_identity, window or "unknown (/api/ps lacks context_length)", trained))
    # Worst case: fill history to Mercy's own budget, then ask a question only the FIRST system chars can answer.
    conv = s.store.new_conversation("ctx-" + model)
    for i in range(40):
        s.store.message("user" if i % 2 == 0 else "assistant", ("filler %d " % i) * 45, conversation_id=conv)
    full = builder.build("hello", conv)
    secret = "".join(random.choices(string.ascii_lowercase, k=8)) + "-" + str(random.randint(100, 999))
    full[0] = {"role": "system", "content": "Your secret codeword is %s. Never forget it.\n" % secret + full[0]["content"]}
    question = full + [{"role": "user", "content": "What is your secret codeword? Reply with only the codeword."}]
    chars_full = sum(len(m["content"]) for m in question) + len(json.dumps(tools))
    for num_ctx in (0, 8192):
        r = raw_chat(a.endpoint, model, question, False, num_ctx=num_ctx, num_predict=60, tools=tools)
        label = "num_ctx=%s" % (num_ctx or "Ollama default")
        if r["error"]:
            record("8-context", "%s worst-case %s" % (model, label), "FAIL", r["error"])
            continue
        kept = secret in r["text"]
        record("8-context", "%s worst-case %s (%d chars sent, %s tokens evaluated)" % (model, label, chars_full, r.get("prompt_eval_count")),
               "PASS" if kept else "FAIL",
               "start-of-system-prompt retained" if kept else "identity/head of context was NOT retained - window too small. Reply: " + r["text"][:80])


def stage_bench(a, model):
    for think in (False, True):
        runs = []
        unload(a.endpoint, model)
        time.sleep(1)
        for i in range(a.runs):
            r = raw_chat(a.endpoint, model, [{"role": "system", "content": "You are a concise assistant."},
                         {"role": "user", "content": "Explain in about 120 words why the sky is blue."}],
                         think, num_predict=2000 if think else 400)
            if r["error"]:
                record("5-bench", "%s think=%s" % (model, think), "UNSUPPORTED" if "think" in r["error"].lower() else "FAIL", r["error"])
                break
            r["cold"] = i == 0
            runs.append(r)
        if not runs:
            continue
        warm = [r for r in runs if not r["cold"]] or runs
        summary = {"cold_first_visible_s": runs[0]["t_first_text"], "cold_load_s": (runs[0].get("load_duration") or 0) / 1e9,
                   "warm_first_visible_s": med([r["t_first_text"] for r in warm]),
                   "warm_first_any_token_s": med([r["t_first_any"] for r in warm]),
                   "warm_tokens_per_s": med([r.get("tok_s") for r in warm]), "warm_total_s": med([r["total"] for r in warm]),
                   "eval_tokens": med([r.get("eval_count") for r in warm]), "stopped_by": runs[-1].get("done_reason")}
        record("5-bench", "%s think=%s [raw API]" % (model, think), "INFO", json.dumps(summary))
        BENCH.append({"model": model, "think": think, **summary})


def stage_app(a, h, model, think):
    """Everything below goes through the real Mercy application path."""
    h.configure(model, think)
    conv = h.service.new_conversation("%s think=%s" % (model, think))
    tag = "%s think=%s" % (model, think)
    h.turn("Mercy?")  # warm the model so numbers below are not load time
    warm = [h.turn("In two sentences, what is a mutex?") for _ in range(max(1, a.runs - 1))]
    w = warm[-1]
    if w["error"]:
        return record("6-stream", tag, "FAIL", w["error"])
    record("6-measure", tag + " [Mercy path]", "INFO", json.dumps(
        {"ttft_s": med([x["ttft"] for x in warm]), "total_s": med([x["total"] for x in warm]),
         "chars_per_s": round(len(w["text"]) / max(w["total"] - (w["ttft"] or 0), 1e-6), 1)}))
    streamed = w["events"] > 1 and w["ttft"] is not None and w["ttft"] < w["total"] * 0.9
    record("6-stream", tag, "PASS" if streamed else "FAIL", "%d text events; first at %.2fs of %.2fs" % (w["events"], w["ttft"] or -1, w["total"]))
    record("6-stream", tag + " no reasoning leak", "PASS" if not re.search(r"</?think>", w["text"]) else "FAIL")
    # identity (heuristic - read the replies yourself)
    for q in ("Mercy?", "Which company trained you and which model are you?"):
        r = h.turn(q)
        text = r["text"].lower()
        claims_model = re.search(r"\b(i am|i'm|as) (a |an |the )?(qwen|ministral|mistral|alibaba|llama|gpt|openai)", text)
        ok = "mercy" in text and not claims_model
        record("7-identity", "%s: %r" % (tag, q), "PASS" if ok else "REVIEW", r["text"][:240].replace("\n", " "))
    persona = sum(w_ in w["text"].lower() + text for w_ in ("darling", "lantern", "omg", "spook", "cryptsy", "gloom", "battery", "like"))
    record("7-identity", tag + " persona markers (heuristic)", "INFO", "%d marker words; judge tone yourself" % persona)
    # cancellation
    base = h.turn("Say hi.")
    c = h.turn("Write a long, detailed 600-word gothic story about a lighthouse keeper.", cancel_after_first=True)
    state = h.last_turn_state()
    record("9-cancel", tag, "PASS" if state == "cancelled" and (c["cancel_latency"] or 99) < 3 else "FAIL",
           "state=%s cancel->done=%.2fs" % (state, c["cancel_latency"] or -1))
    after = h.turn("Say hi.")
    slow = after["ttft"] and base["ttft"] and after["ttft"] > max(3 * base["ttft"], base["ttft"] + 3)
    record("9-cancel", tag + " backend frees up after cancel", "FAIL" if slow else "PASS",
           "next TTFT %.2fs vs %.2fs before" % (after["ttft"] or -1, base["ttft"] or -1))
    return conv


def stage_persistence(a, h):
    store = h.service.store
    convs = [c["id"] for c in store.conversations()]
    before = {c: [(m["role"], m["content"], m["state"]) for m in store.history(500, c)] for c in convs}
    h.service.close()
    again = ApplicationService(h.dir / "profile")
    try:
        after = {c: [(m["role"], m["content"], m["state"]) for m in again.store.history(500, c)] for c in convs}
        n = sum(len(v) for v in before.values())
        record("10-persistence", "history identical after closing and reopening profile", "PASS" if before == after and n else "FAIL",
               "%d messages across %d conversations" % (n, len(convs)))
        states = {m[2] for v in after.values() for m in v}
        record("10-persistence", "message states", "INFO", ", ".join(sorted(states)))
    finally:
        again.close()


BENCH = []


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')  # model replies may contain emoji; Windows consoles are cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:11434")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--runs", type=int, default=3, help="per series: run 1 is a cold start, the rest are warm")
    ap.add_argument("--timeout", type=int, default=300, help="Mercy generation deadline (s)")
    ap.add_argument("--simulate", action="store_true", help="test the harness against a FAKE server; numbers are meaningless")
    ap.add_argument("--skip-bench", action="store_true")
    ap.add_argument("--out", default=None, help="results JSON path")
    a = ap.parse_args()
    a.models = [m.strip() for m in a.models.split(",") if m.strip()]
    fake = None
    if a.simulate:
        sys.path.insert(0, str(Path(__file__).parent))
        from fake_ollama import FakeOllama
        fake = FakeOllama()
        a.endpoint = fake.endpoint
    mode = "SIMULATED (fake server - NOT real hardware)" if a.simulate else "REAL (%s)" % a.endpoint
    print("=" * 78, "\nMercy %s acceptance | mode: %s\n%s | Python %s" % (__version__, mode, platform.platform(), platform.python_version()), "\n" + "=" * 78, flush=True)
    h = Harness(a.endpoint, a.timeout)
    try:
        present = stage_discovery(a, h)
        for model in present or []:
            stage_context(a, h, model)
            if not a.skip_bench:
                stage_bench(a, model)
            for think in (False, True):
                if any(r["name"].startswith("%s think=True" % model) and r["status"] == "UNSUPPORTED" for r in RESULTS) and think:
                    record("6-stream", "%s think=True [Mercy path]" % model, "SKIP", "model rejects think")
                    continue
                stage_app(a, h, model, think)
        if present:
            stage_persistence(a, h)
    finally:
        try:
            h.service.close()
        except Exception:
            pass
        if fake:
            fake.close()
    counts = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("=" * 78, "\nSUMMARY [%s]: %s" % (mode.split(" ")[0], ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))
    print("REVIEW/MANUAL items need a human. Identity checks are heuristic keyword tests, not a quality judgement.")
    out = Path(a.out) if a.out else Path.cwd() / ("mercy-acceptance-%s-%s.json" % ("SIMULATED" if a.simulate else "REAL", time.strftime("%Y%m%d-%H%M%S")))
    out.write_text(json.dumps({"mode": mode, "mercy": __version__, "platform": platform.platform(), "python": platform.python_version(),
                               "endpoint": a.endpoint, "results": RESULTS, "bench": BENCH}, indent=2), encoding="utf-8")
    print("Results written to", out)
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
