"""A small Matplotlib-only editor for saved 1-D figure layout state."""
from __future__ import annotations

from copy import deepcopy
import importlib
import os
from pathlib import Path
import sys
from typing import Any

from .layout import apply_layout, capture_layout, write_layout


_NON_INTERACTIVE_BACKENDS = {"agg", "pdf", "svg", "ps", "template", "cairo"}


def _has_desktop_session(platform: str, environ: dict[str, str]) -> bool:
    """Check a display only where a display variable is meaningful.

    Windows uses the native desktop session and macOS normally uses Aqua; they
    do not advertise GUI availability through X11's ``DISPLAY`` variable.
    Linux/BSD desktop backends, on the other hand, must not be selected on a
    headless compute node merely because Tk happens to be installed.
    """
    if platform.startswith("win") or platform == "darwin":
        return True
    return bool(environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))


def _backend_candidates(platform: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Candidates in native preference order, with import-only capability probes."""
    standard = (("TkAgg", ("tkinter", "matplotlib.backends.backend_tkagg")),
                ("QtAgg", ("PyQt6", "matplotlib.backends.backend_qtagg")),
                ("QtAgg", ("PySide6", "matplotlib.backends.backend_qtagg")))
    if platform == "darwin":
        return (("MacOSX", ("matplotlib.backends.backend_macosx",)),) + standard
    # Tk is shipped with most official Windows Python installers, avoiding a
    # large Qt dependency for the small built-in editor.
    return standard


def _activate_backend(matplotlib, candidate: str, probes: tuple[str, ...]) -> bool:
    """Probe and select a backend without importing ``matplotlib.pyplot``."""
    try:
        for probe in probes:
            importlib.import_module(probe)
        matplotlib.use(candidate, force=True)
        return True
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError):
        return False


def _gui_error(platform: str, headless: bool) -> RuntimeError:
    if headless:
        if platform.startswith("win") or platform == "darwin":
            return RuntimeError(
                "`pypost edit` requires a graphical desktop session and an interactive Matplotlib backend. "
                "This process is configured for headless Agg output; unset MPLBACKEND and check Tk/Qt on a desktop."
            )
        return RuntimeError(
            "`pypost edit` requires a graphical desktop session on Linux (set DISPLAY or WAYLAND_DISPLAY). "
            "Use `pypost plot` for headless PDF/SVG/PNG export."
        )
    system = "Windows" if platform.startswith("win") else "macOS" if platform == "darwin" else "this system"
    return RuntimeError(
        f"No usable Matplotlib desktop backend is available on {system}. "
        "Check Tk with `python -m tkinter`, or install PyQt6/PySide6; then run `pypost edit` from a desktop session."
    )


def ensure_interactive_backend(*, platform: str | None = None, environ: dict[str, str] | None = None) -> str:
    """Select a usable native desktop backend before importing pyplot.

    Optional arguments exist solely for deterministic platform tests. Normal
    callers use ``sys.platform`` and ``os.environ``.
    """
    platform = platform or sys.platform
    environ = dict(os.environ if environ is None else environ)
    # A CI/user explicitly selecting Agg has declared a non-GUI process. Do
    # not turn that process into TkAgg merely because Windows has no DISPLAY
    # convention; doing so contaminates subsequent headless pyplot tests.
    if environ.get("MPLBACKEND", "").lower() in _NON_INTERACTIVE_BACKENDS:
        raise _gui_error(platform, headless=True)
    if not _has_desktop_session(platform, environ):
        raise _gui_error(platform, headless=True)
    import matplotlib
    backend = matplotlib.get_backend().lower()
    if backend not in _NON_INTERACTIVE_BACKENDS:
        # A configured interactive backend is not necessarily importable (for
        # example a copied matplotlibrc may name QtAgg without Qt installed).
        # Verify the common built-ins before accepting it.
        known = {candidate.lower(): (candidate, probes) for candidate, probes in _backend_candidates(platform)}
        # On macOS, a stale TkAgg setting must not leapfrog the native MacOSX
        # backend. The candidate order below is the documented preference.
        if platform == "darwin" and backend != "macosx":
            pass
        elif backend not in known:
            return backend
        else:
            candidate, probes = known[backend]
            if _activate_backend(matplotlib, candidate, probes):
                return candidate.lower()
        # Fall through and try the remaining supported native backends.
    for candidate, probes in _backend_candidates(platform):
        if _activate_backend(matplotlib, candidate, probes):
            return candidate.lower()
    raise _gui_error(platform, headless=False)


class FigureEditor:
    """Drag visual artists and persist only their stable, portable layout IDs."""
    def __init__(self, fig, panels: dict[str, Any], annotations: dict[str, Any], layout_path: str | Path,
                 default_layout: dict[str, Any]):
        self.fig, self.panels, self.annotations = fig, panels, annotations
        self.layout_path, self.default_layout = Path(layout_path), default_layout
        self._yaml_auto_layout = fig.get_layout_engine() is not None
        self._drag: tuple[str, Any, Any] | None = None
        self._connections: list[int] = []

    def save(self) -> Path:
        """Save current visual state to JSON without touching YAML or data."""
        target = write_layout(self.layout_path, capture_layout(self.fig, self.panels, self.annotations))
        self.fig.canvas.draw_idle()
        return target

    def restore_yaml_defaults(self) -> None:
        layout = deepcopy(self.default_layout)
        if self._yaml_auto_layout:
            # Auto layout and explicit Axes/margin adjustment are mutually
            # exclusive. Keep YAML's automatic engine for a true reset.
            self.fig.set_layout_engine("constrained")
            layout["figure"] = {}
            for state in layout["panels"].values(): state.pop("axes", None)
        apply_layout(self.fig, self.panels, self.annotations, layout)

    def set_margins(self, **margins: float) -> None:
        allowed = {"left", "right", "bottom", "top", "wspace", "hspace"}
        unknown = set(margins) - allowed
        if unknown: raise ValueError(f"Unsupported margin controls: {sorted(unknown)}")
        self.fig.set_layout_engine(None)
        self.fig.subplots_adjust(**{key: float(value) for key, value in margins.items()})
        self.fig.canvas.draw_idle()

    def move(self, stable_id: str, xy: tuple[float, float]) -> None:
        """Core movement method, testable without a desktop event loop."""
        panel_id, _, item = stable_id.partition(":")
        if panel_id == "annotation":
            if item not in self.annotations: raise KeyError(f"Unknown annotation ID: {item}")
            self.annotations[item].set_position(xy)
        elif panel_id in self.panels:
            ax = self.panels[panel_id]
            if item == "xlabel":
                ax.xaxis.set_label_coords(*xy); ax.xaxis.label._pypost_layout_position = xy
            elif item == "ylabel":
                ax.yaxis.set_label_coords(*xy); ax.yaxis.label._pypost_layout_position = xy
            elif item == "title":
                ax.title.set_position(xy); ax.title._pypost_layout_position = xy
            elif item == "legend":
                legend = ax.get_legend()
                if legend is None: raise KeyError(f"Panel {panel_id!r} has no legend")
                legend.set_bbox_to_anchor((xy[0], xy[1]), transform=ax.transAxes); legend._loc = 2
            else: raise KeyError(f"Unknown editable element: {stable_id}")
        else:
            raise KeyError(f"Unknown panel ID: {panel_id}")
        self.fig.canvas.draw_idle()

    def _candidates(self):
        for panel_id, ax in self.panels.items():
            yield f"{panel_id}:xlabel", ax.xaxis.label, ax
            yield f"{panel_id}:ylabel", ax.yaxis.label, ax
            yield f"{panel_id}:title", ax.title, ax
            legend = ax.get_legend()
            if legend is not None: yield f"{panel_id}:legend", legend, ax
        for annotation_id, artist in self.annotations.items():
            yield f"annotation:{annotation_id}", artist, self.panels[getattr(artist, "_pypost_annotation")["panel"]]

    def _press(self, event) -> None:
        if event.x is None or event.y is None: return
        renderer = self.fig.canvas.get_renderer()
        for stable_id, artist, ax in self._candidates():
            if artist.get_window_extent(renderer).contains(event.x, event.y):
                self._drag = (stable_id, artist, ax)
                return

    def _motion(self, event) -> None:
        if self._drag is None or event.x is None or event.y is None: return
        stable_id, _, ax = self._drag
        xy = tuple(float(v) for v in ax.transAxes.inverted().transform((event.x, event.y)))
        if stable_id.startswith("annotation:"):
            annotation = self.annotations[stable_id.split(":", 1)[1]]
            coords = getattr(annotation, "_pypost_annotation")["coords"]
            if coords == "data": xy = tuple(float(v) for v in ax.transData.inverted().transform((event.x, event.y)))
            elif coords == "figure": xy = tuple(float(v) for v in self.fig.transFigure.inverted().transform((event.x, event.y)))
        self.move(stable_id, xy)

    def _release(self, event) -> None:
        self._drag = None

    def _key(self, event) -> None:
        if event.key in {"ctrl+s", "cmd+s"}:
            print(f"Saved layout: {self.save()}")
        elif event.key in {"r", "R"}:
            self.restore_yaml_defaults()

    def connect(self) -> None:
        canvas = self.fig.canvas
        self._connections = [canvas.mpl_connect("button_press_event", self._press),
                             canvas.mpl_connect("motion_notify_event", self._motion),
                             canvas.mpl_connect("button_release_event", self._release),
                             canvas.mpl_connect("key_press_event", self._key)]

    def controls(self):
        """Open a small companion window with margin sliders and save/reset buttons."""
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, Slider
        control = plt.figure("pypost Figure Editor controls", figsize=(5.2, 2.6))
        values = capture_layout(self.fig, self.panels, self.annotations)["figure"]["margins"]
        sliders = {}
        for index, key in enumerate(("left", "right", "bottom", "top")):
            sliders[key] = Slider(control.add_axes((0.18, 0.80 - index * 0.16, 0.66, 0.05)), key, 0.0, 1.0, valinit=values[key])
        def apply(_): self.set_margins(**{key: slider.val for key, slider in sliders.items()})
        for slider in sliders.values(): slider.on_changed(apply)
        save = Button(control.add_axes((0.18, 0.06, 0.22, 0.10)), "Save (Ctrl+S)")
        reset = Button(control.add_axes((0.55, 0.06, 0.22, 0.10)), "Reset (R)")
        save.on_clicked(lambda _: print(f"Saved layout: {self.save()}"))
        reset.on_clicked(lambda _: self.restore_yaml_defaults())
        return control


def open_editor(fig, panels, annotations, layout_path, default_layout) -> FigureEditor:
    """Attach editor events, show the live final figure, and return its state."""
    editor = FigureEditor(fig, panels, annotations, layout_path, default_layout)
    editor.connect(); editor.controls()
    import matplotlib.pyplot as plt
    plt.show()
    return editor


def open_data_browser(fig) -> None:
    """Show Matplotlib's native pan/zoom toolbar without persisting view state.

    Final x/y ranges, layout, labels, legends, and annotations are numerical
    YAML parameters.  Deliberately do not connect the legacy draggable-layout
    handlers here: Home/Pan/Zoom are transient exploration only.
    """
    import matplotlib.pyplot as plt
    plt.show()
