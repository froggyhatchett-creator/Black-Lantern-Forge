"""Provider-neutral events; remote providers can implement the same contract."""
import json
from dataclasses import dataclass
from typing import Protocol, Iterator
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    pass


DEFAULT_NUM_CTX, MIN_NUM_CTX, MAX_NUM_CTX = 8192, 4096, 131072
CHARS_PER_TOKEN = 2.5  # deliberately pessimistic (typical English is ~4) so we refuse rather than silently truncate
REPLY_RESERVE_TOKENS = 512  # headroom a prompt must leave inside the window


def check_num_ctx(value):
    if type(value) is not int or not MIN_NUM_CTX <= value <= MAX_NUM_CTX:
        raise ValueError('num_ctx must be an integer between %d and %d tokens.' % (MIN_NUM_CTX, MAX_NUM_CTX))
    return value


def estimate_tokens(messages, tools):
    chars = sum(len(str(m.get('content', ''))) + len(json.dumps(m.get('tool_calls', ''))) for m in messages)
    return int((chars + len(json.dumps(tools or []))) / CHARS_PER_TOKEN)


@dataclass
class Event:
    text: str = ""
    tool: object = None


class Provider(Protocol):
    model: str
    def status(self) -> dict: ...
    def stream(self, messages: list, tools: list) -> Iterator[Event]: ...


class Lifecycle(Protocol):
    """Optional interface; core never assumes providers implement it."""
    def unload(self) -> None: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError("Backend redirects are forbidden.")


class OllamaProvider:
    def __init__(self, model, endpoint="http://127.0.0.1:11434", think=False, num_ctx=DEFAULT_NUM_CTX):
        u = urlparse(endpoint)
        if u.scheme != 'http' or u.hostname not in ('localhost', '127.0.0.1', '::1') or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
            raise ValueError("Ollama endpoint must be a loopback HTTP origin.")
        self.model, self.endpoint, self.think = model, endpoint.rstrip('/'), think is True
        self.num_ctx = check_num_ctx(num_ctx)  # always sent: an unset window lets Ollama pick the model maximum
        self.http = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None, timeout=120):
        data = None if payload is None else json.dumps(payload).encode()
        return self.http.open(Request(self.endpoint + path, data=data,
                                     headers={"Content-Type": "application/json"}), timeout=timeout)

    def status(self):
        try:
            with self.request('/api/tags', timeout=5) as response:
                models = [m['name'] for m in json.load(response)['models']]
            return {"available": self.model in models, "models": models,
                    "detail": "Ready" if self.model in models else "Selected model is not installed; select an exact name from models."}
        except Exception as exc:
            raise ProviderError("Ollama unavailable. Start Ollama and check the endpoint.") from exc

    def _open_chat(self, messages, tools):
        """Open the chat stream. Reasoning is requested off (or on) explicitly; a model that
        rejects the `think` field is retried once without it, since not all models accept it."""
        payload = {"model": self.model, "messages": messages, "tools": tools,
                   "stream": True, "keep_alive": "5m", "think": self.think}
        payload["options"] = {"num_ctx": self.num_ctx}
        try:
            return self.request('/api/chat', payload)
        except HTTPError as exc:
            detail = exc.read(2000).decode('utf-8', 'replace').lower()
            exc.close()
            if exc.code != 400 or 'think' not in detail:
                raise
        del payload['think']
        return self.request('/api/chat', payload)

    def stream(self, messages, tools):
        if estimate_tokens(messages, tools) > self.num_ctx - REPLY_RESERVE_TOKENS:
            raise ProviderError("Prompt would not fit the %d-token context window. Raise num_ctx or shorten the conversation; "
                                "nothing was sent." % self.num_ctx)
        try:
            with self._open_chat(messages, tools) as response:
                done = False
                for line in response:
                    if len(line) > 1_000_000:
                        raise ProviderError("Backend response chunk exceeds limit.")
                    item = json.loads(line)
                    if item.get('error'):
                        raise ProviderError(str(item['error'])[:300])
                    msg = item.get('message', {})
                    content = msg.get('content', '')
                    if not isinstance(content, str):
                        raise ProviderError("Invalid backend text.")
                    # msg['thinking'] is deliberately dropped: reasoning is never shown or stored.
                    if content:
                        yield Event(text=content)
                    for call in msg.get('tool_calls', []):
                        yield Event(tool=call)
                    if item.get('done'):
                        done = True
                        used = item.get('prompt_eval_count')
                        if type(used) is int and used >= self.num_ctx - 64:
                            raise ProviderError("The prompt filled the %d-token context window; the server truncated it. "
                                                "Raise num_ctx. This reply may have lost Mercy's identity." % self.num_ctx)
                        break
                if not done:
                    raise ProviderError("Backend disconnected before completion.")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Inference failed. Check Ollama, selected model and tool support.") from exc

    def unload(self):
        with self.request('/api/generate', {"model": self.model, "keep_alive": 0}) as response:
            response.read()


class MockProvider:
    model = "offline-demo"

    def status(self):
        return {"available": True, "models": [self.model], "detail": "Mock demo — no language model"}

    def stream(self, messages, tools):
        if messages[-1]['role'] == 'tool':
            yield Event(text="The capability returned: " + messages[-1]['content'])
        elif messages[-1]['content'].lower().strip() == '/time':
            yield Event(tool={"function": {"name": "current_time", "arguments": {}}})
        else:
            for word in "Here, darling. Lantern lit. Let's make something spookulous. [Offline demo response]".split(' '):
                yield Event(text=word + ' ')
