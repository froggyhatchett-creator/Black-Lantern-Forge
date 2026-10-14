"""DesktopSession: the window's state and the user's intents, without any widgets.

GUI event -> DesktopSession intent -> ForgeController -> registry pipeline
         -> result -> ShellState -> ViewModel -> widgets

The session owns only GUI state (ShellState): selections, explicit versions,
seed text, view, the current result, the record path, status. It never touches
generator or registry state.

Collaborators are injected so everything here runs headless in tests:
  dialogs      file pickers and error boxes (Tk in the app, fakes in tests)
  runner       runs slow work (generate + render): background thread in the app,
               synchronous in tests
  seed_source  the Random Seed button's entropy (forge_desktop.entropy in the app)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from forge_desktop.controller import AssetOptions, AssetResult, ExportChoice, ForgeActionError, ForgeController

log = logging.getLogger("forge_desktop")


class Dialogs(Protocol):
    def open_record(self) -> Path | None: ...
    def save_record(self, suggested_name: str) -> Path | None: ...
    def export_file(self, suggested_name: str, extension: str, description: str) -> Path | None: ...
    def save_preview(self, suggested_name: str) -> Path | None: ...
    def error(self, title: str, message: str) -> None: ...


class Runner(Protocol):
    def run(self, task: Callable[[], object], on_success: Callable[[object], None],
            on_error: Callable[[BaseException], None]) -> None: ...


class SyncRunner:
    """Runs tasks immediately on the calling thread (tests, scripts)."""

    def run(self, task, on_success, on_error):
        try:
            value = task()
        except Exception as exc:  # handed to the session's error reporting, never swallowed
            on_error(exc)
            return
        on_success(value)


@dataclass
class ShellState:
    asset_type: str | None = None
    seed_text: str = ""
    generator_version: int | None = None
    presentation_version: int | None = None
    preview_version: int | None = None
    view: str | None = None
    export_key: str | None = None
    current: AssetResult | None = None
    preview_base: object | None = None              # PreviewSettings whose size/ssaa the current asset uses
    previews: dict = field(default_factory=dict)    # view -> PreviewImage, for the current asset only
    preview_note: str | None = None
    record_path: Path | None = None
    record_content: str | None = None
    last_export: tuple[str, tuple[Path, ...]] | None = None   # (export key, written paths), current asset only
    status: str = "Ready"
    status_kind: str = "info"                       # info | busy | error
    busy: bool = False


@dataclass(frozen=True)
class ViewModel:
    title: str
    asset_types: tuple[str, ...]
    asset_type: str | None
    generator_versions: tuple[int, ...]
    generator_version: int | None
    presentation_versions: tuple[int, ...]
    presentation_version: int | None
    preview_versions: tuple[int, ...]
    preview_version: int | None
    views: tuple[str, ...]
    view: str | None
    exporters: tuple[ExportChoice, ...]
    export_key: str | None
    seed_text: str
    details: tuple[tuple[str, str], ...]
    preview: object | None
    status: str
    status_kind: str
    busy: bool
    can_generate: bool
    can_save_record: bool
    can_export: bool
    can_save_preview: bool
    can_load: bool
    export_action: str = "Export…"                  # "Export Engine Package…" for a contract exporter


def _only(values: tuple[int, ...]) -> int | None:
    """Preselect a version only when exactly one exists. Never 'the newest'."""
    return values[0] if len(values) == 1 else None


def _as_version(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ForgeActionError("Invalid version", f"{value!r} is not a version number")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text.isdigit() or not text.isascii():
        raise ForgeActionError("Invalid version", f"{value!r} is not a version number")
    return int(text)


class DesktopSession:
    def __init__(self, controller: ForgeController, dialogs: Dialogs, runner: Runner,
                 seed_source: Callable[[], int], on_change: Callable[[], None] | None = None):
        self.controller = controller
        self.dialogs = dialogs
        self.runner = runner
        self.seed_source = seed_source
        self.on_change = on_change or (lambda: None)
        self.state = ShellState()
        self._options: AssetOptions | None = None
        types = controller.asset_types()
        if len(types) == 1:
            self._apply_asset_type(types[0])
        # Launching never generates. Generation happens only when the user asks.

    # ------------------------------------------------------------ helpers

    def _notify(self):
        self.on_change()

    def _status(self, text: str, kind: str = "info"):
        self.state.status, self.state.status_kind = text, kind

    def _report(self, exc: BaseException, fallback_title: str):
        if isinstance(exc, ForgeActionError):
            title, message = exc.title, exc.message
        else:
            log.error("%s: unexpected error", fallback_title, exc_info=(type(exc), exc, exc.__traceback__))
            title = f"{fallback_title}: unexpected error"
            message = f"{type(exc).__name__}: {exc}\n\nDetails were written to the log."
        self._status(f"Error: {title}", "error")
        self._notify()                 # show the error state before the (modal) dialog opens
        self.dialogs.error(title, message)

    def _guard(self, fallback_title: str, fn):
        try:
            fn()
        except Exception as exc:
            self._report(exc, fallback_title)
        self._notify()

    def _apply_asset_type(self, name: str):
        opts = self.controller.options(name)
        s = self.state
        self._options = opts
        s.asset_type = name
        s.generator_version = _only(opts.generator_versions)
        s.presentation_version = _only(opts.presentation_versions)
        s.preview_version = _only(self.controller.preview_versions(name, s.presentation_version))
        s.view = s.view if s.view in opts.views else (opts.views[0] if opts.views else None)
        s.export_key = s.export_key if opts.exporter(s.export_key or "") else _only_key(opts.exporters)

    def _require(self, value, title: str, message: str):
        if value is None:
            raise ForgeActionError(title, message)
        return value

    # ------------------------------------------------------------ selection intents

    def select_asset_type(self, name: str):
        self._guard("Select asset type", lambda: self._apply_asset_type(name))

    def set_seed_text(self, text: str):
        self.state.seed_text = text

    def randomize_seed(self):
        def act():
            self.state.seed_text = str(self.seed_source())
            self._status(f"Random seed {self.state.seed_text} chosen. Press Generate to use it.")
        self._guard("Random seed", act)

    def select_generator_version(self, value):
        def act():
            v = _as_version(value)
            if v is not None and v not in self._options.generator_versions:
                raise ForgeActionError("Unsupported generator version", f"{v} is not registered")
            self.state.generator_version = v
        self._guard("Select generator version", act)

    def select_presentation_version(self, value):
        def act():
            v = _as_version(value)
            if v is not None and v not in self._options.presentation_versions:
                raise ForgeActionError("Unsupported presentation version", f"{v} is not registered")
            self.state.presentation_version = v
            versions = self.controller.preview_versions(self.state.asset_type, v)
            if self.state.preview_version not in versions:
                self.state.preview_version = _only(versions)
        self._guard("Select presentation version", act)

    def select_preview_version(self, value):
        def act():
            v = _as_version(value)
            allowed = self.controller.preview_versions(self.state.asset_type, self.state.presentation_version)
            if v is not None and v not in allowed:
                raise ForgeActionError("Unsupported preview version", f"{v} is not available")
            self.state.preview_version = v
        self._guard("Select preview version", act)

    def select_export(self, key: str | None):
        def act():
            if key is not None and self._options.exporter(key) is None:
                raise ForgeActionError("Export not available", f"{key!r} is not offered for {self.state.asset_type}")
            self.state.export_key = key
        self._guard("Select export format", act)

    def select_view(self, view: str):
        s = self.state
        if self._options is None or view not in self._options.views:
            self._report(ForgeActionError("Unknown view", f"{view!r} is not a preview view"), "Select view")
            self._notify()
            return
        s.view = view
        if s.current is None or s.busy:
            self._notify()
            return
        if view in s.previews:
            self._status(f"Showing {view} preview")
            self._notify()
            return
        current = s.current

        def task():
            settings = self.controller.preview_settings(s.preview_version, view, s.preview_base)
            return self.controller.render(current, settings)

        def done(image):
            s.busy = False
            if s.current is current:
                s.previews[image.settings.view] = image
                s.preview_note = None
            self._status(f"Preview rendered ({view})")
            self._notify()

        self._start(f"Rendering {view} preview…", task, done, "Preview")

    # ------------------------------------------------------------ actions

    def _start(self, busy_text: str, task, on_success, fallback_title: str):
        self.state.busy = True
        self._status(busy_text, "busy")
        self._notify()

        def on_error(exc):
            self.state.busy = False
            self._report(exc, fallback_title)
            self._notify()

        self.runner.run(task, on_success, on_error)

    def generate(self):
        s = self.state
        if s.busy:
            return
        try:
            asset_type = self._require(s.asset_type, "Choose an asset type", "Select an asset type first.")
            view = self._require(s.view, "No preview available", "This asset type has no preview views.")
            request = (asset_type, s.seed_text, s.generator_version, s.presentation_version, s.preview_version)
        except ForgeActionError as exc:
            self._report(exc, "Generate")
            self._notify()
            return

        def task():
            result = self.controller.generate(*request[:4])
            settings = self.controller.preview_settings(request[4], view)
            return result, settings, self.controller.render(result, settings)

        def done(value):
            result, settings, image = value
            s.busy = False
            s.current, s.preview_base, s.previews = result, settings, {view: image}
            s.preview_note, s.record_path, s.record_content = None, None, None
            s.last_export = None
            s.seed_text = str(result.seed)
            self._status(f"Generated {result.asset_type} seed {result.seed} · preview rendered ({view})")
            self._notify()

        self._start("Generating…", task, done, "Generate")

    def save_record(self):
        s = self.state
        if s.current is None or s.busy:
            return

        def act():
            r = s.current
            path = self.dialogs.save_record(f"{r.asset_type}_seed{r.seed}.json")
            if path is None:
                self._status("Save cancelled")
                return
            written, content = self.controller.save_record(r, path, s.previews.get(s.view))
            s.record_path, s.record_content = written, content
            self._status(f"Record saved: {written.name}")
        self._guard("Save record", act)

    def load_record(self):
        s = self.state
        if s.busy:
            return
        path = self.dialogs.open_record()
        if path is None:
            self._status("Load cancelled")
            self._notify()
            return

        def task():
            loaded = self.controller.load_record(path)
            view = loaded.preview.view if loaded.preview else (s.view or loaded.result.options.views[0])
            pv = loaded.preview.preview_version if loaded.preview else _only(
                self.controller.preview_versions(loaded.result.asset_type, loaded.result.versions.presentation_version))
            settings = self.controller.preview_settings(pv, view, loaded.preview)
            return loaded, settings, self.controller.render(loaded.result, settings)

        def done(value):
            loaded, settings, image = value
            r = loaded.result
            s.busy = False
            self._apply_asset_type(r.asset_type)
            s.seed_text = str(r.seed)
            s.generator_version = r.generator_version
            s.presentation_version = r.versions.presentation_version
            s.preview_version = settings.preview_version
            s.view = settings.view
            s.current, s.preview_base, s.previews = r, settings, {settings.view: image}
            s.record_path, s.record_content = loaded.path, loaded.record_content_sha256
            s.last_export = None
            if loaded.expected_pixels_sha256 is None:
                s.preview_note = None
            elif loaded.expected_pixels_sha256 == image.pixels_sha256:
                s.preview_note = "matches record"
            else:
                s.preview_note = f"DIFFERS from record {loaded.expected_pixels_sha256[:12]}…"
            self._status(f"Loaded {loaded.path.name}: {len(loaded.checks)} checks passed")
            self._notify()
            if s.preview_note and s.preview_note.startswith("DIFFERS"):
                self._report(ForgeActionError(
                    "Preview differs from record",
                    "The asset, materials and hashes verified, but the re-rendered preview pixels do not match "
                    "the pixel hash stored in the record. This can mean an unsupported platform."), "Load record")
                self._notify()

        self._start(f"Loading {Path(path).name}…", task, done, "Load record")

    def export(self):
        s = self.state
        if s.current is None or s.busy:
            return

        def act():
            r = s.current
            key = self._require(s.export_key, "Choose an export format", "Select an export format first.")
            choice = r.options.exporter(key)
            if choice is None:
                raise ForgeActionError("Export not available", f"{key!r} is not offered for {r.asset_type}")
            suggested = f"{r.asset_type}_seed{r.seed}_v{r.generator_version}_{choice.format_id}{choice.format_version}"
            path = self.dialogs.export_file(suggested + choice.extension, choice.extension, choice.label)
            if path is None:
                self._status("Export cancelled")
                return
            written = self.controller.export(r, key, path)
            s.last_export = (key, tuple(written))
            base = Path(path).parent

            def shown(p: Path) -> str:      # relative to the chosen location: "x.obj", "x.forgepkg/asset.glb"
                try:
                    return p.relative_to(base).as_posix()
                except ValueError:
                    return p.name
            extra = f" (+ {', '.join(shown(p) for p in written[1:])})" if len(written) > 1 else ""
            contract = f" · {choice.contract_label} validated" if choice.contract is not None else ""
            self._status(f"Export complete: {choice.key} → {shown(written[0])}{extra}{contract}")
        self._guard("Export", act)

    def save_preview(self):
        s = self.state
        image = s.previews.get(s.view) if s.current else None
        if image is None or s.busy:
            return

        def act():
            r = s.current
            path = self.dialogs.save_preview(f"{r.asset_type}_seed{r.seed}_{s.view}.png")
            if path is None:
                self._status("Save preview cancelled")
                return
            written = self.controller.save_preview(r, image, path, s.record_content)
            self._status(f"Preview saved: {written.name}")
        self._guard("Save preview", act)

    # ------------------------------------------------------------ view model

    def view_model(self) -> ViewModel:
        s, o = self.state, self._options
        image = s.previews.get(s.view) if s.current else None
        details = ()
        if s.current is not None:
            details = self.controller.details(s.current, export_key=s.export_key, image=image,
                                              record_path=s.record_path, record_content_sha256=s.record_content,
                                              preview_note=s.preview_note, last_export=s.last_export)
        title = "Black Lantern Forge"
        if s.current is not None:
            title += f" — {s.current.asset_type} · seed {s.current.seed}"
        preview_versions = (self.controller.preview_versions(s.asset_type, s.presentation_version)
                            if o is not None else ())
        idle = not s.busy
        return ViewModel(
            title=title,
            asset_types=self.controller.asset_types(), asset_type=s.asset_type,
            generator_versions=o.generator_versions if o else (), generator_version=s.generator_version,
            presentation_versions=o.presentation_versions if o else (), presentation_version=s.presentation_version,
            preview_versions=preview_versions, preview_version=s.preview_version,
            views=o.views if o else (), view=s.view,
            exporters=o.exporters if o else (), export_key=s.export_key,
            seed_text=s.seed_text, details=details, preview=image,
            status=s.status, status_kind=s.status_kind, busy=s.busy,
            can_generate=idle and o is not None,
            can_save_record=idle and s.current is not None,
            can_export=idle and s.current is not None and s.export_key is not None,
            can_save_preview=idle and image is not None,
            can_load=idle,
            export_action=next((c.action_label for c in (o.exporters if o else ()) if c.key == s.export_key),
                               "Export…"),
        )


def _only_key(exporters: tuple[ExportChoice, ...]) -> str | None:
    return exporters[0].key if len(exporters) == 1 else None
