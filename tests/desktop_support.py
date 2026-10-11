"""Fakes for the Step 2.75 desktop tests (not a test module). No tkinter needed."""

from __future__ import annotations

from pathlib import Path

from forge_desktop.controller import ForgeController
from forge_desktop.session import DesktopSession, SyncRunner

SMALL_PREVIEW = (96, 192, 1)   # matches step2_support.SMALL, so goldens apply


class FakeDialogs:
    """Scripted answers for file pickers; records every error shown."""

    def __init__(self, open_path=None, save_path=None, export_path=None, preview_path=None):
        self.open_path, self.save_path = open_path, save_path
        self.export_path, self.preview_path = export_path, preview_path
        self.errors: list[tuple[str, str]] = []
        self.asked: list[tuple] = []

    def open_record(self):
        self.asked.append(("open",))
        return None if self.open_path is None else Path(self.open_path)

    def save_record(self, suggested_name):
        self.asked.append(("save", suggested_name))
        return None if self.save_path is None else Path(self.save_path)

    def export_file(self, suggested_name, extension, description):
        self.asked.append(("export", suggested_name, extension, description))
        return None if self.export_path is None else Path(self.export_path)

    def save_preview(self, suggested_name):
        self.asked.append(("preview", suggested_name))
        return None if self.preview_path is None else Path(self.preview_path)

    def error(self, title, message):
        self.errors.append((title, message))


class DeferredRunner:
    """Queues tasks instead of running them, so tests can observe the busy state."""

    def __init__(self):
        self.queue = []

    def run(self, task, on_success, on_error):
        self.queue.append((task, on_success, on_error))

    def flush(self):
        while self.queue:
            task, ok, err = self.queue.pop(0)
            SyncRunner().run(task, ok, err)


def make_session(registry=None, dialogs=None, runner=None, seed_source=lambda: 4242, preview_size=SMALL_PREVIEW):
    controller = ForgeController(registry, preview_size=preview_size) if registry else \
        ForgeController(preview_size=preview_size)
    dialogs = dialogs or FakeDialogs()
    session = DesktopSession(controller, dialogs, runner or SyncRunner(), seed_source)
    if session.state.asset_type is None and "short_sword" in controller.asset_types():
        session.select_asset_type("short_sword")   # Step 5A: several families now; these tests use the short sword
    return session, dialogs
