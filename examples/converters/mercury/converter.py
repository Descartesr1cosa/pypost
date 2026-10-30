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
from typing import Any

import numpy as np
import yaml

# Permit the documented command to run from an editable repository checkout;
# installed packages already resolve normally and are not shadowed otherwise.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from sciplot import Data3D, validate_dataset


_RAW_FIELDS = {
    "B_induced": {"B_xi", "B_eta", "B_zeta"},
    "H_density": {"U_H"}, "H_velocity": {"U_H"}, "H_pressure": {"U_H"},
    "Na_density": {"U_Na"}, "Na_velocity": {"U_Na"}, "Na_pressure": {"U_Na"},
}
_DEFAULT_FIELDS = tuple(_RAW_FIELDS)


def _resolve(value: str | Path, base: Path) -> Path:
    """Resolve a configured path with no dependence on the current directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load and normalize one ``kind: mercury-data3d`` configuration.

    ``paths.data_root`` is relative to this YAML file.  Every relative input,
    output, and temporary path is then relative to that resolved root.
    """
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Mercury configuration does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("kind") != "mercury-data3d":
        raise ValueError("Mercury YAML requires `kind: mercury-data3d`")
    try:
        root = _resolve(raw["paths"]["data_root"], config_path.parent).resolve()
        input_cfg = raw["input"]
        output_cfg = raw["output"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Mercury YAML requires paths.data_root, input, and output.path") from exc
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields or not all(isinstance(item, str) for item in fields):
        raise ValueError("Mercury YAML fields must be a non-empty list of field names")
    if not isinstance(input_cfg, dict) or not input_cfg.get("static_dir") or not input_cfg.get("data_dir"):
        raise ValueError("Mercury YAML requires non-empty input.static_dir and input.data_dir")
    if not isinstance(output_cfg, dict) or not output_cfg.get("path"):
        raise ValueError("Mercury YAML requires a non-empty output.path")
    runtime = raw.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ValueError("Mercury YAML runtime must be a mapping")
    return {
        "config_path": config_path,
        "data_root": root,
        "static_dir": _resolve(input_cfg.get("static_dir", ""), root).resolve(),
        "data_dir": _resolve(input_cfg.get("data_dir", ""), root).resolve(),
        "output": _resolve(output_cfg.get("path", ""), root).resolve(),
        "fields": fields,
        "temp_dir": _resolve(runtime["temp_dir"], root).resolve() if runtime.get("temp_dir") else None,
        "memory_budget_gb": runtime.get("memory_budget_gb", 4.0),
        "keep_temp": bool(runtime.get("keep_temp", False)),
        "verify_readback": bool(runtime.get("verify_readback", False)),
        "overwrite": bool(output_cfg.get("overwrite", False)),
    }


def validate_conversion_request(*, static_dir: Path, data_dir: Path, output: Path, fields: list[str],
                                temp_dir: Path | None, memory_budget_gb: float | None,
                                overwrite: bool = False) -> None:
    """Reject configuration/path errors before a rank file is streamed."""
    from .low_memory import SUPPORTED_FIELDS
    from .streaming import load_manifest

    unknown = sorted(set(fields) - set(SUPPORTED_FIELDS))
    if unknown:
        raise ValueError(f"Unknown output fields: {unknown}; choose from {list(SUPPORTED_FIELDS)}")
    if len(set(fields)) != len(fields):
        raise ValueError("Mercury YAML fields must not contain duplicates")
    if memory_budget_gb is not None and float(memory_budget_gb) <= 0:
        raise ValueError("runtime.memory_budget_gb must be positive")
    if output.suffix.lower() != ".vtu":
        raise ValueError(f"Output must be a .vtu file path, not {output}")
    if output.exists() and output.is_dir():
        raise IsADirectoryError(f"Output must be a .vtu file, not an existing directory: {output}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {output}; set output.overwrite: true explicitly")
    if not static_dir.is_dir() or not data_dir.is_dir():
        raise FileNotFoundError(f"Mercury input directories must exist: static={static_dir}, data={data_dir}")
    for protected in (static_dir, data_dir):
        if output == protected or protected in output.parents:
            raise ValueError(f"Output must be outside Mercury input directory: {protected}")
        if temp_dir is not None and (temp_dir == protected or protected in temp_dir.parents):
            raise ValueError(f"runtime.temp_dir must be outside Mercury input directory: {protected}")
    manifest = load_manifest(static_dir)
    try:
        ranks, files = int(manifest["number_of_ranks"]), manifest["files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Mercury manifest lacks a valid number_of_ranks/files mapping") from exc
    if ranks <= 0 or not isinstance(files, dict):
        raise ValueError("Mercury manifest must declare at least one rank and its static files")
    for category in ("geometry", "topology", "reconstruction"):
        entries = files.get(category)
        if not isinstance(entries, list) or len(entries) != ranks:
            raise ValueError(f"Mercury manifest has invalid {category} rank list")
        missing = next((static_dir / item for item in entries if not (static_dir / item).is_file()), None)
        if missing:
            raise FileNotFoundError(f"Mercury static input is missing: {missing}")
    missing_restart = next((data_dir / f"flow_field{rank:04d}.bin" for rank in range(ranks)
                            if not (data_dir / f"flow_field{rank:04d}.bin").is_file()), None)
    if missing_restart:
        raise FileNotFoundError(f"Mercury restart input is missing: {missing_restart}")
    available = {str(item.get("name")) for item in manifest.get("existing_dynamic_data", {}).get("fields", [])}
    required = set().union(*(_RAW_FIELDS[field] for field in fields))
    if missing := sorted(required - available):
        raise ValueError(f"Mercury manifest does not provide raw field(s) required by {fields}: {missing}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if temp_dir is not None:
        if temp_dir.exists() and not temp_dir.is_dir():
            raise NotADirectoryError(f"runtime.temp_dir is not a directory: {temp_dir}")
        temp_dir.mkdir(parents=True, exist_ok=True)


def convert_from_config(path: str | Path) -> Path:
    """Run the existing low-memory converter from a normalized YAML request."""
    request = load_yaml_config(path)
    validate_conversion_request(**{key: request[key] for key in (
        "static_dir", "data_dir", "output", "fields", "temp_dir", "memory_budget_gb", "overwrite")})
    from .low_memory import convert
    return convert(**{key: request[key] for key in (
        "static_dir", "data_dir", "output", "fields", "temp_dir", "memory_budget_gb", "keep_temp", "verify_readback")})


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
        conversion={"converter": "examples.converters.mercury", "report": report,
                    "B_reconstruction": "mpcns_post B_face_to_cell_cartesian", "cell_to_node": "mpcns_post cell_scalar_to_node"},
    )
    target = Data3D(mesh, source="Mercury MPCNS", time=float(case.latest_restart[0].time), metadata=metadata).save_data3d_v1(output)
    result = validate_dataset(target, deep=True)
    if not result["valid"]:
        raise RuntimeError("Data3D validation failed after write: " + "; ".join(result["issues"]))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="mercury-data3d YAML configuration (recommended)")
    parser.add_argument("--static-dir", type=Path, help="Mercury DATA_bin directory containing manifest.json")
    parser.add_argument("--data-dir", type=Path, help="One restart directory containing flow_field####.bin")
    parser.add_argument("--output", type=Path, help="Output Data3D v1 .vtu")
    parser.add_argument("--fields", default="B_induced,H_density,H_velocity,H_pressure,Na_density,Na_velocity,Na_pressure",
                        help="Comma-separated confirmed Data3D fields; use --fields B_induced for the smallest output")
    parser.add_argument("--temp-dir", type=Path, help="Directory for disk-backed temporary buffers")
    parser.add_argument("--memory-budget-gb", type=float, default=4.0, help="Hard observed-RSS ceiling (default: 4 GiB)")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary buffers and diagnostics.json after completion/failure")
    parser.add_argument("--verify-readback", action="store_true", help="Use PyVista to reopen the final temporary VTU; may need output-sized RAM")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing .vtu result")
    args = parser.parse_args(argv)
    if args.config:
        if any(value is not None for value in (args.static_dir, args.data_dir, args.output)):
            parser.error("--config cannot be combined with --static-dir, --data-dir, or --output")
        print(convert_from_config(args.config))
        return 0
    if any(value is None for value in (args.static_dir, args.data_dir, args.output)):
        parser.error("use --config CONFIG.yml or supply --static-dir, --data-dir, and --output")
    selected = [item.strip() for item in args.fields.split(",") if item.strip()]
    request = {"static_dir": args.static_dir.resolve(), "data_dir": args.data_dir.resolve(), "output": args.output.resolve(),
               "fields": selected, "temp_dir": args.temp_dir.resolve() if args.temp_dir else None,
               "memory_budget_gb": args.memory_budget_gb, "overwrite": args.overwrite}
    validate_conversion_request(**request)
    from .low_memory import convert
    print(convert(**{key: request[key] for key in ("static_dir", "data_dir", "output", "fields", "temp_dir", "memory_budget_gb")},
                  keep_temp=args.keep_temp, verify_readback=args.verify_readback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
