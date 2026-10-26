"""Human-readable summaries of pypost's standard data representations."""
from __future__ import annotations

from pathlib import Path
import numpy as np
from .data import Data1D, Data3D
from .io import inspect_dataset


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
    """Human-readable compatibility wrapper around the structured report API."""
    report = inspect_dataset(path)
    dimension = report["dimension"]
    if dimension == "1d":
        coordinate = report["coordinate"]
        lines = [f"1-D {'CSV' if report['encoding'] == 'ascii' else 'NPZ'}: {report['path']}",
                 f"format: {report['format']} v{report['format_version']}; encoding: {report['encoding']}",
                 f"rows: {report['points']}", f"coordinate: {coordinate['name']} {_range([]) if 'range' not in coordinate else coordinate['range']}"]
    else:
        lines = [f"{dimension.upper()} dataset: {report['path']}",
                 f"format: {report['format']} v{report['format_version']}; encoding: {report['encoding']}",
                 f"mesh: {report.get('mesh_type')}; points: {report.get('points', 0)}; cells: {report.get('cells', 0)}"]
    for field in report["fields"]:
        unit = f" [{field['unit']}]" if field.get("unit") else ""
        lines.append(f"field {field['location']} {field['name']}{unit}: shape={tuple(field['shape'])}; dtype={field['dtype']}; components={field['components']}; nan={field['nan']}; inf={field['inf']}")
    return "\n".join(lines)
