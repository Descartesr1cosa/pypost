"""Small YAML-driven workflow helpers used by the standalone scripts.

The configuration is intentionally declarative: it names fields and simple
arithmetic only; it never executes Python expressions from YAML.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import numpy as np
import yaml
from .data import Data1D, Data2D, Data3D


def read_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        result = yaml.safe_load(handle) or {}
    if not isinstance(result, dict):
        raise ValueError("The root YAML value must be a mapping")
    return result


def load_data(spec: dict[str, Any]):
    """Load a normalized object from a concise ``input`` YAML mapping."""
    dimension = str(spec["dimension"]).lower().replace("d", "")
    path = spec["path"]
    if dimension == "1":
        if str(path).lower().endswith(".npz"):
            from .io import load_dataset
            result = load_dataset(path)
            if not isinstance(result, Data1D): raise TypeError(f"Expected 1-D NPZ dataset, got {type(result).__name__}")
            return result
        return Data1D.from_file(path, x=spec.get("x"))
    if dimension == "2":
        return Data2D.from_npz(path) if str(path).lower().endswith(".npz") else Data2D.from_vtk(path)
    if dimension == "3":
        return Data3D.from_file(path, time=spec.get("time"), patches=spec.get("patches"))
    raise ValueError("input.dimension must be 1, 2, or 3")


def save_data(data, path: str | Path) -> None:
    # Legacy workflow paths retain their familiar extension behavior. New
    # converter code should call sciplot.io.save_dataset explicitly.
    path = Path(path)
    if isinstance(data, Data1D):
        if path.suffix.lower() == ".npz":
            from .io import save_dataset
            save_dataset(data, path, encoding="binary")
            return
        data.save_csv(path)
    elif isinstance(data, Data2D):
        if path.suffix.lower() != ".npz":
            raise ValueError("Data2D processed data must be saved as .npz")
        data.save_npz(path)
    elif isinstance(data, Data3D):
        data.save(path)
    else:
        raise TypeError(f"Unsupported data object: {type(data)!r}")


def apply_calculations(data, steps: list[dict[str, Any]]):
    """Add derived scalar/vector fields using scale, offset, or magnitude."""
    for step in steps:
        source, target = step["field"], step.get("output", step["field"])
        op, location = step.get("operation", "scale"), step.get("location")
        if isinstance(data, Data1D):
            values = data.fields[source]
            data.fields[target] = _calculate(values, op, step)
        elif isinstance(data, Data2D):
            coords, values, actual_location = data.field(source)
            if location and location != actual_location:
                raise ValueError(f"{source!r} is {actual_location}-located, not {location}-located")
            destination = data.point_fields if actual_location == "point" else data.cell_fields
            destination[target] = _calculate(values, op, step)
        elif isinstance(data, Data3D):
            if location not in ("point", "cell"):
                raise ValueError("3-D calculation needs explicit location: point or cell")
            arrays = data.mesh.point_data if location == "point" else data.mesh.cell_data
            if source not in arrays:
                raise KeyError(f"{source!r} is not {location}-located")
            arrays[target] = _calculate(arrays[source], op, step)
        else:
            raise TypeError(type(data))
    return data


def _calculate(values, operation: str, step: dict[str, Any]):
    values = np.asarray(values)
    if operation == "scale": return values * float(step.get("factor", 1.0))
    if operation == "offset": return values + float(step.get("value", 0.0))
    if operation == "magnitude": return np.linalg.norm(values, axis=-1)
    raise ValueError("operation must be scale, offset, or magnitude")
