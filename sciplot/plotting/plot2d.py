"""Irregular-grid 2-D plotting based on Matplotlib triangulation."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from ..data import Data2D
from ..utils.style import apply_style


class Plot2D:
    def __init__(self, figsize=(6.4, 4.8), style: str | None = None, dpi: int | None = None):
        if style:
            apply_style(style)
        self.fig, self.ax = plt.subplots(figsize=figsize, dpi=dpi)
        self._last = None

    @staticmethod
    def _scalar_data(data: Data2D, field: str, coordinate_transform=None):
        points, values, location = data.field(field)
        values = np.asarray(values)
        if values.ndim != 1:
            raise ValueError("contour plots require a scalar field")
        plotted_points = points if coordinate_transform is None else np.asarray(coordinate_transform(points))
        if plotted_points.shape != points.shape:
            raise ValueError("coordinate_transform must return an (N, 2) array")
        return mtri.Triangulation(plotted_points[:, 0], plotted_points[:, 1]), values, location

    def contourf(self, data: Data2D, field: str, levels=20, cmap="viridis", vmin=None,
                 vmax=None, colorbar: bool = True, colorbar_label: str | None = None,
                 coordinate_transform=None, **kwargs):
        tri, values, _ = self._scalar_data(data, field, coordinate_transform)
        result = self.ax.tricontourf(tri, values, levels=levels, cmap=cmap, vmin=vmin, vmax=vmax, **kwargs)
        self._last = result
        if colorbar:
            bar = self.fig.colorbar(result, ax=self.ax)
            if colorbar_label: bar.set_label(colorbar_label)
        return result

    def contour(self, data: Data2D, field: str, levels=10, colors=None, cmap=None,
                vmin=None, vmax=None, coordinate_transform=None, **kwargs):
        tri, values, _ = self._scalar_data(data, field, coordinate_transform)
        return self.ax.tricontour(tri, values, levels=levels, colors=colors, cmap=cmap,
                                  vmin=vmin, vmax=vmax, **kwargs)

    def line_sample(self, data: Data2D, field: str, start, end, n=200, **kwargs):
        distance, values = data.sample_line(field, start, end, n=n)
        return self.ax.plot(distance, values, **kwargs)[0]

    def set_axes(self, xlabel=None, ylabel=None, title=None, xlim=None, ylim=None,
                 xticks=None, yticks=None, equal: bool = True):
        if xlabel is not None: self.ax.set_xlabel(xlabel)
        if ylabel is not None: self.ax.set_ylabel(ylabel)
        if title is not None: self.ax.set_title(title)
        if xlim is not None: self.ax.set_xlim(xlim)
        if ylim is not None: self.ax.set_ylim(ylim)
        if xticks is not None: self.ax.set_xticks(xticks)
        if yticks is not None: self.ax.set_yticks(yticks)
        if equal: self.ax.set_aspect("equal", adjustable="box")
        return self

    def save(self, path: str | Path, dpi: int | None = None, **kwargs):
        self.fig.savefig(path, dpi=dpi, **kwargs)
        return Path(path)
