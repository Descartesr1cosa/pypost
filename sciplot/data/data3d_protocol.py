"""Strict, solver-independent Data3D v1 VTK protocol helpers.

The JSON document is deliberately stored as unsigned UTF-8 bytes in VTK
``FieldData``.  That representation survives ordinary VTK XML readers and
does not depend on PyVista serialising a Python dictionary or VTK string-array
implementation details.
"""
from __future__ import annotations

from typing import Any
import json

import numpy as np


FORMAT = "pypost-data3d"
VERSION = 1
METADATA_ARRAY = "pypost_data3d_v1_json_utf8"


def encode_metadata(metadata: dict[str, Any]) -> np.ndarray:
    """Return canonical UTF-8 metadata bytes suitable for VTK FieldData."""
    text = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return np.frombuffer(text.encode("utf-8"), dtype=np.uint8).copy()


def metadata_from_mesh(mesh: object) -> dict[str, Any] | None:
    """Read the exact embedded v1 document, returning ``None`` when absent."""
    field_data = getattr(mesh, "field_data", None)
    if field_data is None or METADATA_ARRAY not in field_data:
        return None
    raw = np.asarray(field_data[METADATA_ARRAY], dtype=np.uint8).reshape(-1)
    try:
        value = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid embedded {METADATA_ARRAY} FieldData: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Embedded Data3D metadata must be a JSON object")
    return value


def standard_metadata(*, physical_time: float, time_unit: str, coordinate_unit: str,
                      source: dict[str, Any], fields: dict[str, dict[str, Any]],
                      normalization: dict[str, Any] | None = None,
                      coordinate_system: str = "Cartesian",
                      cell_fields: dict[str, dict[str, Any]] | None = None,
                      conversion: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construct the complete metadata baseline required by Data3D v1."""
    return {
        "format": FORMAT,
        "format_version": VERSION,
        "physical_time": float(physical_time),
        "time_unit": str(time_unit),
        "coordinates": {"system": coordinate_system, "unit": str(coordinate_unit), "components": ["x", "y", "z"]},
        "node_identity": {"contract": "global_unique"},
        "source": dict(source),
        "fields": {str(name): dict(value) for name, value in fields.items()},
        "cell_fields": {str(name): dict(value) for name, value in (cell_fields or {}).items()},
        "normalization": dict(normalization or {}),
        "conversion": dict(conversion or {}),
    }


def validate_v1_mesh(mesh: object, metadata: dict[str, Any] | None = None) -> list[str]:
    """Validate structural and semantic Data3D v1 requirements without repair."""
    import pyvista as pv

    issues: list[str] = []
    if not isinstance(mesh, pv.UnstructuredGrid):
        return ["Data3D v1 requires a single VTK UnstructuredGrid (.vtu)"]
    if metadata is None:
        try:
            metadata = metadata_from_mesh(mesh)
        except ValueError as exc:
            return [str(exc)]
    if not isinstance(metadata, dict):
        return [f"missing embedded FieldData array {METADATA_ARRAY}"]
    required = {"format", "format_version", "physical_time", "time_unit", "coordinates", "node_identity", "source", "fields", "cell_fields", "normalization", "conversion"}
    missing = sorted(required - metadata.keys())
    if missing:
        issues.append(f"metadata is missing required keys: {', '.join(missing)}")
    if metadata.get("format") != FORMAT:
        issues.append(f"metadata format must be {FORMAT!r}")
    if metadata.get("format_version") != VERSION:
        issues.append(f"unsupported Data3D version {metadata.get('format_version')!r}; expected {VERSION}")
    try:
        if not np.isfinite(float(metadata.get("physical_time"))):
            issues.append("physical_time must be finite")
    except (TypeError, ValueError):
        issues.append("physical_time must be a finite number")
    if not isinstance(metadata.get("time_unit"), str) or not metadata.get("time_unit"):
        issues.append("time_unit must be a non-empty string")
    coordinates = metadata.get("coordinates")
    if not isinstance(coordinates, dict) or coordinates.get("system") != "Cartesian" or not isinstance(coordinates.get("unit"), str) or not coordinates.get("unit"):
        issues.append("coordinates must declare Cartesian system and a non-empty unit")
    identity = metadata.get("node_identity")
    if not isinstance(identity, dict) or identity.get("contract") != "global_unique":
        issues.append("node_identity.contract must be 'global_unique'")
    source = metadata.get("source")
    if (not isinstance(source, dict) or not isinstance(source.get("name"), str) or not source["name"]
            or not isinstance(source.get("version"), str) or not source["version"]):
        issues.append("source must name and version the producing converter or data source")

    points = np.asarray(mesh.points)
    if points.ndim != 2 or points.shape != (mesh.n_points, 3):
        issues.append("points must have shape (N, 3)")
    elif not np.isfinite(points).all():
        issues.append("points contain NaN or Inf")
    if mesh.n_points == 0 or mesh.n_cells == 0:
        issues.append("Data3D v1 requires at least one point and one volume cell")
    connectivity = np.asarray(mesh.cell_connectivity)
    offsets = np.asarray(mesh.cell_offsets if hasattr(mesh, "cell_offsets") else mesh.offset)
    if offsets.size != mesh.n_cells + 1 or (offsets.size and (offsets[0] != 0 or offsets[-1] != connectivity.size)):
        issues.append("cell offsets/connectivity are inconsistent")
    elif np.any(connectivity < 0) or np.any(connectivity >= mesh.n_points):
        issues.append("cell connectivity references an invalid point index")
    for index in range(mesh.n_cells):
        ids = connectivity[offsets[index]:offsets[index + 1]]
        if len(np.unique(ids)) != len(ids):
            issues.append(f"cell {index} repeats a node and is topologically degenerate")
            break
        if mesh.get_cell(index).dimension != 3:
            issues.append(f"cell {index} is not a three-dimensional volume cell")
            break
    if mesh.n_cells:
        try:
            sizes = np.asarray(mesh.compute_cell_sizes(length=False, area=False, volume=True).cell_data["Volume"])
            scale = max(float(np.ptp(points, axis=0).max()) if points.size else 1.0, 1.0)
            if not np.isfinite(sizes).all() or np.any(sizes <= np.finfo(float).eps * scale ** 3):
                issues.append("mesh contains non-finite or zero/degenerate volume cells")
        except Exception as exc:
            issues.append(f"could not determine cell volumes: {exc}")

    descriptors = metadata.get("fields")
    if not isinstance(descriptors, dict):
        issues.append("fields must be an object keyed by PointData name")
        descriptors = {}
    point_names = {str(name) for name in mesh.point_data.keys()}
    for name in sorted(point_names - set(descriptors)):
        issues.append(f"PointData field {name!r} has no metadata descriptor")
    for name, descriptor in descriptors.items():
        if name not in point_names:
            issues.append(f"metadata describes absent PointData field {name!r}")
            continue
        values = np.asarray(mesh.point_data[name])
        if len(values) != mesh.n_points:
            issues.append(f"PointData field {name!r} has {len(values)} tuples; expected {mesh.n_points}")
        if not np.issubdtype(values.dtype, np.number):
            issues.append(f"PointData field {name!r} must be numeric")
        if np.issubdtype(values.dtype, np.inexact) and np.isinf(values).any():
            issues.append(f"PointData field {name!r} contains Inf")
        if not isinstance(descriptor, dict):
            issues.append(f"field descriptor for {name!r} must be an object")
            continue
        components = int(np.prod(values.shape[1:])) if values.ndim > 1 else 1
        kind = descriptor.get("kind")
        expected = {"scalar": 1, "vector": 3, "tensor": 9}.get(kind)
        if expected is None or components != expected or descriptor.get("components") != expected:
            issues.append(f"field {name!r} must declare matching scalar(1), vector(3), or tensor(9) components")
        if not isinstance(descriptor.get("unit"), str) or not descriptor.get("unit"):
            issues.append(f"field {name!r} must declare a non-empty unit")
        if not isinstance(descriptor.get("description"), str) or not descriptor.get("description"):
            issues.append(f"field {name!r} must declare a non-empty description")
        if np.issubdtype(values.dtype, np.inexact) and np.isnan(values).any() and not isinstance(descriptor.get("missing_data"), str):
            issues.append(f"PointData field {name!r} contains NaN but has no missing_data declaration")
        if descriptor.get("provenance") not in {"native", "reconstructed", "derived"}:
            issues.append(f"field {name!r} provenance must be native, reconstructed, or derived")
        if kind == "vector" and descriptor.get("component_system") != "Cartesian":
            issues.append(f"vector field {name!r} must explicitly declare Cartesian components")
        if kind == "tensor" and descriptor.get("flattening") != "row-major-xx-xy-xz-yx-yy-yz-zx-zy-zz":
            issues.append(f"tensor field {name!r} must use the v1 row-major flattening declaration")
    cell_descriptors = metadata.get("cell_fields")
    if not isinstance(cell_descriptors, dict):
        issues.append("cell_fields must describe CellData topology/source arrays")
        cell_descriptors = {}
    cell_names = {str(name) for name in mesh.cell_data.keys()}
    if "SourceBlockId" not in cell_names:
        issues.append("CellData must contain SourceBlockId for original-block provenance")
    elif not np.issubdtype(np.asarray(mesh.cell_data["SourceBlockId"]).dtype, np.integer):
        issues.append("SourceBlockId must be an integer CellData array")
    source_block_descriptor = cell_descriptors.get("SourceBlockId", {}) if isinstance(cell_descriptors, dict) else {}
    if not isinstance(source_block_descriptor, dict) or source_block_descriptor.get("role") != "source_block_id":
        issues.append("SourceBlockId metadata must declare role 'source_block_id'")
    for name in sorted(cell_names - set(cell_descriptors)):
        issues.append(f"CellData field {name!r} has no topology/source descriptor")
    for name in sorted(cell_descriptors):
        if name not in cell_names:
            issues.append(f"metadata describes absent CellData field {name!r}")
        elif len(mesh.cell_data[name]) != mesh.n_cells:
            issues.append(f"CellData field {name!r} has incorrect tuple count")
    return issues
