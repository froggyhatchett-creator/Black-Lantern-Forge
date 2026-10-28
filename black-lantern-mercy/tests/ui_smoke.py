"""Optional real Tk widget/worker smoke test; requires a desktop session.

Run from project root: python -m tests.ui_smoke --data-dir PATH
The supplied profile is disposable; never point this test at a real profile.
"""
import argparse
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch
from mercy.ui import Application


def settle(root, app, approval=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root.update()
        if app.permission_dialog is not None and approval is not None:
            (app.allow_button if approval else app.deny_button).invoke()
        if not app.busy and app.service.events.empty():
            break
        time.sleep(0.01)
    assert not app.busy, 'UI worker timed out'


def run(path):
    root = tk.Tk()
    app = Application(root, path)
    settle(root, app)
    app.entry.insert(0, 'Mercy?')
    app.send()
    settle(root, app)
    assert 'Lantern lit' in app.transcript.get('1.0', 'end')
    app.store.remember('The compiler project is named Lantern.')
    for approved in (False, True):
        app.entry.insert(0, '/time')
        app.send()
        settle(root, app, approved)
    assert 'denied' in str(app.store.audits())
    assert 'approved' in str(app.store.audits())
    app.link_note.set(True)
    with patch('mercy.ui.simpledialog.askstring', return_value='A note linked to the latest turn'):
        app.add_memory()
    linked = app.store.memories()[-1]
    assert linked['source_kind'] == 'conversation' and linked['source_ref']
    app.memory_list.selection_set(str(linked['id']))
    with patch('mercy.ui.messagebox.askyesno', return_value=True):
        app.delete_memory()
    assert all(m['id'] != linked['id'] for m in app.store.memories())
    with patch('mercy.ui.simpledialog.askstring', return_value='Second conversation'):
        app.new_session()
    assert 'Lantern lit' not in app.transcript.get('1.0', 'end')
    app.service.select_conversation(1)
    app.refresh()
    app.reload_history()
    app.entry.insert(0, '/time')
    app.send()
    deadline = time.monotonic() + 10
    while app.permission_dialog is None and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert app.permission_dialog is not None
    app.cancel_button.invoke()
    settle(root, app)
    assert app.store.turns()[-1]['state'] == 'cancelled'
    assert app.permission_dialog is None
    app.latest_audit()
    assert app.audit_filter.get() == app.store.turns()[-1]['id']
    app.close()
    root = tk.Tk()
    app = Application(root, path)
    settle(root, app)
    assert 'Lantern lit' in app.transcript.get('1.0', 'end')
    assert app.store.memories()[0]['content'].startswith('The compiler')
    app.close()
    print('PASS: Tk startup, streaming, permission buttons, memory provenance/deletion, session switching, cancel pending permission, audit filter, restart persistence')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    run(parser.parse_args().data_dir)
