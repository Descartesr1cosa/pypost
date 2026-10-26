"""Lightweight readers and plotting helpers for scientific/CFD data."""

from .data import Data1D, Data2D, Data3D, FieldInfo

__all__ = ["Data1D", "Data2D", "Data3D", "FieldInfo", "Plot1D", "Plot2D", "Plot3D"]


def __getattr__(name):
    """Keep data-only and editor CLI startup free to select a GUI backend."""
    if name in {"Plot1D", "Plot2D", "Plot3D"}:
        from . import plotting
        return getattr(plotting, name)
    raise AttributeError(name)
