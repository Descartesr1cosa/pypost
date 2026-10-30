"""Algebraic fields, geometric slices, and probes for Data3D v1 volumes.

No solver discretisation is reconstructed here.  VTK performs ordinary
piecewise-linear interpolation of already Cartesian PointData on the supplied
volume mesh; unsupported/outside samples are explicitly marked invalid.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json

import numpy as np

from ..data import Data1D, Data3D
from ..data.data3d_protocol import encode_metadata
from ..workflow import read_yaml


SLICE_METADATA_ARRAY = "pypost_slice_v1_json_utf8"


@dataclass(frozen=True)
class DerivedField:
    """One new PointData array plus its Data3D-compatible descriptor."""
    name: str
    values: np.ndarray
    descriptor: dict[str, Any]
    dependencies: tuple[str, ...]


@dataclass
class SliceData:
    """An actual VTK plane/volume intersection with local-plane metadata."""
    mesh: object
    metadata: dict[str, Any]

    def project_vector(self, field: str, output: str | None = None) -> np.ndarray:
        values = np.asarray(self.mesh.point_data[field])
        if values.shape != (self.mesh.n_points, 3):
            raise ValueError(f"{field!r} is not a three-component PointData vector")
        basis = self.metadata["plane"]
        result = np.column_stack((values @ np.asarray(basis["basis_u"]), values @ np.asarray(basis["basis_v"])))
        if output:
            self.mesh.point_data[output] = result
        return result

    def save(self, path: str | Path, binary: bool = True) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".vtp":
            raise ValueError("SliceData must be stored as a VTK PolyData .vtp file")
        copy = self.mesh.copy(deep=False)
        copy.field_data[SLICE_METADATA_ARRAY] = encode_metadata(self.metadata)
        path.parent.mkdir(parents=True, exist_ok=True)
        copy.save(path, binary=binary)
        return path

    @classmethod
    def from_file(cls, path: str | Path) -> "SliceData":
        import pyvista as pv
        mesh = pv.read(path)
        if SLICE_METADATA_ARRAY not in mesh.field_data:
            raise ValueError(f"Not a pypost SliceData file: missing {SLICE_METADATA_ARRAY}")
        try:
            metadata = json.loads(bytes(np.asarray(mesh.field_data[SLICE_METADATA_ARRAY], dtype=np.uint8)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid embedded slice metadata: {exc}") from exc
        return cls(mesh, metadata)


def _require_data3d_v1(data: Data3D) -> None:
    if not isinstance(data, Data3D) or not data.is_data3d_v1:
        raise TypeError("processing accepts only a loaded conforming Data3D v1 object")


def _descriptor(data: Data3D, name: str) -> dict[str, Any]:
    value = data.metadata.get("fields", {}).get(name)
    if not isinstance(value, dict):
        raise KeyError(f"PointData field {name!r} has no Data3D v1 descriptor")
    return value


def _reference_value(data: Data3D, path: str) -> float:
    """Resolve ``a.b`` in the file's ``normalization`` block, e.g. ``@pressure_ref`` or ``@physical_constants.mu0``."""
    node: Any = data.metadata.get("normalization", {})
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"normalization has no entry {path!r}; available: {sorted(data.metadata.get('normalization', {}))}")
        node = node[part]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise TypeError(f"normalization entry {path!r} is not a number")
    return float(node)


def _field(data: Data3D, value: str | DerivedField | float | int,
           available: Mapping[str, DerivedField] | None = None) -> tuple[np.ndarray, dict[str, Any], tuple[str, ...]]:
    if isinstance(value, DerivedField): return value.values, value.descriptor, value.dependencies
    if isinstance(value, str) and value.startswith("@"):
        return np.asarray(_reference_value(data, value[1:])), {"kind": "constant", "unit": "1", "provenance": "derived", "description": value}, ()
    if isinstance(value, str):
        if available and value in available:
            item = available[value]; return item.values, item.descriptor, item.dependencies
        if value not in data.mesh.point_data: raise KeyError(f"PointData field {value!r} is unavailable")
        return np.asarray(data.mesh.point_data[value]), _descriptor(data, value), (value,)
    if isinstance(value, (float, int)):
        return np.asarray(float(value)), {"kind": "constant", "unit": "1", "provenance": "derived", "description": str(value)}, ()
    raise TypeError(f"Unsupported field operand {value!r}")


def _unit_binary(left: dict[str, Any], right: dict[str, Any], operation: str) -> str:
    lu, ru = left.get("unit", "1"), right.get("unit", "1")
    if left.get("kind") == "constant": return ru
    if right.get("kind") == "constant": return lu
    if operation in {"add", "subtract"}:
        if lu != ru: raise ValueError(f"{operation} requires equal units, got {lu!r} and {ru!r}")
        return lu
    return f"{lu}*{ru}" if operation in {"multiply", "dot", "cross"} else f"{lu}/{ru}"


def derive_field(data: Data3D, *, name: str, operation: str, field: str | DerivedField | None = None,
                 left: str | DerivedField | float | int | None = None, right: str | DerivedField | float | int | None = None,
                 component: str | int | None = None, available: Mapping[str, DerivedField] | None = None) -> DerivedField:
    """Create a pointwise derived field without mutating or copying ``data.mesh``.

    Supported operations are ``magnitude``, ``component``, ``add``,
    ``subtract``, ``multiply``, ``divide``, ``dot`` and ``cross``.  Components
    use Cartesian x/y/z (or 0/1/2) and vectors must already be declared
    Cartesian by Data3D v1 metadata.
    """
    _require_data3d_v1(data)
    operation = operation.lower()
    if operation in {"magnitude", "component"}:
        if field is None: raise ValueError(f"{operation} requires field")
        values, descriptor, deps = _field(data, field, available)
        if values.ndim != 2 or values.shape[1] != 3 or descriptor.get("component_system") != "Cartesian":
            raise ValueError(f"{operation} requires a Cartesian three-component vector")
        if operation == "magnitude":
            output = np.linalg.norm(values, axis=1); kind = "scalar"; description = f"Magnitude of {field}"
        else:
            index = {"x": 0, "y": 1, "z": 2}.get(str(component).lower(), component)
            if index not in (0, 1, 2): raise ValueError("component must be x/y/z or 0/1/2")
            output = values[:, int(index)]; kind = "scalar"; description = f"Cartesian component {index} of {field}"
        return DerivedField(name, output, {"kind": kind, "components": 1, "unit": descriptor["unit"], "description": description,
                                           "provenance": "derived", "dependencies": list(deps)}, deps)
    if left is None or right is None: raise ValueError(f"{operation} requires left and right operands")
    a, ad, adeps = _field(data, left, available); b, bd, bdeps = _field(data, right, available)
    if operation in {"add", "subtract", "multiply", "divide"}:
        output = {"add": np.add, "subtract": np.subtract, "multiply": np.multiply, "divide": np.divide}[operation](a, b)
        kind = "vector" if output.ndim == 2 else "scalar"
    elif operation == "dot":
        if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3: raise ValueError("dot requires two matching three-component vectors")
        output = np.einsum("ij,ij->i", a, b); kind = "scalar"
    elif operation == "cross":
        if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3: raise ValueError("cross requires two matching three-component vectors")
        output = np.cross(a, b); kind = "vector"
    else:
        raise ValueError(f"Unsupported operation {operation!r}")
    unit = _unit_binary(ad, bd, operation); deps = tuple(dict.fromkeys((*adeps, *bdeps)))
    descriptor = {"kind": kind, "components": 3 if kind == "vector" else 1, "unit": unit,
                  "description": f"{operation}({left}, {right})", "provenance": "derived", "dependencies": list(deps)}
    if kind == "vector": descriptor["component_system"] = "Cartesian"
    return DerivedField(name, np.asarray(output), descriptor, deps)


def _plane(origin, normal, u_direction=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin = np.asarray(origin, dtype=float); normal = np.asarray(normal, dtype=float)
    if origin.shape != (3,) or normal.shape != (3,) or not np.isfinite(np.r_[origin, normal]).all(): raise ValueError("origin and normal must be finite length-3 vectors")
    norm = np.linalg.norm(normal)
    if norm == 0: raise ValueError("normal must be non-zero")
    n = normal / norm
    if u_direction is None:
        axis = np.eye(3)[np.argmin(np.abs(n))]
        u = np.cross(axis, n)
    else:
        u = np.asarray(u_direction, dtype=float)
        if u.shape != (3,) or not np.isfinite(u).all(): raise ValueError("u_direction must be a finite length-3 vector")
        u = u - np.dot(u, n) * n
    u_norm = np.linalg.norm(u)
    if u_norm == 0: raise ValueError("u_direction cannot be parallel to normal")
    u /= u_norm; v = np.cross(n, u)
    return origin, n, np.column_stack((u, v))


def _attach_fields(data: Data3D, names: Sequence[str], derived: Mapping[str, DerivedField] | None):
    mesh = data.mesh.copy(deep=False)
    descriptors: dict[str, dict[str, Any]] = {}
    for name in names:
        if derived and name in derived:
            mesh.point_data[name] = derived[name].values; descriptors[name] = derived[name].descriptor
        elif name in mesh.point_data:
            descriptors[name] = _descriptor(data, name)
        else: raise KeyError(f"Requested field {name!r} is unavailable")
    return mesh, descriptors


def _source_identity(data: Data3D) -> dict[str, Any]:
    path = Path(data.source) if data.source else None
    result = {"path": str(path) if path else None, "physical_time": data.metadata.get("physical_time"),
              "format": data.metadata.get("format"), "format_version": data.metadata.get("format_version")}
    if path and path.is_file():
        stat = path.stat(); result.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result


def extract_slice(data: Data3D, *, origin, normal, u_direction=None, fields: Sequence[str] | None = None,
                  derived: Mapping[str, DerivedField] | None = None) -> SliceData:
    """Intersect a real VTK volume with an arbitrary plane; never resample holes."""
    _require_data3d_v1(data)
    requested = list(fields or data.mesh.point_data.keys())
    source, descriptors = _attach_fields(data, requested, derived)
    origin, unit_normal, basis = _plane(origin, normal, u_direction)
    result = source.slice(normal=unit_normal, origin=origin)
    # Keep only requested physics fields and explicit local/world coordinates.
    for key in list(result.point_data.keys()):
        if key not in requested: del result.point_data[key]
    delta = np.asarray(result.points) - origin
    result.point_data["plane_u"] = delta @ basis[:, 0]
    result.point_data["plane_v"] = delta @ basis[:, 1]
    metadata = {"format": "pypost-slice", "format_version": 1, "source": _source_identity(data),
                "physical_time": data.metadata["physical_time"], "time_unit": data.metadata["time_unit"],
                "coordinates": data.metadata["coordinates"], "fields": descriptors,
                "normalization": data.metadata.get("normalization", {}),
                "plane": {"origin": origin.tolist(), "normal": unit_normal.tolist(), "basis_u": basis[:, 0].tolist(), "basis_v": basis[:, 1].tolist()},
                "operation": {"name": "extract_slice", "interpolation": "VTK cell intersection / PointData interpolation", "fields": requested}}
    return SliceData(result, metadata)


def sample_line(data: Data3D, *, start, end, n_points: int | None = None, spacing: float | None = None,
                fields: Sequence[str] | None = None, derived: Mapping[str, DerivedField] | None = None) -> Data1D:
    """Sample a 3-D segment; invalid points are NaN and never extrapolated."""
    _require_data3d_v1(data)
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    if start.shape != (3,) or end.shape != (3,) or not np.isfinite(np.r_[start, end]).all() or np.allclose(start, end):
        raise ValueError("start/end must be distinct finite length-3 vectors")
    length = float(np.linalg.norm(end - start))
    if (n_points is None) == (spacing is None): raise ValueError("Specify exactly one of n_points or spacing")
    if spacing is not None:
        if spacing <= 0: raise ValueError("spacing must be positive")
        n_points = int(np.ceil(length / spacing)) + 1
    assert n_points is not None
    if n_points < 2: raise ValueError("n_points must be at least 2")
    requested = list(fields or data.mesh.point_data.keys())
    source, descriptors = _attach_fields(data, requested, derived)
    sampled = source.sample_over_line(start, end, resolution=n_points - 1)
    valid = np.asarray(sampled.point_data.get("vtkValidPointMask", np.ones(n_points, dtype=np.uint8)), dtype=bool)
    coordinates = np.asarray(sampled.points)
    output: dict[str, np.ndarray] = {"x": coordinates[:, 0], "y": coordinates[:, 1], "z": coordinates[:, 2], "valid": valid.astype(np.uint8)}
    units = {"x": data.metadata["coordinates"]["unit"], "y": data.metadata["coordinates"]["unit"], "z": data.metadata["coordinates"]["unit"], "valid": "1"}
    line_descriptors = {}
    for name in requested:
        values = np.asarray(sampled.point_data[name]).copy()
        values[~valid] = np.nan
        output[name] = values; units[name] = descriptors[name]["unit"]; line_descriptors[name] = descriptors[name]
        if values.ndim == 2 and values.shape[1] == 3:
            for index, component in enumerate("xyz"):
                key = f"{name}_{component}"; output[key] = values[:, index]; units[key] = descriptors[name]["unit"]
    s = np.linspace(0.0, length, n_points)
    metadata = {"format": "pypost-data1d-line", "format_version": 1, "source": _source_identity(data),
                "physical_time": data.metadata["physical_time"], "time_unit": data.metadata["time_unit"], "field_descriptors": line_descriptors,
                "normalization": data.metadata.get("normalization", {}),
                "operation": {"name": "sample_line", "start": start.tolist(), "end": end.tolist(), "n_points": n_points,
                              "spacing": length / (n_points - 1), "valid_mask": "valid", "interpolation": "VTK probe; no extrapolation"}}
    return Data1D(s, output, x_name="s", x_unit=data.metadata["coordinates"]["unit"], field_units=units, metadata=metadata, sort=False)


def _scalar_columns(line: Data1D) -> Data1D:
    """Spreadsheet view of a sampled line: vectors are kept as their ``*_x/_y/_z`` scalar columns."""
    fields = {k: v for k, v in line.fields.items() if np.ndim(v) == 1}
    units = {k: u for k, u in line.field_units.items() if k in fields}
    return Data1D(line.x, fields, x_name=line.x_name, x_unit=line.x_unit, field_units=units, metadata=line.metadata, sort=False)


def process_data3d_yaml(path: str | Path) -> dict[str, Path]:
    """Run the concise ``kind: data3d-process`` workflow once per input volume."""
    config_path = Path(path); config = read_yaml(config_path)
    if config.get("kind") != "data3d-process": raise ValueError("Processing YAML needs kind: data3d-process")
    source_value = config.get("input", {}).get("path")
    if not source_value: raise ValueError("Processing YAML needs input.path")
    source = Path(source_value); source = source if source.is_absolute() else config_path.parent / source
    data = Data3D.from_file(source)
    _require_data3d_v1(data)
    derived: dict[str, DerivedField] = {}
    for item in config.get("derived", []):
        if not isinstance(item, dict) or "name" not in item or "operation" not in item: raise ValueError("Each derived item needs name and operation")
        derived[item["name"]] = derive_field(data, available=derived, **item)
    outputs: dict[str, Path] = {}
    for item in config.get("slices", []):
        spec = dict(item); name = spec.pop("name"); output = Path(spec.pop("output")); output = output if output.is_absolute() else config_path.parent / output
        result = extract_slice(data, derived=derived, **spec); result.save(output); outputs[name] = output
    for item in config.get("lines", []):
        spec = dict(item); name = spec.pop("name")
        targets = [spec.pop("output")]
        if "csv" in spec: targets.append(spec.pop("csv"))
        result = sample_line(data, derived=derived, **spec)
        from ..io import save_dataset
        for index, target in enumerate(targets):
            target = Path(target); target = target if target.is_absolute() else config_path.parent / target
            if target.suffix.lower() == ".csv":
                save_dataset(_scalar_columns(result), target, encoding="ascii")
            else:
                save_dataset(result, target)
            outputs[name if index == 0 else f"{name}.csv"] = target
    return outputs
