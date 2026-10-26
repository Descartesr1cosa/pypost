"""Inspection and strict validation reports for standard datasets."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np

from ..data import Data1D, Data2D, Data3D
from ..provenance import vtk_dependency_signature
from .dataset import FORMAT, FORMAT_VERSION, VTK_SUFFIXES, _npz_header, _vtk_header, load_dataset


def _stats(values) -> dict[str, Any]:
    array = np.asarray(values)
    result = {"shape": list(array.shape), "dtype": str(array.dtype),
              "components": int(np.prod(array.shape[1:])) if array.ndim > 1 else 1,
              "nan": 0, "inf": 0}
    if np.issubdtype(array.dtype, np.number):
        result["nan"] = int(np.isnan(array).sum()) if np.issubdtype(array.dtype, np.inexact) else 0
        result["inf"] = int(np.isinf(array).sum()) if np.issubdtype(array.dtype, np.inexact) else 0
        finite = array[np.isfinite(array)] if np.issubdtype(array.dtype, np.inexact) else array.reshape(-1)
        if finite.size: result["range"] = [float(np.min(finite)), float(np.max(finite))]
    return result


def _encoding(path: Path) -> str:
    if path.suffix.lower() == ".npz": return "binary"
    if path.suffix.lower() in {".csv", ".txt", ".xy", ".dat"}: return "ascii"
    if path.suffix.lower() in VTK_SUFFIXES:
        try:
            root = ElementTree.parse(path).getroot()
            formats = {item.attrib.get("format", "ascii") for item in root.iter() if item.tag.endswith("DataArray")}
            return "ascii" if formats <= {"ascii"} else "binary"
        except (ElementTree.ParseError, OSError): return "unknown"
    return "unknown"


def _base(path: Path, dimension: str, header: dict[str, Any] | None) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "format": (header or {}).get("format", "legacy"),
            "format_version": (header or {}).get("format_version"), "dimension": dimension,
            "encoding": (header or {}).get("encoding", _encoding(path)), "file_size": stat.st_size,
            "estimated_memory": 0, "fields": [], "metadata": (header or {}).get("metadata", {})}


def inspect_dataset(path: str | Path) -> dict[str, Any]:
    """Return a JSON-serializable report without modifying data or metadata."""
    source = Path(path)
    if not source.is_file(): raise FileNotFoundError(f"Dataset file not found: {source}")
    header = _npz_header(source) if source.suffix.lower() == ".npz" else _vtk_header(source)
    data = load_dataset(source)
    if isinstance(data, Data1D):
        result = _base(source, "1d", header)
        result.update({"points": len(data.x), "coordinate": {"name": data.x_name, "unit": data.x_unit, **_stats(data.x)}})
        result["fields"] = [{"name": name, "location": "point", "unit": data.field_units.get(name), **_stats(values)} for name, values in data.fields.items()]
        result["estimated_memory"] = int(data.x.nbytes + sum(values.nbytes for values in data.fields.values()))
        return result
    if isinstance(data, Data2D):
        result = _base(source, "2d", header)
        result.update({"points": len(data.points), "cells": _cells(data.connectivity), "mesh_type": "planar-point-cloud" if data.connectivity is None else "planar-unstructured",
                       "topology": {"connectivity": data.connectivity is not None, "cell_types": data.cell_types is not None,
                                    "plane": data.metadata.get("plane")}})
        result["fields"] = ([{"name": name, "location": "point", **_stats(values)} for name, values in data.point_fields.items()] +
                            [{"name": name, "location": "cell", **_stats(values)} for name, values in data.cell_fields.items()])
        result["estimated_memory"] = int(data.points.nbytes + sum(v.nbytes for v in data.point_fields.values()) + sum(v.nbytes for v in data.cell_fields.values()) +
                                          (0 if data.connectivity is None else data.connectivity.nbytes))
        return result
    if isinstance(data, Data3D):
        result = _base(source, "3d", header or data.metadata)
        result.update(_mesh_report(data.mesh))
        result["dependencies"] = vtk_dependency_signature(source)["dependencies"] if source.suffix.lower() == ".vtm" else []
        return result
    raise TypeError(type(data))


def _cells(connectivity) -> int:
    if connectivity is None: return 0
    count = 0; index = 0
    while index < len(connectivity): index += int(connectivity[index]) + 1; count += 1
    return count


def _mesh_report(mesh) -> dict[str, Any]:
    import pyvista as pv
    if isinstance(mesh, pv.MultiBlock):
        blocks = [_mesh_report(block) for block in mesh if block is not None]
        return {"mesh_type": "MultiBlock", "blocks": blocks, "points": sum(item.get("points", 0) for item in blocks),
                "cells": sum(item.get("cells", 0) for item in blocks), "fields": [field for item in blocks for field in item.get("fields", [])],
                "estimated_memory": sum(item.get("estimated_memory", 0) for item in blocks)}
    fields = []
    for location, arrays in (("point", mesh.point_data), ("cell", mesh.cell_data)):
        for name, values in arrays.items(): fields.append({"name": str(name), "location": location, **_stats(values)})
    memory = mesh.points.nbytes + sum(np.asarray(value).nbytes for value in mesh.point_data.values()) + sum(np.asarray(value).nbytes for value in mesh.cell_data.values())
    return {"mesh_type": type(mesh).__name__, "points": int(mesh.n_points), "cells": int(mesh.n_cells), "fields": fields,
            "estimated_memory": int(memory), "bounds": [float(value) for value in mesh.bounds]}


def validate_dataset(path: str | Path, deep: bool = False) -> dict[str, Any]:
    """Validate structure and report every observed problem without repairing it."""
    source = Path(path); issues: list[str] = []
    try:
        report = inspect_dataset(source)
        data = load_dataset(source)
        if report["format"] == FORMAT and report.get("format_version") != FORMAT_VERSION:
            issues.append(f"unsupported format version {report.get('format_version')}")
        for field in report.get("fields", []):
            if field.get("inf", 0): issues.append(f"field {field['location']}:{field['name']} contains {field['inf']} Inf values")
        if isinstance(data, Data2D) and data.connectivity is not None:
            _validate_2d_connectivity(data, issues)
        if isinstance(data, Data3D): _validate_mesh(data.mesh, issues)
        if source.suffix.lower() == ".vtm":
            try: vtk_dependency_signature(source)
            except Exception as exc: issues.append(f"VTM dependency failure: {exc}")
        checksums = None
        if deep:
            checksums = {"sha256": sha256(source.read_bytes()).hexdigest()}
            if source.suffix.lower() == ".vtm":
                checksums["dependencies"] = {item["path"]: sha256(Path(item["path"]).read_bytes()).hexdigest()
                                                for item in vtk_dependency_signature(source)["dependencies"]}
        return {"valid": not issues, "path": str(source), "issues": issues, "report": report, "checksums": checksums}
    except Exception as exc:
        return {"valid": False, "path": str(source), "issues": [str(exc)], "report": None, "checksums": None}


def _validate_2d_connectivity(data: Data2D, issues: list[str]) -> None:
    cells = data.connectivity; index = 0; count = 0
    while index < len(cells):
        size = int(cells[index])
        if size < 1 or index + size >= len(cells):
            issues.append(f"connectivity cell at offset {index} is truncated"); return
        ids = cells[index + 1:index + size + 1]
        if np.any(ids < 0) or np.any(ids >= len(data.points)):
            issues.append(f"connectivity cell {count} references an invalid point index")
        index += size + 1; count += 1
    if data.cell_centers is not None and len(data.cell_centers) != count: issues.append("cell_centers count does not match connectivity")


def _validate_mesh(mesh, issues: list[str]) -> None:
    import pyvista as pv
    if isinstance(mesh, pv.MultiBlock):
        for index, block in enumerate(mesh):
            if block is None: issues.append(f"MultiBlock has empty block {index}")
            else: _validate_mesh(block, issues)
        return
    for location, arrays, expected in (("point", mesh.point_data, mesh.n_points), ("cell", mesh.cell_data, mesh.n_cells)):
        for name, values in arrays.items():
            if len(values) != expected: issues.append(f"{location} field {name!r} has {len(values)} tuples; expected {expected}")
