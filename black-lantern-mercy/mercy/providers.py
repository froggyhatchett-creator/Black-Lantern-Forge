"""Provider-neutral events; remote providers can implement the same contract."""
import json
from dataclasses import dataclass
from typing import Protocol, Iterator
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    pass


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
    def __init__(self, model, endpoint="http://127.0.0.1:11434"):
        u = urlparse(endpoint)
        if u.scheme != 'http' or u.hostname not in ('localhost', '127.0.0.1', '::1') or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
            raise ValueError("Ollama endpoint must be a loopback HTTP origin.")
        self.model, self.endpoint = model, endpoint.rstrip('/')
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

    def stream(self, messages, tools):
        try:
            with self.request('/api/chat', {"model": self.model, "messages": messages,
                                           "tools": tools, "stream": True, "keep_alive": "5m"}) as response:
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
                    if content:
                        yield Event(text=content)
                    for call in msg.get('tool_calls', []):
                        yield Event(tool=call)
                    if item.get('done'):
                        done = True
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
