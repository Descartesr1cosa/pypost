"""Matplotlib plotting for :class:`sciplot.data.Data1D`."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from ..data import Data1D
from ..utils.style import apply_style


class Plot1D:
    def __init__(self, figsize=(6.4, 4.2), style: str | None = None, dpi: int | None = None):
        if style:
            apply_style(style)
        self.fig, self.ax = plt.subplots(figsize=figsize, dpi=dpi)

    def line(self, data: Data1D, field: str, label: str | None = None,
             x_transform=None, y_transform=None, **kwargs):
        if field not in data.fields:
            raise KeyError(f"{field!r} is not in {list(data.fields)}")
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        return self.ax.plot(x, y, label=label, **kwargs)[0]

    def scatter(self, data: Data1D, field: str, label: str | None = None,
                x_transform=None, y_transform=None, **kwargs):
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        return self.ax.scatter(x, y, label=label, **kwargs)

    def errorbar(self, data: Data1D, field: str, yerr, label: str | None = None,
                 x_transform=None, y_transform=None, **kwargs):
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        y = data.fields[field] if y_transform is None else np.asarray(y_transform(data.fields[field]))
        return self.ax.errorbar(x, y, yerr=yerr, label=label, **kwargs)

    def band(self, data: Data1D, lower: str, upper: str, label: str | None = None,
             x_transform=None, y_transform=None, **kwargs):
        if lower not in data.fields or upper not in data.fields:
            raise KeyError(f"Band fields must be present: {lower!r}, {upper!r}")
        x = data.x if x_transform is None else np.asarray(x_transform(data.x))
        convert = (lambda values: values) if y_transform is None else y_transform
        return self.ax.fill_between(x, convert(data.fields[lower]), convert(data.fields[upper]), label=label, **kwargs)

    def lines(self, datasets, field: str, labels=None, **kwargs):
        labels = labels or [None] * len(datasets)
        return [self.line(data, field, label=label, **kwargs) for data, label in zip(datasets, labels)]

    def set_axes(self, xlabel=None, ylabel=None, title=None, xlim=None, ylim=None,
                 xticks=None, yticks=None, equal: bool = False, legend: bool = False, legend_kwargs=None):
        if xlabel is not None: self.ax.set_xlabel(xlabel)
        if ylabel is not None: self.ax.set_ylabel(ylabel)
        if title is not None: self.ax.set_title(title)
        if xlim is not None: self.ax.set_xlim(xlim)
        if ylim is not None: self.ax.set_ylim(ylim)
        if xticks is not None: self.ax.set_xticks(xticks)
        if yticks is not None: self.ax.set_yticks(yticks)
        if equal: self.ax.set_aspect("equal", adjustable="box")
        if legend: self.ax.legend(**(legend_kwargs or {}))
        return self

    def save(self, path: str | Path, dpi: int | None = None, **kwargs):
        self.fig.savefig(path, dpi=dpi, **kwargs)
        return Path(path)
