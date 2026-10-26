"""Strict, safe storage for pypost standard datasets.

Legacy readers remain in the data containers.  This module is the public API
for new converters and writes a small JSON header rather than pickle objects.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..data import Data1D, Data2D, Data3D


FORMAT = "pypost-dataset"
FORMAT_VERSION = 1
VTK_SUFFIXES = {".vtu", ".vts", ".vti", ".vtm", ".vtp"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _header(kind: str, encoding: str, data, fields: list[dict[str, Any]], **extra) -> dict[str, Any]:
    result = {"format": FORMAT, "format_version": FORMAT_VERSION, "dimension": kind,
              "encoding": encoding, "fields": fields, "metadata": dict(getattr(data, "metadata", {}))}
    result.update(extra)
    return result


def _array_info(name: str, values, location: str) -> dict[str, Any]:
    array = np.asarray(values)
    return {"name": name, "location": location, "shape": list(array.shape), "dtype": str(array.dtype),
            "components": int(np.prod(array.shape[1:])) if array.ndim > 1 else 1}


def _reject_inf(data) -> None:
    arrays: list[tuple[str, np.ndarray]] = []
    if isinstance(data, Data1D): arrays = [(data.x_name, data.x), *data.fields.items()]
    elif isinstance(data, Data2D):
        arrays = [("points", data.points), *data.point_fields.items(), *data.cell_fields.items()]
        if data.cell_centers is not None: arrays.append(("cell_centers", data.cell_centers))
    elif isinstance(data, Data3D):
        import pyvista as pv
        def collect(mesh):
            if isinstance(mesh, pv.MultiBlock):
                for block in mesh:
                    if block is not None: collect(block)
            else:
                arrays.extend([(str(name), np.asarray(value)) for name, value in mesh.point_data.items()])
                arrays.extend([(str(name), np.asarray(value)) for name, value in mesh.cell_data.items()])
        collect(data.mesh)
    for name, values in arrays:
        if not np.issubdtype(np.asarray(values).dtype, np.number):
            raise TypeError(f"Strict pypost storage requires numeric arrays; {name!r} has dtype {np.asarray(values).dtype}")
        if np.isinf(values).any():
            raise ValueError(f"Strict pypost storage rejects Inf values in {name!r}; replace or document them before saving")


def save_dataset(data, path: str | Path, encoding: str = "binary") -> Path:
    """Save a Data1D/Data2D/Data3D object without pickle or implicit coercion.

    ``.npz`` is binary storage for 1-D/2-D, ``.csv`` is ASCII 1-D scalar
    storage, and VTK XML extensions are 2-D/3-D mesh storage.  ASCII VTK is
    selected with ``encoding='ascii'``.
    """
    if encoding not in {"binary", "ascii"}: raise ValueError("encoding must be 'binary' or 'ascii'")
    target = Path(path)
    if not target.suffix: raise ValueError("Standard dataset paths need an explicit suffix (.npz, .csv, or VTK XML)")
    _reject_inf(data)
    if isinstance(data, Data1D): return _save_1d(data, target, encoding)
    if isinstance(data, Data2D): return _save_2d(data, target, encoding)
    if isinstance(data, Data3D):
        if target.suffix.lower() not in VTK_SUFFIXES:
            raise ValueError("Data3D standard storage requires VTK XML (.vtu/.vts/.vti/.vtm/.vtp)")
        data.save(target, binary=encoding == "binary")
        _write_vtk_header(target, _header("3d", encoding, data, _mesh_fields(data.mesh), source=data.source, time=data.time))
        return target
    raise TypeError(f"Unsupported standard dataset type: {type(data)!r}")


def _save_1d(data: Data1D, target: Path, encoding: str) -> Path:
    fields = [_array_info(name, values, "point") for name, values in data.fields.items()]
    header = _header("1d", encoding, data, fields, coordinate={"name": data.x_name, "unit": data.x_unit,
                     "shape": list(data.x.shape), "dtype": str(data.x.dtype)}, field_units=data.field_units,
                     sample_order="preserved", x_name=data.x_name, x_unit=data.x_unit)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".npz":
        if encoding != "binary": raise ValueError("NPZ is binary; use a .csv path for ASCII 1-D storage")
        payload = {"__pypost_header__": np.asarray(_json(header)), "x": data.x,
                   "field_names": np.asarray(list(data.fields), dtype="U")}
        payload.update({f"field__{name}": values for name, values in data.fields.items()})
        np.savez_compressed(target, **payload)
        return target
    if target.suffix.lower() == ".csv":
        if encoding != "ascii": raise ValueError("CSV is ASCII; use encoding='ascii' or a .npz path")
        data.save_csv(target, metadata=False)
        target.with_suffix(target.suffix + ".json").write_text(json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target
    raise ValueError("Data1D standard storage requires .npz (binary) or .csv (ASCII)")


def _save_2d(data: Data2D, target: Path, encoding: str) -> Path:
    fields = ([_array_info(name, values, "point") for name, values in data.point_fields.items()] +
              [_array_info(name, values, "cell") for name, values in data.cell_fields.items()])
    header = _header("2d", encoding, data, fields, points={"shape": list(data.points.shape), "dtype": str(data.points.dtype)},
                     topology={"connectivity": data.connectivity is not None, "cells": _cell_count(data.connectivity) if data.connectivity is not None else 0},
                     plane=data.metadata.get("plane"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".npz":
        if encoding != "binary": raise ValueError("NPZ is binary; use a VTK XML path for ASCII 2-D mesh storage")
        payload = {"__pypost_header__": np.asarray(_json(header)), "points": data.points,
                   "point_names": np.asarray(list(data.point_fields), dtype="U"), "cell_names": np.asarray(list(data.cell_fields), dtype="U"),
                   "metadata_json": np.asarray(_json(data.metadata))}
        payload.update({f"point__{name}": values for name, values in data.point_fields.items()})
        payload.update({f"cell__{name}": values for name, values in data.cell_fields.items()})
        if data.cell_centers is not None: payload["cell_centers"] = data.cell_centers
        if data.connectivity is not None: payload["connectivity"] = data.connectivity
        if data.cell_types is not None: payload["cell_types"] = data.cell_types
        np.savez_compressed(target, **payload)
        return target
    if target.suffix.lower() in VTK_SUFFIXES:
        mesh = _data2d_mesh(data)
        mesh.save(target, binary=encoding == "binary")
        _write_vtk_header(target, header)
        return target
    raise ValueError("Data2D standard storage requires .npz or a VTK XML extension")


def _cell_count(connectivity: np.ndarray | None) -> int:
    if connectivity is None: return 0
    count = 0; index = 0
    while index < len(connectivity): index += int(connectivity[index]) + 1; count += 1
    return count


def _data2d_mesh(data: Data2D):
    if data.connectivity is None:
        raise ValueError("Data2D VTK output needs connectivity; use .npz for point clouds or provide VTK-style [n, ids...] cells")
    import pyvista as pv
    cells = np.asarray(data.connectivity, dtype=np.int64)
    if data.cell_types is None:
        types = []; index = 0
        vtk_type = {3: 5, 4: 9}
        while index < len(cells):
            size = int(cells[index]); types.append(vtk_type.get(size, 7)); index += size + 1
        cell_types = np.asarray(types, dtype=np.uint8)
    else: cell_types = data.cell_types
    points = np.column_stack((data.points, np.zeros(len(data.points), dtype=data.points.dtype)))
    mesh = pv.UnstructuredGrid(cells, cell_types, points)
    for name, values in data.point_fields.items(): mesh.point_data[name] = values
    for name, values in data.cell_fields.items(): mesh.cell_data[name] = values
    return mesh


def _write_vtk_header(path: Path, header: dict[str, Any]) -> None:
    path.with_suffix(path.suffix + ".pypost.json").write_text(json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mesh_fields(mesh) -> list[dict[str, Any]]:
    import pyvista as pv
    if isinstance(mesh, pv.MultiBlock):
        return [field for block in mesh if block is not None for field in _mesh_fields(block)]
    return ([_array_info(str(name), values, "point") for name, values in mesh.point_data.items()] +
            [_array_info(str(name), values, "cell") for name, values in mesh.cell_data.items()])


def _npz_header(path: Path) -> dict[str, Any] | None:
    with np.load(path, allow_pickle=False) as raw:
        if "__pypost_header__" not in raw: return None
        try: return json.loads(str(raw["__pypost_header__"].item()))
        except (json.JSONDecodeError, ValueError) as exc: raise ValueError(f"Invalid pypost NPZ header: {path}") from exc


def load_dataset(path: str | Path):
    """Safely load a standard dataset or a documented legacy CSV/NPZ/VTK file."""
    source = Path(path)
    if not source.is_file(): raise FileNotFoundError(f"Dataset file not found: {source}")
    suffix = source.suffix.lower()
    if suffix == ".npz":
        header = _npz_header(source)
        if header is None: return Data2D.from_npz(source)  # legacy 2-D NPZ
        _validate_header(header, source)
        if header["dimension"] == "1d":
            with np.load(source, allow_pickle=False) as raw:
                names = [str(x) for x in raw["field_names"]]
                coordinate = header["coordinate"]
                return Data1D(raw["x"], {name: raw[f"field__{name}"] for name in names}, x_name=coordinate["name"],
                              x_unit=coordinate.get("unit"), field_units=header.get("field_units", {}), metadata=header.get("metadata", {}), sort=False)
        if header["dimension"] == "2d": return Data2D.from_npz(source)
        raise ValueError(f"NPZ header has unsupported dimension {header['dimension']!r}")
    if suffix in {".csv", ".txt", ".xy", ".dat"}: return Data1D.from_file(source)
    if suffix in VTK_SUFFIXES:
        header = _vtk_header(source)
        if header and header.get("dimension") == "2d": return Data2D.from_vtk(source)
        return Data3D.from_file(source)
    raise ValueError(f"Unsupported dataset extension {suffix!r}; use .npz, .csv, or VTK XML")


def _vtk_header(path: Path) -> dict[str, Any] | None:
    sidecar = path.with_suffix(path.suffix + ".pypost.json")
    if not sidecar.is_file(): return None
    try: return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise ValueError(f"Invalid VTK metadata sidecar: {sidecar}") from exc


def _validate_header(header: dict[str, Any], path: Path) -> None:
    if header.get("format") != FORMAT or header.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"Unsupported pypost dataset header in {path}; expected {FORMAT} v{FORMAT_VERSION}")
    if header.get("dimension") not in {"1d", "2d", "3d"}: raise ValueError(f"Invalid dataset dimension in {path}")
