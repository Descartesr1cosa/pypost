#!/usr/bin/env python3
"""Convert one MPCNS Mercury restart into a self-contained Data3D v1 file.

This is intentionally outside ``sciplot``.  It imports the supplied
``mpcns_post`` reader only while converting, so generic pypost workflows never
learn the Mercury binary, ghost, DEC, Hodge, or topology-alias formats.

The converter uses the solver-provided owner maps and reconstruction operators;
it never deduplicates nodes by coordinates and never averages interface values.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np

# Permit the documented command to run from an editable repository checkout;
# installed packages already resolve normally and are not shadowed otherwise.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from sciplot import Data3D, validate_dataset


def _load_mercury_api(source: Path):
    if not source.is_dir():
        raise FileNotFoundError(f"Mercury Postprocess/src directory not found: {source}")
    sys.path.insert(0, str(source))
    try:
        from mpcns_post import MPCNSCase
        from mpcns_post.tecplot import project_cell_values_to_nodes
    except ImportError as exc:
        raise ImportError(f"Cannot import supplied mpcns_post from {source}") from exc
    return MPCNSCase, project_cell_values_to_nodes


def _hex_connectivity(case):
    """Build owner-only VTK hexes from Mercury's authoritative block maps.

    The structured maps are global-ID mapped by ``mpcns_post``.  A cell is
    emitted only by its declared owner.  Repeated node IDs in a would-be hex
    (typically an unhandled polar collapse) are a hard error, never a skipped
    cell or a silently degenerate VTK hexahedron.
    """
    node_blocks = {(block.rank, block.block_id): block for block in case.iter_blocks("node")}
    cells: list[int] = []
    source_blocks: list[int] = []
    source_ranks: list[int] = []
    source_local_blocks: list[int] = []
    bad: list[str] = []
    by_type: Counter[str] = Counter()
    for cell_block in case.iter_blocks("cell"):
        try:
            node_block = node_blocks[(cell_block.rank, cell_block.block_id)]
        except KeyError as exc:
            raise ValueError(f"rank {cell_block.rank} block {cell_block.block_id}: no matching node map") from exc
        cell_shape = tuple(map(int, cell_block.logical_shape))
        node_shape = tuple(map(int, node_block.logical_shape))
        expected = tuple(size + 1 for size in cell_shape)
        if node_shape != expected:
            raise ValueError(
                f"rank {cell_block.rank} block {cell_block.block_id}: node shape {node_shape} "
                f"does not bound cell shape {cell_shape}; explicit cell topology is required"
            )
        nodes = np.asarray(node_block.indices, dtype=np.int64).reshape(node_shape, order="F")
        owner = np.asarray(cell_block.owner_mask, dtype=bool).reshape(cell_shape, order="F")
        for i, j, k in np.argwhere(owner):
            ids = np.asarray((
                nodes[i, j, k], nodes[i + 1, j, k], nodes[i + 1, j + 1, k], nodes[i, j + 1, k],
                nodes[i, j, k + 1], nodes[i + 1, j, k + 1], nodes[i + 1, j + 1, k + 1], nodes[i, j + 1, k + 1],
            ), dtype=np.int64)
            if np.unique(ids).size != 8:
                bad.append(f"rank={cell_block.rank} block={cell_block.block_id} logical_cell=({i},{j},{k})")
                continue
            cells.extend((8, *ids.tolist()))
            # Local block identifiers repeat across ranks. Keep both fields
            # and a deterministic composite identifier for simple consumers.
            source_blocks.append(cell_block.rank * 1_000_000 + cell_block.block_id)
            source_ranks.append(cell_block.rank)
            source_local_blocks.append(cell_block.block_id)
            by_type["VTK_HEXAHEDRON"] += 1
    if bad:
        preview = "; ".join(bad[:8])
        raise ValueError(
            f"{len(bad)} collapsed/invalid owner cells cannot be represented as hexahedra; "
            f"no file was written. First cases: {preview}"
        )
    if not source_blocks:
        raise ValueError("Mercury topology produced no owner volume cells")
    return (np.asarray(cells, dtype=np.int64), np.full(len(source_blocks), 12, dtype=np.uint8),
            np.asarray(source_blocks, dtype=np.int64), np.asarray(source_ranks, dtype=np.int32),
            np.asarray(source_local_blocks, dtype=np.int32), dict(by_type))


def _descriptor(kind: str, unit: str, description: str, *, provenance: str = "reconstructed") -> dict:
    result = {"kind": kind, "components": {"scalar": 1, "vector": 3}[kind], "unit": unit,
              "description": description, "provenance": provenance}
    if kind == "vector":
        result["component_system"] = "Cartesian"
    return result


def convert_legacy_eager(static_dir: str | Path, data_dir: str | Path, output: str | Path, *, mpcns_src: str | Path | None = None) -> Path:
    """Perform the one-time Mercury-specific conversion and validate its v1 result."""
    static_dir = Path(static_dir).resolve()
    data_dir = Path(data_dir).resolve()
    source = Path(mpcns_src).resolve() if mpcns_src else static_dir.parent / "Postprocess" / "src"
    MPCNSCase, project_cell_values_to_nodes = _load_mercury_api(source)
    case = MPCNSCase.load(static_dir, data_dir=data_dir)
    fields = case.dynamic_fields
    assert fields is not None

    # All values below are explicitly reconstructed from solver-defined
    # operators before they cross the Data3D boundary.
    h, na = case.H, case.Na
    units = case.unit_converter
    cell_values = {
        "H_density": (units.convert(h.density, "density", "kg/m^3"), h.valid_mask, "kg/m^3", "H+ mass density"),
        "H_velocity": (units.convert(h.velocity, "velocity", "km/s"), h.valid_mask, "km/s", "H+ bulk velocity"),
        "H_pressure": (units.convert(h.pressure, "pressure", "nPa"), h.valid_mask, "nPa", "H+ thermal pressure"),
        "Na_density": (units.convert(na.density, "density", "kg/m^3"), na.valid_mask, "kg/m^3", "Na+ mass density"),
        "Na_velocity": (units.convert(na.velocity, "velocity", "km/s"), na.valid_mask, "km/s", "Na+ bulk velocity"),
        "Na_pressure": (units.convert(na.pressure, "pressure", "nPa"), na.valid_mask, "nPa", "Na+ thermal pressure"),
        "B_induced": (units.convert(case.reconstruct_B_cell(fields), "magnetic_field", "nT"), None, "nT",
                      "Induced magnetic field reconstructed from oriented Mercury face 2-form flux"),
    }
    if case.reconstruction.B_face_to_J_edge is not None:
        cell_values["J_induced"] = (case.compute_current_dec(unit="nA/m^2"), None, "nA/m^2",
                                    "Induced current reconstructed by Mercury DEC/Hodge operators before nodal projection")

    points = np.asarray(case.geometry.node_xyz, dtype=np.float64)
    point_fields: dict[str, np.ndarray] = {}
    field_metadata: dict[str, dict] = {}
    for name, (values, mask, unit, description) in cell_values.items():
        nodal = np.asarray(project_cell_values_to_nodes(case, values, valid_mask=mask), dtype=np.float64)
        point_fields[name] = nodal
        field_metadata[name] = _descriptor("vector" if nodal.ndim == 2 else "scalar", unit, description)
        if mask is not None:
            field_metadata[name]["missing_data"] = "NaN where no valid incident fluid cell exists"

    cells, cell_types, block_ids, ranks, local_blocks, cell_types_report = _hex_connectivity(case)
    import pyvista as pv
    mesh = pv.UnstructuredGrid(cells, cell_types, points)
    for name, values in point_fields.items():
        mesh.point_data[name] = values
    mesh.cell_data["SourceBlockId"] = block_ids
    mesh.cell_data["SourceRank"] = ranks
    mesh.cell_data["SourceLocalBlockId"] = local_blocks

    report = {
        "original_local_nodes": int(sum(len(g.node_gid) for g in case.rank_geometries)),
        "unique_global_nodes": int(points.shape[0]),
        "merged_interface_aliases": int(sum(len(g.node_gid) for g in case.rank_geometries) - points.shape[0]),
        "cells_by_type": cell_types_report,
        "invalid_or_degenerate_cells": 0,
        "skipped_cells": 0,
        "field_consistency": "Owner/global IDs and mpcns_post reconstruction operators; no coordinate merge or interface averaging",
    }
    metadata = Data3D.standard_metadata(
        physical_time=float(case.latest_restart[0].time), time_unit="s", coordinate_unit="R_M",
        source={"name": "mercury_to_data3d", "version": "1", "mesh_uuid": case.manifest.mesh_uuid,
                "case_uuid": case.manifest.case_uuid, "mercury_format": f"{case.manifest.format_name} v{case.manifest.format_version}"},
        fields=field_metadata,
        cell_fields={"SourceBlockId": {"role": "source_block_id"}, "SourceRank": {"role": "source_rank"},
                     "SourceLocalBlockId": {"role": "source_local_block_id"}},
        normalization={**dict(case.manifest.normalization), "coordinate_reference": "Mercury radius R_M"},
        conversion={"converter": "examples/converters/mercury/mercury_to_data3d.py", "report": report,
                    "B_reconstruction": "mpcns_post B_face_to_cell_cartesian", "cell_to_node": "mpcns_post cell_scalar_to_node"},
    )
    target = Data3D(mesh, source="Mercury MPCNS", time=float(case.latest_restart[0].time), metadata=metadata).save_data3d_v1(output)
    result = validate_dataset(target, deep=True)
    if not result["valid"]:
        raise RuntimeError("Data3D validation failed after write: " + "; ".join(result["issues"]))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-dir", required=True, type=Path, help="Mercury DATA_bin directory containing manifest.json")
    parser.add_argument("--data-dir", required=True, type=Path, help="One restart directory containing flow_field####.bin")
    parser.add_argument("--output", required=True, type=Path, help="Output Data3D v1 .vtu")
    parser.add_argument("--fields", default="B_induced,H_density,H_velocity,H_pressure,Na_density,Na_velocity,Na_pressure",
                        help="Comma-separated confirmed Data3D fields; use --fields B_induced for the smallest output")
    parser.add_argument("--temp-dir", type=Path, help="Directory for disk-backed temporary buffers")
    parser.add_argument("--memory-budget-gb", type=float, default=4.0, help="Hard observed-RSS ceiling (default: 4 GiB)")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary buffers and diagnostics.json after completion/failure")
    parser.add_argument("--verify-readback", action="store_true", help="Use PyVista to reopen the final temporary VTU; may need output-sized RAM")
    args = parser.parse_args(argv)
    from low_memory import convert
    selected = [item.strip() for item in args.fields.split(",") if item.strip()]
    print(convert(static_dir=args.static_dir.resolve(), data_dir=args.data_dir.resolve(), output=args.output.resolve(), fields=selected,
                  temp_dir=args.temp_dir.resolve() if args.temp_dir else None, memory_budget_gb=args.memory_budget_gb,
                  keep_temp=args.keep_temp, verify_readback=args.verify_readback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
