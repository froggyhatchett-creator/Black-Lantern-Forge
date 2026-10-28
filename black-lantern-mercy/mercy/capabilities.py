from dataclasses import dataclass
from . import __version__


@dataclass
class Capability:
    name: str
    purpose: str
    permission: str
    implementation: object

    def validate(self, arguments):
        if not isinstance(arguments, dict) or arguments:
            raise ValueError("This capability accepts an empty object only.")

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.purpose,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}


class Broker:
    def __init__(self, store, authorize):
        self.store, self.authorize = store, authorize
        self.registry = {}
        self.turn_id = None
        self.check_control = lambda: None

    def register(self, capability):
        if capability.name in self.registry:
            raise ValueError("Duplicate capability")
        self.registry[capability.name] = capability

    def schemas(self):
        return [c.schema() for c in self.registry.values()]

    def execute(self, request):
        # These tools take no arguments. Never persist arbitrary rejected payloads:
        # they can contain secrets or huge attacker-controlled strings.
        record = {"capability": "<invalid>", "arguments": "<rejected/redacted>",
                  "authorization": "not_requested", "execution": "not_started"}
        if self.turn_id:
            record['turn_id'] = self.turn_id
        try:
            if not isinstance(request, dict) or set(request) - {'function', 'id', 'type'}:
                raise ValueError("Malformed tool request")
            fn = request.get('function')
            if not isinstance(fn, dict) or set(fn) != {'name', 'arguments'}:
                raise ValueError("Malformed function request")
            name = fn['name']
            if not isinstance(name, str) or name not in self.registry:
                raise ValueError("Unknown capability")
            record['capability'] = name
            capability = self.registry[name]
            capability.validate(fn['arguments'])
            record['arguments'] = {}
            # Commit an intent before prompting or executing. Failure prevents execution.
            intent = self.store.audit(record)
            record['intent_id'] = intent
            self.check_control()
            if self.authorize(capability, {}) is not True:
                record['authorization'] = 'denied'
                result = {"error": "Permission denied"}
            else:
                self.check_control()
                record['authorization'] = 'approved'
                record['execution'] = 'authorized'
                self.store.audit(record)
                result = capability.implementation()
                record['execution'] = 'succeeded'
        except Exception as exc:
            record['execution'] = 'failed'
            record['error'] = type(exc).__name__
            result = {"error": "Capability rejected or failed", "kind": type(exc).__name__}
        record['result'] = result
        self.store.audit(record)
        return result


def register_defaults(broker, platform):
    broker.register(Capability('application_version', 'Read Mercy application version', 'app.read_version', lambda: {"version": __version__}))
    broker.register(Capability('current_time', 'Read current local time', 'host.read_time', platform.current_time))
    broker.register(Capability('system_info', 'Read OS family and CPU architecture only', 'host.read_basic_info', platform.system_info))
