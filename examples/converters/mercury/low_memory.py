"""Disk-backed MPCNS v3 to Data3D v1 conversion pipeline."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import shutil
import tempfile
from typing import Any

import numpy as np

from sciplot import Data3D

from streaming import Diagnostics, geometry, load_manifest, reconstruction, restart_fields, topology_maps, write_vtu


_FIELDS = {
    "H_density": ("U_H", "scalar"), "H_velocity": ("U_H", "vector"), "H_pressure": ("U_H", "scalar"),
    "Na_density": ("U_Na", "scalar"), "Na_velocity": ("U_Na", "vector"), "Na_pressure": ("U_Na", "scalar"),
    "B_induced": ("B", "vector"),
}


def _map(path: Path, dtype, shape, fill=None) -> np.memmap:
    value = np.memmap(path, dtype=dtype, mode="w+", shape=shape)
    if fill is not None:
        value[...] = fill; value.flush()
    return value


def _descriptor(name: str) -> dict[str, Any]:
    unit = {"H_density": "kg/m^3", "Na_density": "kg/m^3", "H_velocity": "km/s", "Na_velocity": "km/s",
            "H_pressure": "nPa", "Na_pressure": "nPa", "B_induced": "nT"}[name]
    kind = _FIELDS[name][1]
    result = {"kind": kind, "components": 3 if kind == "vector" else 1, "unit": unit, "provenance": "reconstructed",
              "description": {"B_induced": "Induced Cartesian magnetic field reconstructed from Mercury oriented face 2-form flux"}.get(name, f"Mercury {name} projected from solver cell state to globally unique nodes"),
              "missing_data": "NaN where no valid incident physical cell exists"}
    if kind == "vector": result["component_system"] = "Cartesian"
    return result


def _primitive(raw: np.ndarray, name: str, normalization: dict, gamma: float) -> np.ndarray:
    rho = raw[:, 0]
    valid = np.isfinite(raw).all(axis=1) & (rho > 0)
    if name.endswith("density"):
        out = rho * normalization["density_ref"]
    elif name.endswith("velocity"):
        out = np.full((len(raw), 3), np.nan); out[valid] = raw[valid, 1:4] / rho[valid, None] * normalization["velocity_ref"] * 1e-3
    else:
        out = np.full(len(raw), np.nan)
        velocity2 = np.zeros(len(raw)); velocity2[valid] = np.sum((raw[valid, 1:4] / rho[valid, None]) ** 2, axis=1)
        out[valid] = (gamma - 1.0) * (raw[valid, 4] - .5 * rho[valid] * velocity2[valid]) * normalization["pressure_ref"] * 1e9
    out[~valid] = np.nan
    return out


def _operator_apply(offsets: np.ndarray, source: np.ndarray, weights: np.ndarray, components: int) -> tuple[np.ndarray, np.ndarray]:
    rows = np.repeat(np.arange(len(offsets) - 1), np.diff(offsets))
    source = source.reshape((-1, components)) if components > 1 else source.reshape((-1, 1))
    finite = np.isfinite(source)
    numerator = np.empty((len(offsets) - 1, components))
    denominator = np.empty_like(numerator)
    for component in range(components):
        numerator[:, component] = np.bincount(rows, weights=weights * np.where(finite[:, component], source[:, component], 0.0), minlength=len(numerator))
        denominator[:, component] = np.bincount(rows, weights=weights * finite[:, component], minlength=len(numerator))
    return numerator, denominator


def convert(*, static_dir: Path, data_dir: Path, output: Path, fields: list[str], temp_dir: Path | None,
            memory_budget_gb: float | None, keep_temp: bool = False, verify_readback: bool = False) -> Path:
    """Convert with bounded RAM; all full-size buffers are disk-backed memmaps."""
    unknown = sorted(set(fields) - set(_FIELDS))
    if unknown: raise ValueError(f"Unknown output fields: {unknown}; choose from {sorted(_FIELDS)}")
    manifest = load_manifest(static_dir)
    diagnostics = Diagnostics(memory_budget_gb)
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = temp_dir or output.parent
    work = Path(tempfile.mkdtemp(prefix="mercury-data3d-", dir=parent))
    try:
        ranks = int(manifest["number_of_ranks"]); files = manifest["files"]
        # Phase A1: counts and dense direct-ID map feasibility, one rank at a time.
        node_count = cell_count = node_max = cell_max = 0
        for rank in range(ranks):
            node_gid, _xyz, cell_gid = geometry(static_dir / files["geometry"][rank], manifest)
            node_count += len(node_gid); cell_count += len(cell_gid)
            node_max = max(node_max, int(node_gid.max(initial=-1))); cell_max = max(cell_max, int(cell_gid.max(initial=-1)))
            diagnostics.event("scan_geometry", rank=rank, processed_nodes=node_count, processed_cells=cell_count)
        if node_max > max(4 * node_count, 1) or cell_max > max(4 * cell_count, 1):
            raise ValueError("sparse global IDs require an external sorted index; this case exceeds safe direct-index density")
        node_index = _map(work / "node-index.i64", "int64", node_max + 1, -1)
        cell_index = _map(work / "cell-index.i64", "int64", cell_max + 1, -1)
        points = _map(work / "points.f64", "float64", (node_count, 3))
        # Deterministic rank-order allocation from solver owner IDs, not coordinates.
        node_cursor = cell_cursor = 0
        for rank in range(ranks):
            node_gid, xyz, cell_gid = geometry(static_dir / files["geometry"][rank], manifest)
            if np.any(node_index[node_gid] >= 0) or np.any(cell_index[cell_gid] >= 0):
                raise ValueError(f"rank {rank}: duplicate purported owner global IDs")
            node_index[node_gid] = np.arange(node_cursor, node_cursor + len(node_gid)); points[node_cursor:node_cursor + len(node_gid)] = xyz
            cell_index[cell_gid] = np.arange(cell_cursor, cell_cursor + len(cell_gid)); node_cursor += len(node_gid); cell_cursor += len(cell_gid)
            diagnostics.event("index_geometry", rank=rank, processed_nodes=node_cursor, processed_cells=cell_cursor)
        if (node_cursor, cell_cursor) != (node_count, cell_count): raise AssertionError("owner index cursor mismatch")

        # Phase A2: count owner cells and determine the global B-face ID span.
        physical_cells = 0; face_max = -1; local_nodes = 0; alias_nodes = 0
        for rank in range(ranks):
            maps = topology_maps(static_dir / files["topology"][rank], manifest)
            physical_cells += sum(int(item.owners.sum()) for item in maps if item.location == "cell")
            for item in maps:
                if item.location == "node": local_nodes += len(item.gids); alias_nodes += len(item.gids) - int(item.owners.sum())
                if item.location.startswith("face_"): face_max = max(face_max, int(item.gids.max(initial=-1)))
            diagnostics.event("scan_topology", rank=rank, processed_cells=physical_cells)
        if physical_cells != cell_count:
            raise ValueError(f"owner local-map cells {physical_cells} != owner geometry cells {cell_count}")
        cells = _map(work / "connectivity.i64", "int64", physical_cells * 8)
        offsets = _map(work / "offsets.i64", "int64", physical_cells)
        types = _map(work / "types.u8", "uint8", physical_cells)
        source_block = _map(work / "source-block.i64", "int64", physical_cells)
        source_rank = _map(work / "source-rank.i32", "int32", physical_cells)
        source_local = _map(work / "source-local.i32", "int32", physical_cells)
        # Phase A3: real global connectivity.  No geometric merging and no skipped invalid cell.
        cursor = 0; invalid_cells: list[str] = []
        for rank in range(ranks):
            maps = topology_maps(static_dir / files["topology"][rank], manifest); nodes = {x.block: x for x in maps if x.location == "node"}
            for block in (x for x in maps if x.location == "cell"):
                node = nodes.get(block.block)
                if node is None or node.shape != tuple(x + 1 for x in block.shape): raise ValueError(f"rank {rank} block {block.block}: incompatible node/cell maps")
                nids = node_index[node.gids].reshape(node.shape, order="F")
                if np.any(nids < 0): raise ValueError(f"rank {rank} block {block.block}: topology references absent owner node")
                owners = block.owners.reshape(block.shape, order="F")
                for i, j, k in np.argwhere(owners):
                    ids = (nids[i,j,k], nids[i+1,j,k], nids[i+1,j+1,k], nids[i,j+1,k], nids[i,j,k+1], nids[i+1,j,k+1], nids[i+1,j+1,k+1], nids[i,j+1,k+1])
                    if len(set(map(int, ids))) != 8: invalid_cells.append(f"rank {rank} block {block.block} cell ({i},{j},{k})"); continue
                    cells[cursor * 8:(cursor + 1) * 8] = ids; offsets[cursor] = (cursor + 1) * 8; types[cursor] = 12
                    source_block[cursor] = rank * 1_000_000 + block.block; source_rank[cursor] = rank; source_local[cursor] = block.block; cursor += 1
            diagnostics.event("build_connectivity", rank=rank, processed_cells=cursor)
        if invalid_cells or cursor != physical_cells:
            raise ValueError(f"invalid axis/degenerate cells={len(invalid_cells)}; first={invalid_cells[:4]}; no output written")

        # Full-size on-disk cell fields and global oriented B face store.
        cell_values = {name: _map(work / f"cell-{name}.f64", "float64", (cell_count, 3) if _FIELDS[name][1] == "vector" else cell_count, np.nan) for name in fields}
        b_faces = _map(work / "b-faces.f64", "float64", face_max + 1, np.nan) if "B_induced" in fields else None
        time_value = step = None
        requested_raw = {value[0] for name, value in _FIELDS.items() if name in fields and value[0] != "B"}
        if b_faces is not None: requested_raw.update({"B_xi", "B_eta", "B_zeta"})
        # Phase B1: stream restart blocks into global owner-ID storage.
        for rank in range(ranks):
            maps = {(item.block, item.location): item for item in topology_maps(static_dir / files["topology"][rank], manifest)}
            def consume(name, block_id, lo, _hi, values):
                if values is None: return
                location = {"U_H": "cell", "U_Na": "cell", "B_xi": "face_xi", "B_eta": "face_eta", "B_zeta": "face_zeta"}[name]
                item = maps.get((block_id, location))
                if item is None: raise ValueError(f"rank {rank} block {block_id}: missing {location} map")
                sl = tuple(slice(-lo[d], -lo[d] + item.shape[d]) for d in range(3))
                local = values[sl].reshape((-1, values.shape[-1]), order="F"); owner = item.owners
                gids = item.gids[owner]
                if name.startswith("B_"):
                    assert b_faces is not None
                    incoming = local[owner, 0] * item.signs[owner]
                    existing = b_faces[gids]; conflict = np.isfinite(existing) & ~np.isclose(existing, incoming, rtol=1e-10, atol=1e-12)
                    if np.any(conflict): raise ValueError(f"rank {rank}: oriented B alias mismatch (max={np.max(np.abs(existing[conflict]-incoming[conflict]))})")
                    b_faces[gids] = incoming
                    return
                for output_name, (raw_name, _kind) in _FIELDS.items():
                    if output_name in cell_values and raw_name == name:
                        cell_values[output_name][cell_index[gids]] = _primitive(local[owner], output_name, manifest["normalization"], manifest["physical_constants"]["gamma"])
            actual_step, actual_time = restart_fields(data_dir / f"flow_field{rank:04d}.bin", manifest, requested_raw, consume)
            if time_value is None: step, time_value = actual_step, actual_time
            elif (step, time_value) != (actual_step, actual_time): raise ValueError("restart rank step/time mismatch")
            diagnostics.event("stream_restart", rank=rank, processed_cells=cell_count)

        # Phase B2: B face 2-form -> Cartesian cell B with the supplied per-rank operator.
        if b_faces is not None:
            bsum = _map(work / "b-cell-sum.f64", "float64", (cell_count, 3), 0.0); bcount = _map(work / "b-cell-count.i32", "int32", cell_count, 0)
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, ("Bcell_global_id", "Bcell_offsets", "Bcell_face_ids", "Bcell_weights"))
                face = b_faces[op["Bcell_face_ids"]]
                if np.any(~np.isfinite(face)): raise ValueError(f"rank {rank}: B operator references unfilled face storage")
                rows = np.repeat(np.arange(len(op["Bcell_global_id"])), np.diff(op["Bcell_offsets"]))
                local = np.empty((len(op["Bcell_global_id"]), 3))
                for component in range(3): local[:, component] = np.bincount(rows, weights=face * op["Bcell_weights"][:, component], minlength=len(local))
                dest = cell_index[op["Bcell_global_id"]]
                if np.any(dest < 0): raise ValueError(f"rank {rank}: B operator references absent owner cell")
                bsum[dest] += local; bcount[dest] += 1; diagnostics.event("reconstruct_B", rank=rank)
            if np.any(bcount == 0): raise ValueError(f"B reconstruction left {int((bcount == 0).sum())} cells unfilled")
            cell_values["B_induced"][:] = bsum * manifest["normalization"]["magnetic_field_ref"] * 1e9

        # Phase B3: scalar cell-to-node operator, accumulated safely across rank fragments.
        node_fields: dict[str, np.memmap] = {}
        for name, values in cell_values.items():
            components = 3 if values.ndim == 2 else 1
            sums = _map(work / f"node-sum-{name}.f64", "float64", (node_count, components) if components > 1 else node_count, 0.0)
            denoms = _map(work / f"node-denom-{name}.f64", "float64", (node_count, components) if components > 1 else node_count, 0.0)
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, ("NodeScalar_global_id", "NodeScalar_offsets", "NodeScalar_cell_ids", "NodeScalar_weights"))
                source = values[cell_index[op["NodeScalar_cell_ids"]]]
                numerator, denominator = _operator_apply(op["NodeScalar_offsets"], source, op["NodeScalar_weights"], components)
                dest = node_index[op["NodeScalar_global_id"]]
                if np.any(dest < 0): raise ValueError(f"rank {rank}: node reconstruction references absent owner node")
                sums[dest] += numerator if components > 1 else numerator[:, 0]; denoms[dest] += denominator if components > 1 else denominator[:, 0]
                diagnostics.event("project_to_nodes", rank=rank, field=name)
            final = _map(work / f"point-{name}.f64", "float64", sums.shape, np.nan)
            # Chunked finalisation prevents an expression-size spike.
            for start in range(0, node_count, 1_000_000):
                stop = min(start + 1_000_000, node_count); valid = denoms[start:stop] > 0
                final[start:stop][valid] = sums[start:stop][valid] / denoms[start:stop][valid]
            node_fields[name] = final

        report = {"ranks_processed": ranks, "blocks_processed": int(manifest["number_of_blocks"]), "local_nodes": local_nodes,
                  "unique_global_nodes": node_count, "interface_aliases": alias_nodes, "physical_cells": physical_cells,
                  "cell_types": {"VTK_HEXAHEDRON": physical_cells}, "invalid_cells": 0, "skipped_cells": 0,
                  "owner_alias_discrepancies": 0, "source_fields": sorted(requested_raw), "output_fields": fields,
                  "reconstruction_methods": {"B_induced": "MPCNS B_face_to_cell_cartesian", "nodal": "MPCNS cell_scalar_to_node"},
                  "temporary_directory": str(work), "temporary_bytes": sum(p.stat().st_size for p in work.iterdir() if p.is_file()),
                  "peak_memory": diagnostics.peak_rss}
        metadata = Data3D.standard_metadata(physical_time=float(time_value), time_unit="s", coordinate_unit="R_M",
            source={"name": "mercury_to_data3d", "version": "2-streaming", "mesh_uuid": manifest["mesh_uuid"], "case_uuid": manifest["case_uuid"]},
            fields={name: _descriptor(name) for name in fields}, cell_fields={"SourceBlockId": {"role": "source_block_id"}, "SourceRank": {"role": "source_rank"}, "SourceLocalBlockId": {"role": "source_local_block_id"}},
            normalization={**manifest["normalization"], "coordinate_reference": "Mercury radius R_M"}, conversion={"report": report, "memory": diagnostics.report()})
        partial = output.with_suffix(output.suffix + ".partial")
        write_vtu(partial, metadata=metadata, points=points, fields=node_fields, cells=cells, offsets=offsets, types=types,
                  cell_data={"SourceBlockId": source_block, "SourceRank": source_rank, "SourceLocalBlockId": source_local})
        diagnostics.event("write_vtu", output_bytes=partial.stat().st_size)
        # The writer has produced standard VTK XML; optional full PyVista readback is intentionally opt-in because it materialises all arrays.
        if verify_readback:
            loaded = Data3D.from_file(partial)
            if not loaded.is_data3d_v1: raise RuntimeError("VTK readback lost embedded Data3D metadata")
            diagnostics.event("vtk_readback", points=int(loaded.mesh.n_points), cells=int(loaded.mesh.n_cells))
        partial.replace(output)
        return output
    finally:
        if keep_temp:
            (work / "diagnostics.json").write_text(json.dumps(diagnostics.report(), indent=2) + "\n", encoding="utf-8")
        else:
            shutil.rmtree(work, ignore_errors=True)
