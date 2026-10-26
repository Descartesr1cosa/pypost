"""Containers for non-rectangular 2-D data and line sampling."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import json
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
    connectivity: np.ndarray | None = None
    cell_types: np.ndarray | None = None

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
        if self.connectivity is not None:
            self.connectivity = np.asarray(self.connectivity, dtype=np.int64).reshape(-1)
            _validate_connectivity(self.connectivity, len(self.points))
            count = _connectivity_count(self.connectivity)
            if self.cell_types is not None:
                self.cell_types = np.asarray(self.cell_types, dtype=np.uint8).reshape(-1)
                if len(self.cell_types) != count:
                    raise ValueError("cell_types must have one VTK type per connectivity cell")
            if self.cell_centers is not None and len(self.cell_centers) != count:
                raise ValueError("cell_centers count must match connectivity cell count")

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
        connectivity = np.asarray(getattr(mesh, "cells", getattr(mesh, "faces", np.empty(0, dtype=np.int64))))
        cell_types = np.asarray(mesh.celltypes) if hasattr(mesh, "celltypes") else None
        return cls(points, dict(mesh.point_data), centers, dict(mesh.cell_data),
                   metadata={"source": source, "plane": {"origin": [0, 0, 0], "basis_u": [1, 0, 0], "basis_v": [0, 1, 0]}} if source else {},
                   connectivity=connectivity if connectivity.size else None, cell_types=cell_types)

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
        if self.connectivity is not None: payload["connectivity"] = self.connectivity
        if self.cell_types is not None: payload["cell_types"] = self.cell_types
        payload["metadata_json"] = np.asarray(json.dumps(self.metadata, ensure_ascii=False, default=str))
        np.savez_compressed(path, **payload)

    @classmethod
    def from_npz(cls, path: str | Path) -> "Data2D":
        with np.load(path, allow_pickle=False) as raw:
            point_names = [str(x) for x in raw["point_names"]]
            cell_names = [str(x) for x in raw["cell_names"]]
            return cls(raw["points"], {n: raw[f"point__{n}"] for n in point_names},
                       raw["cell_centers"] if "cell_centers" in raw else None,
                       {n: raw[f"cell__{n}"] for n in cell_names},
                       json.loads(str(raw["metadata_json"])) if "metadata_json" in raw else {"source": str(path)},
                       raw["connectivity"] if "connectivity" in raw else None,
                       raw["cell_types"] if "cell_types" in raw else None)


def _field_array(values: object) -> np.ndarray:
    """Keep vector component axes, but make a one-item scalar field indexable."""
    array = np.asarray(values)
    if not np.issubdtype(array.dtype, np.number):
        raise TypeError(f"Data2D field must be numeric, got {array.dtype}")
    return array.reshape(1) if array.ndim == 0 else array


def _connectivity_count(cells: np.ndarray) -> int:
    count = 0; index = 0
    while index < len(cells):
        size = int(cells[index]); index += size + 1; count += 1
    return count


def _validate_connectivity(cells: np.ndarray, points: int) -> None:
    index = 0
    while index < len(cells):
        size = int(cells[index])
        if size < 1 or index + size >= len(cells):
            raise ValueError(f"Invalid 2-D connectivity at offset {index}: expected [n, point_ids...]")
        ids = cells[index + 1:index + size + 1]
        if np.any(ids < 0) or np.any(ids >= points):
            raise ValueError(f"2-D connectivity at offset {index} references a point outside [0, {points})")
        index += size + 1
    if index != len(cells): raise ValueError("Invalid 2-D connectivity length")
