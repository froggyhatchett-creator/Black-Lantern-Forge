import json
from .providers import ProviderError


class MercyCore:
    def __init__(self, store, context, provider, broker):
        self.store, self.context = store, context
        self.provider, self.broker = provider, broker

    def chat(self, text, emit=lambda text: None, conversation_id=1, control=None):
        text = text.strip()
        if not text or len(text) > 4000:
            raise ValueError("Enter 1–4000 characters.")
        if control:
            control.check()
        turn = self.store.begin_turn(conversation_id, text, getattr(self.provider, 'model', 'unknown'))
        self.broker.turn_id = turn
        accumulated = ''
        try:
            messages = self.context.build(text, conversation_id)
            for round_number in range(4):
                if control:
                    control.check()
                calls, response = [], ''
                for event in self.provider.stream(messages, self.broker.schemas()):
                    if control:
                        control.check()
                    response += event.text
                    accumulated += event.text
                    if len(accumulated) > 24000:
                        raise ProviderError("Response exceeds v0.1 size limit.")
                    if event.text:
                        self.store.checkpoint(turn, accumulated)
                        emit(event.text)
                    if event.tool is not None:
                        calls.append(event.tool)
                        if len(calls) > 4:
                            self.store.audit({'event': 'tool_limit_rejected', 'turn_id': turn, 'execution': 'not_started'})
                            raise ProviderError("Too many tool requests in one response.")
                if not calls:
                    if not accumulated.strip():
                        raise ProviderError("Backend returned an empty response.")
                    if control:
                        control.check()
                    self.store.finish_turn(turn, accumulated)
                    return accumulated
                if round_number == 3:
                    self.store.audit({'event': 'tool_round_limit_rejected', 'turn_id': turn, 'execution': 'not_started'})
                    raise ProviderError("Tool round limit reached.")
                messages.append({"role": "assistant", "content": response, "tool_calls": calls})
                for call in calls:
                    if control:
                        control.check()
                    result = self.broker.execute(call)
                    name = call.get('function', {}).get('name', '<invalid>') if isinstance(call, dict) and isinstance(call.get('function'), dict) else '<invalid>'
                    messages.append({"role": "tool", "tool_name": str(name)[:80], "content": json.dumps(result)})
        except Exception as exc:
            self.store.finish_turn(turn, accumulated or '[No response received]', getattr(exc, 'turn_state', 'failed'), type(exc).__name__)
            raise
        finally:
            self.broker.turn_id = None
