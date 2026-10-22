"""Small, explicit Matplotlib style presets."""
from contextlib import contextmanager
import matplotlib as mpl

STYLES = {
    "default": {"font.size": 11, "axes.labelsize": 12, "axes.titlesize": 13,
                "legend.fontsize": 10, "figure.dpi": 120, "savefig.bbox": "tight"},
    "paper": {"font.size": 9, "axes.labelsize": 10, "axes.titlesize": 11,
              "legend.fontsize": 8, "lines.linewidth": 1.2, "figure.dpi": 300,
              "savefig.bbox": "tight"},
}


def apply_style(name: str = "default") -> None:
    """Apply a bundled style globally."""
    if name not in STYLES:
        raise ValueError(f"Unknown style {name!r}; choose from {tuple(STYLES)}")
    mpl.rcParams.update(STYLES[name])


@contextmanager
def style_context(name: str = "default"):
    if name not in STYLES:
        raise ValueError(f"Unknown style {name!r}; choose from {tuple(STYLES)}")
    with mpl.rc_context(STYLES[name]):
        yield
