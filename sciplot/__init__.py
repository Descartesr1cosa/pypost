"""Lightweight readers and plotting helpers for scientific/CFD data."""

from .data import Data1D, Data2D, Data3D, FieldInfo

__all__ = ["Data1D", "Data2D", "Data3D", "FieldInfo", "Plot1D", "Plot2D", "Plot3D",
           "save_dataset", "load_dataset", "inspect_dataset", "validate_dataset"]


def __getattr__(name):
    """Keep data-only and editor CLI startup free to select a GUI backend."""
    if name in {"Plot1D", "Plot2D", "Plot3D"}:
        from . import plotting
        return getattr(plotting, name)
    if name in {"save_dataset", "load_dataset", "inspect_dataset", "validate_dataset"}:
        from . import io
        return getattr(io, name)
    raise AttributeError(name)
