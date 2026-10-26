"""Matplotlib plotting for :class:`sciplot.data.Data1D`."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.ticker import AutoMinorLocator, ScalarFormatter
from ..data import Data1D
from ..utils.style import style_values


class Plot1D:
    def __init__(self, figsize=(6.4, 4.2), style: str | None = None, dpi: int | None = None,
                 ax=None, size_unit: str = "in"):
        """Create a plot or wrap an existing Axes without global rcParam changes."""
        self.style = style_values(style)
        if size_unit not in {"in", "mm"}:
            raise ValueError("size_unit must be 'in' or 'mm'")
        if size_unit == "mm":
            figsize = tuple(float(value) / 25.4 for value in figsize)
        if ax is None:
            with mpl.rc_context(self.style):
                self.fig, self.ax = plt.subplots(figsize=figsize, dpi=dpi)
        else:
            self.ax, self.fig = ax, ax.figure
        self._apply_axes_style()

    def _apply_axes_style(self):
        width = self.style.get("axes.linewidth")
        if width is not None:
            for spine in self.ax.spines.values(): spine.set_linewidth(width)

    def _context(self):
        return mpl.rc_context(self.style)

    @staticmethod
    def transformed(values, scale: float = 1.0, offset: float = 0.0):
        return np.asarray(values) * float(scale) + float(offset)

    def line(self, data: Data1D, field: str, label: str | None = None,
             x_transform=None, y_transform=None, **kwargs):
        if field not in data.fields:
            raise KeyError(f"{field!r} is not in {list(data.fields)}")
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        with self._context(): return self.ax.plot(x, y, label=label, **kwargs)[0]

    def scatter(self, data: Data1D, field: str, label: str | None = None,
                x_transform=None, y_transform=None, **kwargs):
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        with self._context(): return self.ax.scatter(x, y, label=label, **kwargs)

    def errorbar(self, data: Data1D, field: str, yerr, label: str | None = None,
                 x_transform=None, y_transform=None, **kwargs):
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        with self._context(): return self.ax.errorbar(x, y, yerr=yerr, label=label, **kwargs)

    def band(self, data: Data1D, lower: str, upper: str, label: str | None = None,
             x_transform=None, y_transform=None, **kwargs):
        if lower not in data.fields or upper not in data.fields:
            raise KeyError(f"Band fields must be present: {lower!r}, {upper!r}")
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        convert = (lambda values: values) if y_transform is None else y_transform
        with self._context(): return self.ax.fill_between(x, convert(data.fields[lower]), convert(data.fields[upper]), label=label, **kwargs)

    def lines(self, datasets, field: str, labels=None, **kwargs):
        labels = labels or [None] * len(datasets)
        return [self.line(data, field, label=label, **kwargs) for data, label in zip(datasets, labels)]

    def set_axes(self, xlabel=None, ylabel=None, title=None, xlim=None, ylim=None,
                 xticks=None, yticks=None, equal: bool = False, legend: bool = False, legend_kwargs=None,
                 xscale="linear", yscale="linear", xscale_kwargs=None, yscale_kwargs=None,
                 tick_params=None, minor_ticks=False, scientific=None, xformatter=None, yformatter=None,
                 xlabelpad=None, ylabelpad=None):
        with self._context():
            if xlabel is not None: self.ax.set_xlabel(xlabel, labelpad=xlabelpad)
            if ylabel is not None: self.ax.set_ylabel(ylabel, labelpad=ylabelpad)
            if title is not None: self.ax.set_title(title)
        self.ax.set_xscale(xscale, **(xscale_kwargs or {})); self.ax.set_yscale(yscale, **(yscale_kwargs or {}))
        if xlim is not None: self.ax.set_xlim(xlim)
        if ylim is not None: self.ax.set_ylim(ylim)
        if xticks is not None: self.ax.set_xticks(xticks)
        if yticks is not None: self.ax.set_yticks(yticks)
        if minor_ticks:
            self.ax.xaxis.set_minor_locator(AutoMinorLocator() if xscale == "linear" else self.ax.xaxis.get_minor_locator())
            self.ax.yaxis.set_minor_locator(AutoMinorLocator() if yscale == "linear" else self.ax.yaxis.get_minor_locator())
        if tick_params: self.ax.tick_params(**tick_params)
        if scientific:
            limits = scientific.get("limits", (-3, 3)) if isinstance(scientific, dict) else (-3, 3)
            for axis in (self.ax.xaxis, self.ax.yaxis):
                formatter = ScalarFormatter(useMathText=True); formatter.set_powerlimits(tuple(limits)); axis.set_major_formatter(formatter)
        if xformatter is not None: self.ax.xaxis.set_major_formatter(xformatter)
        if yformatter is not None: self.ax.yaxis.set_major_formatter(yformatter)
        if equal: self.ax.set_aspect("equal", adjustable="box")
        if legend:
            with self._context(): self.ax.legend(**(legend_kwargs or {}))
        return self

    def grid(self, major=None, minor=None):
        if major: self.ax.grid(True, which="major", **(major if isinstance(major, dict) else {}))
        if minor: self.ax.grid(True, which="minor", **(minor if isinstance(minor, dict) else {}))
        return self

    def hline(self, y, **kwargs): return self.ax.axhline(y, **kwargs)
    def vline(self, x, **kwargs): return self.ax.axvline(x, **kwargs)
    def text(self, x, y, text, **kwargs): return self.ax.text(x, y, text, **kwargs)
    def arrow(self, text, xy, xytext, **kwargs): return self.ax.annotate(text, xy=xy, xytext=xytext, arrowprops=kwargs.pop("arrowprops", {"arrowstyle": "->"}), **kwargs)
    def panel_label(self, label, x=0.02, y=0.98, **kwargs):
        return self.ax.text(x, y, label, transform=self.ax.transAxes, va="top", ha="left", fontweight="bold", **kwargs)

    def inset(self, bounds, **kwargs):
        from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        axes_kwargs = kwargs.pop("axes_kwargs", None)
        axis = inset_axes(self.ax, width=bounds[2], height=bounds[3], loc="lower left",
                          bbox_to_anchor=(bounds[0], bounds[1], 1, 1), bbox_transform=self.ax.transAxes,
                          borderpad=0, axes_kwargs=axes_kwargs, **kwargs)
        return Plot1D(ax=axis, style=None)

    def save(self, path: str | Path, dpi: int | None = None, tight: bool = False, **kwargs):
        """Save without changing requested figure dimensions unless ``tight`` is explicit."""
        if tight: kwargs.setdefault("bbox_inches", "tight")
        self.fig.savefig(path, dpi=dpi, **kwargs)
        return Path(path)
