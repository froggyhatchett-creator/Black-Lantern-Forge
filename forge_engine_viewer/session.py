"""ViewerSession: what the window shows, and when. Headless (no Tk), so it can be tested without a display.

Rule: nothing is rendered until a package has passed ingestion. open() runs the whole
validation flow first; frame() returns None while no validated package is loaded. A refused
package never replaces the current one.
"""

from __future__ import annotations

from typing import Callable

from forge_engine_viewer.errors import IngestionError
from forge_engine_viewer.ingest import IngestedPackage, ingest
from forge_engine_viewer.render import MODES, VIEWS, Camera, Frame, build_frame
from forge_engine_viewer.summary import detail_sections


class ViewerSession:
    def __init__(self, *, ingest_fn: Callable = ingest, frame_fn: Callable = build_frame):
        self._ingest, self._frame = ingest_fn, frame_fn
        self.package: IngestedPackage | None = None
        self.camera = Camera()
        self.mode = "render"
        self.show_sockets = False
        self.status = "No package loaded. Open a .forgepkg directory."
        self.status_kind = "info"           # info | ok | error
        self.last_error: IngestionError | None = None
        self.listeners: list[Callable[[], None]] = []

    def _changed(self) -> None:
        for listener in list(self.listeners):
            listener()

    # ---- package
    def open(self, path) -> bool:
        """Validate + ingest. On refusal the previous package (if any) stays, and nothing new is drawn."""
        try:
            pkg = self._ingest(path)
        except IngestionError as exc:
            self.last_error = exc
            self.status, self.status_kind = f"Refused [{exc.code}]: {exc.message}", "error"
            self._changed()
            return False
        self.package, self.last_error = pkg, None
        self.camera, self.mode, self.show_sockets = Camera(), "render", False
        self.status = (f"Valid: {pkg.asset['asset_type']} seed {pkg.asset['seed']} · contract v{pkg.contract_version} · "
                       f"{len(pkg.checks)} checks · {len(pkg.hashes_verified)} hashes verified")
        self.status_kind = "ok"
        self._changed()
        return True

    # ---- view state
    def set_view(self, name: str) -> None:
        if name not in VIEWS:
            raise ValueError(f"unknown view {name!r}; views: {list(VIEWS)}")
        self.camera = Camera.preset(name)
        self._changed()

    def orbit(self, d_azimuth: float, d_elevation: float) -> None:
        self.camera = self.camera.orbited(d_azimuth, d_elevation)
        self._changed()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; modes: {MODES}")
        self.mode = mode
        self._changed()

    def set_sockets(self, shown: bool) -> None:
        self.show_sockets = bool(shown)
        self._changed()

    # ---- output
    def frame(self, width: int, height: int) -> Frame | None:
        if self.package is None:
            return None
        return self._frame(self.package, width=width, height=height, camera=self.camera, mode=self.mode,
                           show_sockets=self.show_sockets)

    def details(self):
        return detail_sections(self.package) if self.package is not None else []
