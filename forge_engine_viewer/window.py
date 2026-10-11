"""Tk window for the Forge Engine Viewer. The only module that imports tkinter.

Layout:
  +--------------------------------------------+----------------------+
  | Open package…   <package path>                                    |
  +--------------------------------------------+----------------------+
  |                                            | Package details      |
  |              render view (Canvas)          | (read-only, grouped) |
  |                                            |                      |
  +--------------------------------------------+----------------------+
  | ( ) Render ( ) Render + collision ( ) Collision only  [x] Sockets |
  | [Three-quarter] [Front] [Side]          drag in the view to orbit |
  +-------------------------------------------------------------------+
  | status: validation result or refusal                              |
  +-------------------------------------------------------------------+

The window draws whatever ViewerSession.frame() returns, and that is None until a
package has passed validation. The window never writes files.
"""

from __future__ import annotations

import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from forge_engine_viewer.render import MODE_LABELS, MODES, Line, Marker, Polygon, Text
from forge_engine_viewer.session import ViewerSession

VIEW_BUTTONS = (("three_quarter", "Three-quarter", "1"), ("front", "Front", "2"), ("side", "Side", "3"))
VIEW_NAMES = {"three_quarter": "three-quarter", "front": "front", "side": "side", "orbit": "orbit"}
STATUS_COLORS = {"info": "#333333", "ok": "#1d6b33", "error": "#a11d1d"}


class ViewerWindow:
    def __init__(self, root: tk.Tk, session: ViewerSession | None = None):
        self.root = root
        self.session = session or ViewerSession()
        self.session.listeners.append(self.refresh)
        self._drag = None
        self.frames_drawn = 0                    # for tests: how many frames reached the canvas
        root.title("Forge Engine Viewer")
        root.geometry("1180x780")
        root.minsize(820, 560)
        root.report_callback_exception = self._unexpected
        self._build()
        self.refresh()

    # ------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)

        top = ttk.Frame(r, padding=(8, 6))
        top.grid(row=0, column=0, sticky="ew")
        self.open_button = ttk.Button(top, text="Open package…", underline=0, command=self.choose_package)
        self.open_button.pack(side="left")
        self.path_var = tk.StringVar(value="no package")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", padx=10)

        body = ttk.Panedwindow(r, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=8)
        view_box = ttk.Frame(body)
        self.canvas = tk.Canvas(view_box, background="#1c1d21", highlightthickness=0, width=700, height=600)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        body.add(view_box, weight=3)

        side = ttk.Frame(body)
        ttk.Label(side, text="Package details", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self.details = tk.Text(side, width=58, wrap="word", relief="flat", borderwidth=0, padx=6, pady=4,
                               font="TkFixedFont")
        bar = ttk.Scrollbar(side, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.details.pack(side="left", fill="both", expand=True)
        self.details.tag_configure("section", font="TkHeadingFont", spacing1=8)
        self.details.tag_configure("key", foreground="#555555")
        self.details.configure(state="disabled")
        body.add(side, weight=2)

        controls = ttk.Frame(r, padding=(8, 6))
        controls.grid(row=2, column=0, sticky="ew")
        self.mode_var = tk.StringVar(value="render")
        self.mode_buttons = {}
        for mode in MODES:
            b = ttk.Radiobutton(controls, text=MODE_LABELS[mode], value=mode, variable=self.mode_var,
                                command=lambda m=mode: self.session.set_mode(m))
            b.pack(side="left", padx=(0, 8))
            self.mode_buttons[mode] = b
        self.sockets_var = tk.BooleanVar(value=False)
        self.sockets_check = ttk.Checkbutton(controls, text="Sockets", variable=self.sockets_var,
                                             command=lambda: self.session.set_sockets(self.sockets_var.get()))
        self.sockets_check.pack(side="left", padx=(8, 16))
        self.view_buttons = {}
        for name, label, _ in VIEW_BUTTONS:
            b = ttk.Button(controls, text=label, command=lambda n=name: self.session.set_view(n))
            b.pack(side="left", padx=(0, 4))
            self.view_buttons[name] = b
        ttk.Label(controls, text="drag in the view to orbit · 1/2/3 views · C collision · S sockets").pack(side="right")

        self.status_var = tk.StringVar()
        self.status = tk.Label(r, textvariable=self.status_var, anchor="w", padx=10, pady=4)
        self.status.grid(row=3, column=0, sticky="ew")

        r.bind("<Control-o>", lambda e: self.choose_package())
        for name, _, key in VIEW_BUTTONS:
            r.bind(f"<Key-{key}>", lambda e, n=name: self._if_loaded(lambda: self.session.set_view(n)))
        r.bind("<Key-c>", lambda e: self._if_loaded(self._cycle_mode))
        r.bind("<Key-s>", lambda e: self._if_loaded(lambda: self.session.set_sockets(not self.session.show_sockets)))

    # ------------------------------------------------------------ actions
    def _if_loaded(self, fn):
        if self.session.package is not None:
            fn()

    def _cycle_mode(self):
        self.session.set_mode(MODES[(MODES.index(self.session.mode) + 1) % len(MODES)])

    def choose_package(self):
        path = filedialog.askdirectory(parent=self.root, title="Open a .forgepkg package directory", mustexist=True)
        if path:
            self.open_package(path)

    def open_package(self, path) -> bool:
        ok = self.session.open(path)
        if ok:
            self.path_var.set(str(Path(path)))
        else:
            exc = self.session.last_error
            messagebox.showerror("Package refused", f"{exc.message}\n\n(code: {exc.code})", parent=self.root)
        return ok

    def _press(self, event):
        self._drag = (event.x, event.y)

    def _motion(self, event):
        if self._drag is None or self.session.package is None:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self._drag = (event.x, event.y)
        self.session.orbit(-dx * 0.5, dy * 0.5)

    def _unexpected(self, exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb, file=sys.stderr)
        self.session.status, self.session.status_kind = f"Unexpected error: {exc_type.__name__}: {exc}", "error"
        self.refresh()
        messagebox.showerror("Unexpected error", f"{exc_type.__name__}: {exc}\n\nDetails were written to the log.",
                             parent=self.root)

    # ------------------------------------------------------------ drawing
    def refresh(self):
        s = self.session
        loaded = s.package is not None
        state = ["!disabled"] if loaded else ["disabled"]
        for w in (*self.mode_buttons.values(), self.sockets_check, *self.view_buttons.values()):
            w.state(state)
        self.mode_var.set(s.mode)
        self.sockets_var.set(s.show_sockets)
        if loaded:
            self.root.title(f"Forge Engine Viewer — {s.package.asset['asset_type']} · seed {s.package.asset['seed']}")
        prefix = "Error: " if s.status_kind == "error" else ""
        self.status_var.set(prefix + s.status)
        self.status.configure(foreground=STATUS_COLORS[s.status_kind])
        self._fill_details()
        self.redraw()

    def _fill_details(self):
        t = self.details
        t.configure(state="normal")
        t.delete("1.0", "end")
        sections = self.session.details()
        if not sections:
            t.insert("end", "No package loaded.\n\nNothing is drawn until a package passes validation.")
        for title, rows in sections:
            t.insert("end", title + "\n", "section")
            for key, value in rows:
                t.insert("end", f"{key:<16} ", "key")
                t.insert("end", f"{value}\n")
        t.configure(state="disabled")

    def redraw(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        frame = self.session.frame(w, h)
        if frame is None:
            c.create_text(w / 2, h / 2, text="Open a .forgepkg package to inspect it.\n"
                                             "Nothing is drawn until the package passes validation.",
                          fill="#9a9ca3", justify="center")
            return
        self.frames_drawn += 1
        for item in frame.items:
            if isinstance(item, Polygon):
                c.create_polygon(*[v for p in item.points for v in p], fill=item.fill, outline=item.outline,
                                 tags=(item.layer, item.source))
            elif isinstance(item, Line):
                c.create_line(*item.a, *item.b, fill=item.fill, width=item.width, dash=item.dash or None,
                              tags=(item.layer,))
            elif isinstance(item, Marker):
                x, y = item.center
                c.create_oval(x - item.radius, y - item.radius, x + item.radius, y + item.radius, fill=item.fill,
                              outline="#000000", tags=(item.layer, "marker"))
                c.create_text(x + 10, y - 9, text=item.label, anchor="w", fill="#ffe08a", tags=(item.layer, "label"))
            elif isinstance(item, Text):
                c.create_text(*item.position, text=item.text, fill=item.fill, tags=(item.layer,))
        cam = frame.camera
        c.create_text(10, 10, anchor="nw", fill="#c8cad0", tags=("caption",),
                      text=f"{VIEW_NAMES.get(cam.name, cam.name)} · azimuth {cam.azimuth:.0f}° elevation {cam.elevation:.0f}° · "
                           f"{MODE_LABELS[frame.mode]}{' · sockets' if frame.show_sockets else ''} · "
                           f"{frame.stats['render_triangles']} render triangles drawn")


def run(path=None) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"forge-engine-viewer: no display available ({exc}). Use --validate-only or --dump-summary.",
              file=sys.stderr)
        return 1
    window = ViewerWindow(root)
    if path is not None:
        root.after(0, lambda: window.open_package(path))
    root.mainloop()
    return 0
