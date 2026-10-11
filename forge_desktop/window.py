"""The Forge Desktop main window (Tk). The only module that imports tkinter.

The window is deliberately thin: it builds widgets, forwards user events to
DesktopSession, and redraws itself from session.view_model(). It holds no Forge
logic and never calls the core directly.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from forge_desktop.controller import ForgeController
from forge_desktop.entropy import random_seed
from forge_desktop.session import DesktopSession

# FIRST FACE palette: dark, high contrast, one warm accent. Text never relies on color alone.
BG = "#141518"
PANEL = "#1b1d21"
RAISED = "#24272c"
BORDER = "#33363d"
FG = "#ebe6da"
MUTED = "#a39e93"
ACCENT = "#d9a441"
ACCENT_ACTIVE = "#ecbb5c"
ERROR = "#ef8a78"
SELECT = "#4a3f26"

# Display-only downscale ratios (zoom, subsample). Saved PNGs and hashes are never scaled.
_FIT_RATIOS = ((1, 1), (3, 4), (2, 3), (1, 2), (1, 3), (1, 4))


def view_label(view: str) -> str:
    return view.replace("_", "-").capitalize()


def ppm_bytes(width: int, height: int, rgb: bytes) -> bytes:
    """Binary PPM (P6). Tk 8.6 and 9.0 both decode it natively: no image library needed."""
    return b"P6 %d %d 255\n" % (width, height) + rgb


def fit_ratio(width: int, height: int, avail_w: int, avail_h: int) -> tuple[int, int]:
    for zoom, sub in _FIT_RATIOS:
        if width * zoom <= avail_w * sub and height * zoom <= avail_h * sub:
            return zoom, sub
    return _FIT_RATIOS[-1]


class TkDialogs:
    """Native file dialogs and message boxes. Remembers the last folder for this run only."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self._last_dir: str | None = None

    def _path(self, chosen) -> Path | None:
        if not chosen:
            return None
        path = Path(chosen)
        self._last_dir = str(path.parent)
        return path

    def open_record(self):
        return self._path(filedialog.askopenfilename(
            parent=self.root, title="Load Forge asset record", initialdir=self._last_dir,
            filetypes=[("Forge asset record", "*.json"), ("All files", "*")]))

    def save_record(self, suggested_name):
        return self._path(filedialog.asksaveasfilename(
            parent=self.root, title="Save Forge asset record", initialdir=self._last_dir,
            initialfile=suggested_name, defaultextension=".json",
            filetypes=[("Forge asset record", "*.json")]))

    def export_file(self, suggested_name, extension, description):
        return self._path(filedialog.asksaveasfilename(
            parent=self.root, title=f"Export {description}", initialdir=self._last_dir,
            initialfile=suggested_name, defaultextension=extension,
            filetypes=[(description, f"*{extension}")]))

    def save_preview(self, suggested_name):
        return self._path(filedialog.asksaveasfilename(
            parent=self.root, title="Save preview PNG", initialdir=self._last_dir,
            initialfile=suggested_name, defaultextension=".png", filetypes=[("PNG image", "*.png")]))

    def error(self, title, message):
        messagebox.showerror(title, message, parent=self.root)


class TkRunner:
    """Runs slow work on a worker thread; callbacks always run on the Tk thread."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self._results: queue.Queue = queue.Queue()
        self._pending = 0

    def run(self, task, on_success, on_error):
        self._pending += 1

        def worker():
            try:
                self._results.put((on_success, task()))
            except Exception as exc:  # delivered to the session's error reporting on the Tk thread
                self._results.put((on_error, exc))

        threading.Thread(target=worker, name="forge-desktop-worker", daemon=True).start()
        if self._pending == 1:
            self.root.after(25, self._poll)

    @property
    def idle(self) -> bool:
        return self._pending == 0

    def _poll(self):
        try:
            alive = bool(self.root.winfo_exists())
        except tk.TclError:          # the application was destroyed while work was in flight
            alive = False
        if not alive:
            return
        while True:
            try:
                callback, value = self._results.get_nowait()
            except queue.Empty:
                break
            self._pending -= 1
            callback(value)
        if self._pending > 0:
            self.root.after(25, self._poll)


def apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=BG)
    style.configure(".", background=PANEL, foreground=FG, fieldbackground=RAISED, bordercolor=BORDER,
                    lightcolor=PANEL, darkcolor=PANEL, troughcolor=BG, focuscolor=ACCENT,
                    selectbackground=SELECT, selectforeground=FG, insertcolor=FG)
    style.configure("TFrame", background=PANEL)
    style.configure("Root.TFrame", background=BG)
    style.configure("TLabel", background=PANEL, foreground=FG)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Key.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Status.TLabel", background=BG, foreground=FG)
    style.configure("Error.TLabel", background=BG, foreground=ERROR, font=("TkDefaultFont", 10, "bold"))
    style.configure("Busy.TLabel", background=BG, foreground=ACCENT)
    style.configure("TLabelframe", background=PANEL, bordercolor=BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=PANEL, foreground=ACCENT)
    style.configure("TButton", background=RAISED, foreground=FG, bordercolor=BORDER, padding=(10, 5))
    style.map("TButton", background=[("disabled", PANEL), ("active", BORDER)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground=BG, bordercolor=ACCENT, padding=(12, 7),
                    font=("TkDefaultFont", 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", RAISED), ("active", ACCENT_ACTIVE)],
              foreground=[("disabled", MUTED)])
    style.configure("TEntry", fieldbackground=RAISED, foreground=FG, bordercolor=BORDER)
    style.map("TEntry", fieldbackground=[("readonly", PANEL)], bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=RAISED, foreground=FG, background=RAISED, arrowcolor=FG,
                    bordercolor=BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", RAISED), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT)])
    # Unselected: dark well with a visible ring. Selected: amber dot. Shape differs, not only color.
    style.configure("TRadiobutton", background=PANEL, foreground=FG, indicatorbackground=RAISED,
                    indicatorforeground=ACCENT, upperbordercolor=MUTED, lowerbordercolor=MUTED)
    style.map("TRadiobutton", indicatorbackground=[("pressed", BORDER), ("selected", RAISED)],
              indicatorforeground=[("selected", ACCENT), ("!selected", RAISED)],
              foreground=[("disabled", MUTED)], background=[("active", PANEL)])
    style.configure("Vertical.TScrollbar", background=RAISED, arrowcolor=FG, bordercolor=BORDER)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=RAISED, bordercolor=BORDER)
    for opt, value in (("background", RAISED), ("foreground", FG), ("selectBackground", SELECT),
                       ("selectForeground", FG)):
        root.option_add(f"*TCombobox*Listbox.{opt}", value)
    return style


class ForgeWindow:
    def __init__(self, root: tk.Tk, session: DesktopSession):
        self.root = root
        self.session = session
        self._photo = None           # keep a reference or Tk drops the image
        self._shown = (None, None)   # (preview image object, fit ratio) currently on screen
        self._details_shown = None
        self._export_keys: tuple[str, ...] = ()
        self._fit_job = None
        apply_theme(root)
        self._mono_font = ("TkFixedFont", 9)
        root.title("Black Lantern Forge")
        width = max(1060, min(1400, root.winfo_screenwidth() - 60))
        height = max(680, min(900, root.winfo_screenheight() - 80))
        root.geometry(f"{width}x{height}")
        self._window_height = height
        root.minsize(1060, 680)
        self._build_menu()
        self._build_layout()
        self._bind_keys()
        session.on_change = self.refresh
        root.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh()
        self.seed_entry.focus_set()

    def _on_destroy(self, event):
        if event.widget is self.root and self._fit_job is not None:
            self.root.after_cancel(self._fit_job)   # no callbacks into a destroyed window
            self._fit_job = None

    # ------------------------------------------------------------ construction

    def _build_menu(self):
        menu_opts = dict(tearoff=False, background=PANEL, foreground=FG, activebackground=SELECT,
                         activeforeground=FG, disabledforeground=MUTED)
        bar = tk.Menu(self.root, **menu_opts)
        self.file_menu = tk.Menu(bar, **menu_opts)
        self.file_menu.add_command(label="Load Record…", accelerator="Ctrl+O", command=self.session.load_record)
        self.file_menu.add_command(label="Save Record…", accelerator="Ctrl+S", command=self.session.save_record)
        self.export_menu = tk.Menu(self.file_menu, **menu_opts)
        self.file_menu.add_cascade(label="Export", menu=self.export_menu)
        self.file_menu.add_command(label="Save Preview PNG…", accelerator="Ctrl+P", command=self.session.save_preview)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.root.destroy)
        bar.add_cascade(label="File", menu=self.file_menu, underline=0)
        help_menu = tk.Menu(bar, **menu_opts)
        help_menu.add_command(label="About Forge Desktop", command=self._about)
        bar.add_cascade(label="Help", menu=help_menu, underline=0)
        self.root.configure(menu=bar)

    def _build_layout(self):
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=0)   # preview column sized from window height (see _build_preview)
        outer.columnconfigure(2, weight=1)
        outer.rowconfigure(0, weight=1)
        self._build_controls(outer).grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        self._build_preview(outer).grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self._build_details(outer).grid(row=0, column=2, sticky="nsew")
        self._build_actions(outer).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def _labeled(self, parent, row, text, widget, caption_var=None):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=(8, 2))
        widget.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
        if caption_var is not None:
            ttk.Label(parent, textvariable=caption_var, style="Muted.TLabel").grid(
                row=row + 2, column=0, columnspan=2, sticky="w")

    def _build_controls(self, parent):
        box = ttk.LabelFrame(parent, text="Controls", padding=12)
        box.columnconfigure(0, weight=1)
        self.asset_var = tk.StringVar()
        self.asset_combo = ttk.Combobox(box, textvariable=self.asset_var, state="readonly", width=24)
        self.asset_combo.bind("<<ComboboxSelected>>", lambda e: self.session.select_asset_type(self.asset_var.get()))
        self._labeled(box, 0, "Asset type", self.asset_combo)

        ttk.Label(box, text="Seed").grid(row=3, column=0, sticky="w", pady=(10, 2))
        seed_row = ttk.Frame(box)
        seed_row.grid(row=4, column=0, columnspan=2, sticky="ew")
        seed_row.columnconfigure(0, weight=1)
        self.seed_var = tk.StringVar()
        self.seed_entry = ttk.Entry(seed_row, textvariable=self.seed_var, width=20)
        self.seed_entry.grid(row=0, column=0, sticky="ew")
        self.seed_var.trace_add("write", lambda *_: self.session.set_seed_text(self.seed_var.get()))
        self.random_button = ttk.Button(seed_row, text="Random Seed", underline=0, command=self.session.randomize_seed)
        self.random_button.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(box, text="0 to 18446744073709551615", style="Muted.TLabel").grid(row=5, column=0, sticky="w")

        self.gen_var, self.gen_caption = tk.StringVar(), tk.StringVar()
        self.gen_combo = ttk.Combobox(box, textvariable=self.gen_var, state="readonly", width=12)
        self.gen_combo.bind("<<ComboboxSelected>>", lambda e: self.session.select_generator_version(self.gen_var.get()))
        self._labeled(box, 6, "Generator version", self.gen_combo, self.gen_caption)

        self.pres_var, self.pres_caption = tk.StringVar(), tk.StringVar()
        self.pres_combo = ttk.Combobox(box, textvariable=self.pres_var, state="readonly", width=12)
        self.pres_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.session.select_presentation_version(self.pres_var.get()))
        self._labeled(box, 9, "Presentation version", self.pres_combo, self.pres_caption)

        self.prev_var, self.prev_caption = tk.StringVar(), tk.StringVar()
        self.prev_combo = ttk.Combobox(box, textvariable=self.prev_var, state="readonly", width=12)
        self.prev_combo.bind("<<ComboboxSelected>>", lambda e: self.session.select_preview_version(self.prev_var.get()))
        self._labeled(box, 12, "Preview version", self.prev_combo, self.prev_caption)

        ttk.Label(box, text="Preview view").grid(row=15, column=0, sticky="w", pady=(10, 2))
        self.view_frame = ttk.Frame(box)
        self.view_frame.grid(row=16, column=0, columnspan=2, sticky="w")
        self.view_var = tk.StringVar()
        self.view_buttons: dict[str, ttk.Radiobutton] = {}

        self.export_var = tk.StringVar()
        self.export_combo = ttk.Combobox(box, textvariable=self.export_var, state="readonly", width=30)
        self.export_combo.bind("<<ComboboxSelected>>", self._on_export_selected)
        self._labeled(box, 17, "Export format", self.export_combo)

        self.generate_button = ttk.Button(box, text="Generate", style="Accent.TButton", underline=0,
                                          command=self.session.generate)
        self.generate_button.grid(row=20, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Label(box, text="Enter or Ctrl+G generates", style="Muted.TLabel").grid(row=21, column=0, sticky="w")
        return box

    def _build_preview(self, parent):
        box = ttk.LabelFrame(parent, text="Preview", padding=6)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        # Width that fits the largest display ratio the window height allows for a 1:2 preview.
        height = max(480, self._window_height - 150)   # minus menu, frame headers, caption, action bar
        zoom, sub = fit_ratio(480, 960, 10_000, height)
        self.canvas = tk.Canvas(box, background=BG, highlightthickness=0, width=480 * zoom // sub + 16,
                                height=height)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._schedule_fit)
        self.preview_caption = ttk.Label(box, style="Muted.TLabel", anchor="center")
        self.preview_caption.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        return box

    def _build_details(self, parent):
        box = ttk.LabelFrame(parent, text="Asset details", padding=8)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.details_canvas = tk.Canvas(box, background=PANEL, highlightthickness=0, width=420)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.details_canvas.yview)
        self.details_canvas.configure(yscrollcommand=scroll.set)
        self.details_canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.details_frame = ttk.Frame(self.details_canvas)
        self.details_frame.columnconfigure(1, weight=1)
        self._details_window = self.details_canvas.create_window(0, 0, window=self.details_frame, anchor="nw")
        self.details_frame.bind("<Configure>", lambda e: self.details_canvas.configure(
            scrollregion=self.details_canvas.bbox("all")))
        self.details_canvas.bind("<Configure>", lambda e: self.details_canvas.itemconfigure(
            self._details_window, width=e.width))
        return box

    def _build_actions(self, parent):
        bar = ttk.Frame(parent, style="Root.TFrame")
        self.save_button = ttk.Button(bar, text="Save Record…", underline=0, command=self.session.save_record)
        self.load_button = ttk.Button(bar, text="Load Record…", underline=0, command=self.session.load_record)
        self.export_button = ttk.Button(bar, text="Export…", underline=0, command=self.session.export)
        self.save_preview_button = ttk.Button(bar, text="Save Preview PNG…", underline=5,
                                              command=self.session.save_preview)
        for i, b in enumerate((self.save_button, self.load_button, self.export_button, self.save_preview_button)):
            b.grid(row=0, column=i, padx=(0, 8))
        bar.columnconfigure(4, weight=1)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=5, padx=(8, 8))
        self.progress.grid_remove()
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel", anchor="e")
        self.status_label.grid(row=0, column=6, sticky="e")
        return bar

    def _bind_keys(self):
        r = self.root
        r.bind_all("<Control-g>", lambda e: self.session.generate())
        r.bind_all("<Control-r>", lambda e: self.session.randomize_seed())
        r.bind_all("<Control-o>", lambda e: self.session.load_record())
        r.bind_all("<Control-s>", lambda e: self.session.save_record())
        r.bind_all("<Control-e>", lambda e: self.session.export())
        r.bind_all("<Control-p>", lambda e: self.session.save_preview())
        r.bind_all("<Control-q>", lambda e: self.root.destroy())
        self.seed_entry.bind("<Return>", lambda e: self.session.generate())
        for key, button in (("g", "generate_button"), ("r", "random_button"), ("s", "save_button"),
                            ("l", "load_button"), ("e", "export_button"), ("p", "save_preview_button")):
            r.bind_all(f"<Alt-{key}>", lambda e, b=button: getattr(self, b).invoke())

    # ------------------------------------------------------------ events

    def _on_export_selected(self, _event=None):
        index = self.export_combo.current()
        self.session.select_export(self._export_keys[index] if 0 <= index < len(self._export_keys) else None)

    def _export_via_menu(self, key):
        self.session.select_export(key)
        self.session.export()

    def _about(self):
        from forge import __version__
        messagebox.showinfo("About Forge Desktop",
                            f"Black Lantern Forge {__version__}\nForge Desktop (Step 2.75, FIRST FACE)\n\n"
                            "A desktop shell over the frozen, registry-driven Forge core.", parent=self.root)

    def _schedule_fit(self, _event=None):
        if self._fit_job is not None:
            self.root.after_cancel(self._fit_job)
        self._fit_job = self.root.after(120, self._refit)

    def _refit(self):
        self._fit_job = None
        self._shown = (None, None)
        self._draw_preview(self.session.view_model())

    # ------------------------------------------------------------ rendering the view model

    def refresh(self):
        vm = self.session.view_model()
        self.root.title(vm.title)
        self._set_combo(self.asset_combo, self.asset_var, vm.asset_types, vm.asset_type)
        if self.seed_var.get() != vm.seed_text:
            self.seed_var.set(vm.seed_text)
        self._set_combo(self.gen_combo, self.gen_var, vm.generator_versions, vm.generator_version)
        self._set_combo(self.pres_combo, self.pres_var, vm.presentation_versions, vm.presentation_version)
        self._set_combo(self.prev_combo, self.prev_var, vm.preview_versions, vm.preview_version)
        opts = self.session._options
        self.gen_caption.set(f"{opts.generator_id}" if opts else "")
        self.pres_caption.set(f"{opts.presentation_id}" if opts else "")
        self.prev_caption.set(f"{opts.preview_id}" if opts and opts.preview_id else "no preview capability")
        self._sync_views(vm)
        self._sync_exports(vm)
        idle = not vm.busy
        for widget, enabled in ((self.generate_button, vm.can_generate), (self.random_button, idle),
                                (self.save_button, vm.can_save_record), (self.load_button, vm.can_load),
                                (self.export_button, vm.can_export), (self.save_preview_button, vm.can_save_preview)):
            widget.state(["!disabled"] if enabled else ["disabled"])
        for combo in (self.asset_combo, self.gen_combo, self.pres_combo, self.prev_combo, self.export_combo):
            combo.configure(state="readonly" if idle else "disabled")
        self.file_menu.entryconfigure("Save Record…", state="normal" if vm.can_save_record else "disabled")
        self.file_menu.entryconfigure("Load Record…", state="normal" if vm.can_load else "disabled")
        self.file_menu.entryconfigure("Save Preview PNG…", state="normal" if vm.can_save_preview else "disabled")
        if self.export_button.cget("text") != vm.export_action:
            self.export_button.configure(text=vm.export_action)
        self._draw_preview(vm)
        self._draw_details(vm)
        self._draw_status(vm)

    def _set_combo(self, combo, var, values, selected):
        labels = tuple(str(v) for v in values)
        if tuple(combo.cget("values") or ()) != labels:
            combo.configure(values=labels)
        text = "" if selected is None else str(selected)
        if var.get() != text:
            var.set(text)

    def _sync_views(self, vm):
        if tuple(self.view_buttons) != vm.views:
            for b in self.view_buttons.values():
                b.destroy()
            self.view_buttons = {}
            for i, view in enumerate(vm.views):
                b = ttk.Radiobutton(self.view_frame, text=view_label(view), value=view, variable=self.view_var,
                                    command=lambda v=view: self.session.select_view(v))
                b.grid(row=0, column=i, padx=(0, 10))
                self.view_buttons[view] = b
        if self.view_var.get() != (vm.view or ""):
            self.view_var.set(vm.view or "")
        for b in self.view_buttons.values():
            b.state(["!disabled"] if not vm.busy else ["disabled"])

    def _sync_exports(self, vm):
        keys = tuple(c.key for c in vm.exporters)
        if keys != self._export_keys:
            self._export_keys = keys
            self.export_combo.configure(values=[c.label for c in vm.exporters])
            # Raw Tcl query: an empty menu answers "none" (Tk 8.6) or "" (Tk 9.0), and Python 3.10's
            # Menu.index() can't parse the latter.
            last = str(self.export_menu.tk.call(self.export_menu._w, "index", "end"))
            if last.isdigit():
                self.export_menu.delete(0, int(last))
            for c in vm.exporters:
                self.export_menu.add_command(label=f"{c.label}…", command=lambda k=c.key: self._export_via_menu(k))
        label = next((c.label for c in vm.exporters if c.key == vm.export_key),
                     "— choose a format —" if vm.exporters else "no exporters registered")
        if self.export_var.get() != label:
            self.export_var.set(label)
        state = "normal" if (not vm.busy and self.session.state.current is not None) else "disabled"
        for i in range(len(vm.exporters)):
            self.export_menu.entryconfigure(i, state=state)

    def _draw_preview(self, vm):
        image = vm.preview
        c = self.canvas
        avail_w, avail_h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        if image is None:
            c.delete("all")
            text = ("Working…" if vm.busy else
                    "No asset yet.\n\nEnter a seed and press Generate,\nor load a saved record.")
            c.create_text(avail_w // 2, avail_h // 2, fill=MUTED, justify="center", font=("TkDefaultFont", 11),
                          text=text)
            self._shown, self._photo = (None, None), None
            self.preview_caption.configure(text="")
            return
        ratio = fit_ratio(image.width, image.height, avail_w, avail_h)
        if self._shown != (image, ratio):
            photo = tk.PhotoImage(master=self.root, data=ppm_bytes(image.width, image.height, image.pixels),
                                  format="ppm")
            zoom, sub = ratio
            if (zoom, sub) != (1, 1):
                photo = photo.zoom(zoom).subsample(sub)
            c.delete("all")
            c.create_image(avail_w // 2, avail_h // 2, image=photo, anchor="center")
            self._photo, self._shown = photo, (image, ratio)
        scale = "" if ratio == (1, 1) else f" · shown at {ratio[0]}/{ratio[1]} size"
        s = image.settings
        self.preview_caption.configure(text=f"{view_label(s.view)} · {s.width}×{s.height}{scale}")

    def _draw_details(self, vm):
        if vm.details == self._details_shown:
            return
        self._details_shown = vm.details
        for child in self.details_frame.winfo_children():
            child.destroy()
        if not vm.details:
            ttk.Label(self.details_frame, text="Details appear after Generate or Load Record.",
                      style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return
        for row, (key, value) in enumerate(vm.details):
            ttk.Label(self.details_frame, text=key, style="Key.TLabel").grid(row=row, column=0, sticky="nw",
                                                                             padx=(2, 10), pady=1)
            mono = key.endswith("sha256") or key == "Parameters" or key == ""
            entry = ttk.Entry(self.details_frame, font=self._mono_font if mono else "TkDefaultFont")
            entry.insert(0, value)
            entry.configure(state="readonly")
            entry.grid(row=row, column=1, sticky="ew", pady=1)

    def _draw_status(self, vm):
        self.status_var.set(vm.status)
        style = {"error": "Error.TLabel", "busy": "Busy.TLabel"}.get(vm.status_kind, "Status.TLabel")
        self.status_label.configure(style=style)
        if vm.busy:
            self.progress.grid()
            self.progress.start(12)
            self.root.configure(cursor="watch")
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self.root.configure(cursor="")


def build_window(root: tk.Tk, controller: ForgeController | None = None, seed_source=random_seed,
                 dialogs=None, runner=None) -> ForgeWindow:
    """Wire the real app: Tk dialogs + threaded runner + the production registry (unless overridden)."""
    session = DesktopSession(controller or ForgeController(), dialogs or TkDialogs(root), runner or TkRunner(root),
                             seed_source)
    return ForgeWindow(root, session)
