"""Containers for non-rectangular 2-D data and line sampling."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator


@dataclass
class Data2D:
    """2-D points plus fields kept separately by their sampling location.

    ``point_fields`` have one value per ``points`` entry. ``cell_fields`` are
    deliberately not converted to points; ``cell_centers`` locates their values.
    """
    points: np.ndarray
    point_fields: dict[str, np.ndarray] = field(default_factory=dict)
    cell_centers: np.ndarray | None = None
    cell_fields: dict[str, np.ndarray] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.points = np.asarray(self.points, dtype=float)
        if self.points.ndim != 2 or self.points.shape[1] != 2:
            raise ValueError("points must have shape (N, 2)")
        self.point_fields = {str(k): _field_array(v) for k, v in self.point_fields.items()}
        if any(len(v) != len(self.points) for v in self.point_fields.values()):
            raise ValueError("Point fields must have one value per point")
        if self.cell_fields:
            if self.cell_centers is None:
                raise ValueError("cell_centers are required for cell_fields")
            self.cell_centers = np.asarray(self.cell_centers, dtype=float)
            if self.cell_centers.ndim != 2 or self.cell_centers.shape[1] != 2:
                raise ValueError("cell_centers must have shape (N, 2)")
            self.cell_fields = {str(k): _field_array(v) for k, v in self.cell_fields.items()}
            if any(len(v) != len(self.cell_centers) for v in self.cell_fields.values()):
                raise ValueError("Cell fields must have one value per cell center")

    @classmethod
    def from_arrays(cls, points, fields: Mapping[str, object], location: str = "point", **kwargs):
        if location == "point":
            return cls(points=np.asarray(points), point_fields=dict(fields), **kwargs)
        if location == "cell":
            return cls(points=np.empty((0, 2)), cell_centers=np.asarray(points), cell_fields=dict(fields), **kwargs)
        raise ValueError("location must be 'point' or 'cell'")

    @classmethod
    def from_vtk(cls, path: str | Path) -> "Data2D":
        import pyvista as pv
        mesh = pv.read(path)
        if isinstance(mesh, pv.MultiBlock):
            raise TypeError("Select a block from MultiBlock before constructing Data2D")
        return cls.from_pyvista(mesh, source=str(path))

    @classmethod
    def from_pyvista(cls, mesh, source: str | None = None) -> "Data2D":
        points = np.asarray(mesh.points)[:, :2]
        centers = np.asarray(mesh.cell_centers().points)[:, :2] if mesh.n_cells else None
        return cls(points, dict(mesh.point_data), centers, dict(mesh.cell_data),
                   metadata={"source": source} if source else {})

    def field(self, name: str) -> tuple[np.ndarray, np.ndarray, str]:
        if name in self.point_fields:
            return self.points, self.point_fields[name], "point"
        if name in self.cell_fields:
            return self.cell_centers, self.cell_fields[name], "cell"
        raise KeyError(f"Field {name!r} not found; available: {self.field_names}")

    @property
    def field_names(self) -> list[str]:
        return list(self.point_fields) + list(self.cell_fields)

    def sample_line(self, field: str, start, end, n: int = 200, method: str = "linear") -> tuple[np.ndarray, np.ndarray]:
        """Sample a scalar field along a segment without altering its location type."""
        if n < 2:
            raise ValueError("n must be at least 2")
        coords, values, _ = self.field(field)
        values = np.asarray(values)
        if values.ndim != 1:
            raise ValueError("sample_line currently accepts scalar fields only")
        t = np.linspace(0.0, 1.0, n)
        start, end = np.asarray(start, float), np.asarray(end, float)
        line = start[None, :] + t[:, None] * (end - start)[None, :]
        interpolator = LinearNDInterpolator(coords, values, fill_value=np.nan) if method == "linear" else NearestNDInterpolator(coords, values)
        sampled = interpolator(line)
        if method == "linear" and np.isnan(sampled).any():
            nearest = NearestNDInterpolator(coords, values)
            sampled = np.where(np.isnan(sampled), nearest(line), sampled)
        return np.linalg.norm(line - start, axis=1), np.asarray(sampled)

    def save_npz(self, path: str | Path) -> None:
        """Persist coordinates and separately located fields without VTK conversion."""
        payload = {"points": self.points, "point_names": np.asarray(list(self.point_fields)),
                   "cell_names": np.asarray(list(self.cell_fields))}
        payload.update({f"point__{k}": v for k, v in self.point_fields.items()})
        payload.update({f"cell__{k}": v for k, v in self.cell_fields.items()})
        if self.cell_centers is not None:
            payload["cell_centers"] = self.cell_centers
        np.savez_compressed(path, **payload)

    @classmethod
    def from_npz(cls, path: str | Path) -> "Data2D":
        with np.load(path, allow_pickle=False) as raw:
            point_names = [str(x) for x in raw["point_names"]]
            cell_names = [str(x) for x in raw["cell_names"]]
            return cls(raw["points"], {n: raw[f"point__{n}"] for n in point_names},
                       raw["cell_centers"] if "cell_centers" in raw else None,
                       {n: raw[f"cell__{n}"] for n in cell_names}, {"source": str(path)})


def _field_array(values: object) -> np.ndarray:
    """Keep vector component axes, but make a one-item scalar field indexable."""
    array = np.asarray(values)
    return array.reshape(1) if array.ndim == 0 else array
