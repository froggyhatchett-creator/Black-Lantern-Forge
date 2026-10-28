import json
import math
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

DEFAULT = {'version': 2, 'provider': 'mock', 'model': '', 'endpoint': 'http://127.0.0.1:11434',
           'generation_timeout': 60, 'status_timeout': 8, 'conversation_id': 1, 'think': False}


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT):
        raise ValueError('Configuration contains unknown fields.')
    result = {**DEFAULT, **value}
    if result['version'] != 2 or type(result['version']) is not int:
        raise ValueError('Unsupported configuration version.')
    if result['provider'] not in ('mock', 'ollama'):
        raise ValueError('Choose a registered provider: mock or ollama.')
    if not isinstance(result['model'], str) or len(result['model']) > 120:
        raise ValueError('Model must be text of at most 120 characters.')
    result['model'] = result['model'].strip()
    if result['provider'] == 'ollama' and not result['model']:
        raise ValueError('Ollama needs an exact installed model name.')
    endpoint = result['endpoint']
    if not isinstance(endpoint, str):
        raise ValueError('Endpoint must be a loopback HTTP origin.')
    u = urlparse(endpoint)
    if u.scheme != 'http' or u.hostname not in ('localhost', '127.0.0.1', '::1') or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
        raise ValueError('Endpoint must be a loopback HTTP origin without credentials.')
    try:
        if u.port is not None and not 1 <= u.port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('Invalid endpoint port.') from None
    for key, low, high in [('generation_timeout', 1, 600), ('status_timeout', 1, 30)]:
        x = result[key]
        if type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high:
            raise ValueError(f'{key} must be between {low} and {high} seconds.')
    if type(result['think']) is not bool:
        raise ValueError('think must be true or false.')
    if type(result['conversation_id']) is not int or result['conversation_id'] < 1:
        raise ValueError('Invalid conversation ID.')
    return result


def load(path):
    if not path.exists():
        return dict(DEFAULT)
    if path.stat().st_size > 16384:
        raise ValueError('Configuration is too large.')
    return validate(json.loads(path.read_text(encoding='utf-8')))


def save(path, value):
    value = validate(value)
    temporary = Path(path).with_name(Path(path).name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
