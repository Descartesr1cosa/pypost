"""Human-readable summaries of pypost's standard data representations."""
from __future__ import annotations

from pathlib import Path
import numpy as np
from .data import Data1D, Data3D


def _range(values) -> str:
    values = np.asarray(values)
    if not values.size:
        return "empty"
    try:
        return f"[{np.nanmin(values):.6g}, {np.nanmax(values):.6g}]"
    except (TypeError, ValueError):
        return "non-numeric"


def inspect_1d(path: str | Path) -> str:
    data = Data1D.from_file(path)
    lines = [f"1-D CSV: {Path(path)}", f"rows: {len(data.x)}", f"coordinate: {data.x_name} {_range(data.x)}"]
    for name, values in data.fields.items():
        unit = f" [{data.field_units[name]}]" if name in data.field_units else ""
        lines.append(f"field point {name}{unit}: {_range(values)}")
    return "\n".join(lines)


def _dataset_summary(mesh, indent: str = "") -> list[str]:
    import pyvista as pv
    if isinstance(mesh, pv.MultiBlock):
        lines = [f"{indent}MultiBlock: {mesh.n_blocks} blocks"]
        for index, block in enumerate(mesh):
            lines.append(f"{indent}block {index}:")
            lines += _dataset_summary(block, indent + "  ") if block is not None else [f"{indent}  empty"]
        return lines
    lines = [f"{indent}mesh: {type(mesh).__name__}; points: {mesh.n_points}; cells: {mesh.n_cells}; bounds: {tuple(round(float(x), 6) for x in mesh.bounds)}"]
    for location, arrays in (("point", mesh.point_data), ("cell", mesh.cell_data)):
        for name in arrays:
            values = np.asarray(arrays[name])
            components = values.shape[1] if values.ndim > 1 else 1
            lines.append(f"{indent}field {location} {name}: components={components}; range={_range(values)}")
    return lines


def inspect_3d(path: str | Path) -> str:
    data = Data3D.from_file(path)
    return "\n".join([f"3-D VTK: {Path(path)}", *_dataset_summary(data.mesh)])


def inspect_path(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() in {".csv", ".txt", ".xy", ".dat"}:
        return inspect_1d(path)
    return inspect_3d(path)
