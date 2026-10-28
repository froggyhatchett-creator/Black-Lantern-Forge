"""Private subprocess transport. Factory names originate in trusted code, not models/config."""
import importlib
import json
import os
import sys
import threading


def main():
    def send(kind, value):
        print(json.dumps([kind, value]), flush=True)
    try:
        request = json.loads(sys.stdin.readline(1_000_001))
        def parent_liveness():
            # Parent exit closes the pipe, even if generation is blocked elsewhere.
            sys.stdin.read()
            os._exit(0)
        threading.Thread(target=parent_liveness, daemon=True).start()
        factory = getattr(importlib.import_module(request['module']), request['factory'])
        provider = factory(request['settings'])
        if request['operation'] == 'stream':
            for event in provider.stream(request['messages'], request['tools']):
                send('event', {'text': event.text, 'tool': event.tool})
        else:
            send('value', provider.status())
        send('done', None)
    except BaseException as exc:
        send('error', str(exc)[:500])


if __name__ == '__main__':
    main()
