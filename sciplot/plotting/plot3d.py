"""PyVista view helpers; geometry operations are delegated to VTK/PyVista."""
from __future__ import annotations
from pathlib import Path
from ctypes.util import find_library
import os
from ..data import Data3D


class Plot3D:
    def __init__(self, window_size=(1024, 768), background="white", off_screen=True):
        import pyvista as pv
        self.plotter = pv.Plotter(window_size=window_size, off_screen=off_screen)
        self.plotter.set_background(background)

    @staticmethod
    def offscreen_available() -> bool:
        """Conservative pre-flight check for a screenshot-capable VTK backend.

        A working X display or an installed EGL/OSMesa library is needed. This
        avoids invoking VTK rendering in minimal containers where it can abort
        in native code rather than raise a Python exception.
        """
        return bool(os.environ.get("DISPLAY") or find_library("EGL") or find_library("OSMesa"))

    @staticmethod
    def _mesh(data):
        return data.mesh if isinstance(data, Data3D) else data

    def mesh(self, data, color="black", opacity=1.0, **kwargs):
        return self.plotter.add_mesh(self._mesh(data), style="wireframe", color=color, opacity=opacity, **kwargs)

    def surface(self, data, field: str | None = None, cmap="viridis", clim=None, opacity=1.0, **kwargs):
        return self.plotter.add_mesh(self._mesh(data), scalars=field, cmap=cmap, clim=clim, opacity=opacity, **kwargs)

    def slice(self, data, origin, normal, field: str | None = None, cmap="viridis", clim=None, **kwargs):
        cut = self._mesh(data).slice(normal=normal, origin=origin)
        self.plotter.add_mesh(cut, scalars=field, cmap=cmap, clim=clim, **kwargs)
        return cut

    def slices(self, data, normal="x", n=3, field: str | None = None, cmap="viridis", clim=None, **kwargs):
        axis = {"x": 0, "y": 1, "z": 2}.get(normal.lower(), normal) if isinstance(normal, str) else normal
        cuts = self._mesh(data).slice_along_axis(n=n, axis=axis)
        self.plotter.add_mesh(cuts, scalars=field, cmap=cmap, clim=clim, **kwargs)
        return cuts

    def contour(self, data, field: str, isosurfaces=10, cmap="viridis", clim=None, opacity=1.0, **kwargs):
        iso = self._mesh(data).contour(isosurfaces=isosurfaces, scalars=field)
        self.plotter.add_mesh(iso, scalars=field, cmap=cmap, clim=clim, opacity=opacity, **kwargs)
        return iso

    def set_camera(self, position=None, focal_point=None, viewup=None):
        if position is not None: self.plotter.camera_position = position
        if focal_point is not None: self.plotter.camera.focal_point = focal_point
        if viewup is not None: self.plotter.camera.up = viewup
        return self

    def screenshot(self, path: str | Path, **kwargs):
        return self.plotter.screenshot(str(path), **kwargs)

    def save_vtk(self, data: Data3D, path: str | Path):
        data.save(path)

    def close(self):
        self.plotter.close()
