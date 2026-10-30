"""Disk-backed MPCNS v3 to Data3D v1 conversion pipeline.

Every quantity is reconstructed here from the documented MPCNS wire format and
the solver-materialised operators; no external Mercury post-processing package
is imported.  Fluid-only quantities (ion moments and generalized-Ohm electric
terms) are never extended into Solid cells: they force a compact Fluid mesh,
and the writer refuses to emit any non-finite PointData value.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import shutil
import tempfile
from typing import Any

import numpy as np

from sciplot import Data3D

from .streaming import (Diagnostics, cell_geometry, constant_fields, face_storage, geometry, load_manifest,
                        reconstruction, restart_fields, topology_maps, write_vtu)


# name: (physics domain, kind, unit, description, provenance)
_FIELDS = {
    "H_density": ("Fluid", "scalar", "kg/m^3", "H+ mass density", "reconstructed"),
    "H_velocity": ("Fluid", "vector", "km/s", "H+ bulk velocity", "reconstructed"),
    "H_pressure": ("Fluid", "scalar", "nPa", "H+ thermal pressure", "reconstructed"),
    "Na_density": ("Fluid", "scalar", "kg/m^3", "Na+ mass density", "reconstructed"),
    "Na_velocity": ("Fluid", "vector", "km/s", "Na+ bulk velocity", "reconstructed"),
    "Na_pressure": ("Fluid", "scalar", "nPa", "Na+ thermal pressure", "reconstructed"),
    "B_induced": ("all", "vector", "nT", "Induced magnetic field reconstructed from Mercury oriented face 2-form flux", "reconstructed"),
    "B_additive": ("all", "vector", "nT", "Prescribed additive magnetic field (Badd) reconstructed with the same face-to-cell operator", "reconstructed"),
    "B_total": ("all", "vector", "nT", "Total magnetic field B_induced + B_additive", "derived"),
    "J_induced": ("all", "vector", "nA/m^2", "Solver-equivalent v3 DEC current density from induced B (B-face -> J-edge -> J-cell)", "reconstructed"),
    "E_motional": ("Fluid", "vector", "mV/m", "Motional electric field -u_plus x B_total, u_plus = (n_H u_H + n_Na u_Na) / n_e", "derived"),
    "E_Hall": ("Fluid", "vector", "mV/m", "Hall electric field J_induced x B_total / (e n_e)", "derived"),
    "E_ambipolar": ("Fluid", "vector", "mV/m", "Ambipolar electric field -grad(p_e) / (e n_e), p_e = p_H + p_Na", "derived"),
    "E_generalized": ("Fluid", "vector", "mV/m", "Generalized-Ohm electric field E_motional + E_Hall + E_ambipolar", "derived"),
    "H_number_density": ("Fluid", "scalar", "cm^-3", "H+ number density rho_H / m_H", "derived"),
    "Na_number_density": ("Fluid", "scalar", "cm^-3", "Na+ number density rho_Na / m_Na", "derived"),
    "electron_number_density": ("Fluid", "scalar", "cm^-3", "Electron number density n_e = n_H + n_Na (singly charged ions)", "derived"),
    "ion_mass_density": ("Fluid", "scalar", "kg/m^3", "Total ion mass density rho_H + rho_Na", "derived"),
    "ion_charge_velocity": ("Fluid", "vector", "km/s", "Charge-weighted ion velocity u_plus = (n_H u_H + n_Na u_Na) / n_e", "derived"),
    "H_temperature": ("Fluid", "scalar", "K", "H+ temperature p m_H / (rho k_B)", "derived"),
    "Na_temperature": ("Fluid", "scalar", "K", "Na+ temperature p m_Na / (rho k_B)", "derived"),
    "thermal_pressure": ("Fluid", "scalar", "nPa", "Total ion thermal pressure p_H + p_Na (equals the electron pressure p_e used for E_ambipolar)", "derived"),
    "H_dynamic_pressure": ("Fluid", "scalar", "nPa", "H+ dynamic pressure rho_H |u_H|^2 (no factor 1/2)", "derived"),
    "Na_dynamic_pressure": ("Fluid", "scalar", "nPa", "Na+ dynamic pressure rho_Na |u_Na|^2 (no factor 1/2)", "derived"),
    "dynamic_pressure": ("Fluid", "scalar", "nPa", "Total ion dynamic pressure rho_H |u_H|^2 + rho_Na |u_Na|^2 (no factor 1/2)", "derived"),
    "magnetic_pressure": ("all", "scalar", "nPa", "Magnetic pressure |B_total|^2 / (2 mu0)", "derived"),
    "total_pressure": ("Fluid", "scalar", "nPa", "Pressure-balance total thermal_pressure + magnetic_pressure (dynamic pressure excluded)", "derived"),
    "plasma_beta": ("Fluid", "scalar", "1", "Plasma beta thermal_pressure / magnetic_pressure", "derived"),
}

# Dimensional category of each field; fields listed here get a nondimensional
# ``<name>_nd`` twin (SI value / solver reference value).
_CATEGORY = {
    "H_density": "density", "Na_density": "density", "ion_mass_density": "density",
    "H_velocity": "velocity", "Na_velocity": "velocity", "ion_charge_velocity": "velocity",
    "H_pressure": "pressure", "Na_pressure": "pressure", "thermal_pressure": "pressure",
    "H_dynamic_pressure": "pressure", "Na_dynamic_pressure": "pressure", "dynamic_pressure": "pressure",
    "magnetic_pressure": "pressure", "total_pressure": "pressure",
    "B_induced": "magnetic_field", "B_additive": "magnetic_field", "B_total": "magnetic_field",
    "J_induced": "current_density",
    "E_motional": "electric_field", "E_Hall": "electric_field", "E_ambipolar": "electric_field", "E_generalized": "electric_field",
    "H_number_density": "number_density", "Na_number_density": "number_density", "electron_number_density": "number_density",
    "H_temperature": "temperature", "Na_temperature": "temperature",
}
ND_SUFFIX = "_nd"

# Solver ingredients of each dimensional field: H/Na ion state, B (induced B
# cell field), Badd (static additive B), J (DEC current), grad (grad p_e).
_NEEDS = {
    "H_density": {"H"}, "H_velocity": {"H"}, "H_pressure": {"H"}, "H_number_density": {"H"}, "H_temperature": {"H"},
    "H_dynamic_pressure": {"H"},
    "Na_density": {"Na"}, "Na_velocity": {"Na"}, "Na_pressure": {"Na"}, "Na_number_density": {"Na"}, "Na_temperature": {"Na"},
    "Na_dynamic_pressure": {"Na"},
    "electron_number_density": {"H", "Na"}, "ion_mass_density": {"H", "Na"}, "ion_charge_velocity": {"H", "Na"},
    "thermal_pressure": {"H", "Na"}, "dynamic_pressure": {"H", "Na"},
    "B_induced": {"B"}, "B_additive": {"Badd"}, "B_total": {"B", "Badd"}, "J_induced": {"J"},
    "magnetic_pressure": {"B", "Badd"}, "total_pressure": {"H", "Na", "B", "Badd"}, "plasma_beta": {"H", "Na", "B", "Badd"},
    "E_motional": {"H", "Na", "B", "Badd"}, "E_Hall": {"H", "Na", "B", "Badd", "J"},
    "E_ambipolar": {"H", "Na", "grad"}, "E_generalized": {"H", "Na", "B", "Badd", "J", "grad"},
}
assert set(_NEEDS) == set(_FIELDS)


def _nd_name(name: str) -> str:
    return name + ND_SUFFIX


for _name in list(_CATEGORY):
    _domain, _kind, _unit, _description, _ = _FIELDS[_name]
    _FIELDS[_nd_name(_name)] = (_domain, _kind, "1", f"Nondimensional {_description[0].lower()}{_description[1:]} (SI value / solver reference)", "derived")
    _NEEDS[_nd_name(_name)] = _NEEDS[_name]


def base_field(name: str) -> str:
    """Dimensional field behind ``name`` (identity for non-``_nd`` names)."""
    return name[:-len(ND_SUFFIX)] if name.endswith(ND_SUFFIX) and name[:-len(ND_SUFFIX)] in _CATEGORY else name


def with_nondimensional(fields: list[str], mode: str) -> list[str]:
    """Expand a field list: ``none`` as given, ``both`` adds ``*_nd`` twins, ``only`` swaps to them."""
    if mode not in ("none", "both", "only"):
        raise ValueError(f"nondimensional must be none, both or only, not {mode!r}")
    if mode == "none": return list(fields)
    result: list[str] = []
    for name in fields:
        twin = _nd_name(name) if name in _CATEGORY else None
        result.extend([name, twin] if mode == "both" and twin else [twin or name] if mode == "only" else [name])
    return list(dict.fromkeys(result))


def _tokens(fields) -> set[str]:
    return set().union(*(_NEEDS[name] for name in fields)) if fields else set()


def raw_fields(name: str) -> set[str]:
    """Restart fields required by one output field."""
    tokens = _NEEDS[name]
    return ({"U_H"} if "H" in tokens else set()) | ({"U_Na"} if "Na" in tokens else set()) \
        | ({"B_xi", "B_eta", "B_zeta"} if tokens & {"B", "J"} else set())


def needs_constant_fields(name: str) -> bool:
    return "Badd" in _NEEDS[name]


# Public converter schema.  Keep this next to the solver-specific decoder so
# the YAML front end never has to duplicate or guess Mercury field names.
SUPPORTED_FIELDS = tuple(_FIELDS)
REGIONS = ("auto", "fluid", "solid", "all")

_ELEMENTARY_CHARGE = 1.602176634e-19
_BOLTZMANN = 1.380649e-23
_CHUNK = 1 << 20


def nondimensional_scales(norm: dict, constants: dict) -> dict[str, dict[str, Any]]:
    """Per category: ``nd = value_in_output_unit * to_nondimensional``."""
    unit = {"density": "kg/m^3", "velocity": "km/s", "pressure": "nPa", "magnetic_field": "nT", "current_density": "nA/m^2",
            "electric_field": "mV/m", "number_density": "cm^-3", "temperature": "K"}
    factor = {"density": 1 / norm["density_ref"], "velocity": 1e3 / norm["velocity_ref"], "pressure": 1e-9 / norm["pressure_ref"],
              "magnetic_field": 1e-9 / norm["magnetic_field_ref"], "current_density": 1e-9 / norm["current_density_ref"],
              "electric_field": 1e-3 / norm["electric_field_ref"],
              # n_nd = n m_H / density_ref, i.e. relative to a hydrogen-mass number density.
              "number_density": 1e6 * float(constants["particle_mass_H"]) / norm["density_ref"],
              "temperature": 1 / norm["temperature_ref"]}
    reference = {"density": "density_ref", "velocity": "velocity_ref", "pressure": "pressure_ref", "magnetic_field": "magnetic_field_ref",
                 "current_density": "current_density_ref", "electric_field": "electric_field_ref", "number_density": "density_ref",
                 "temperature": "temperature_ref"}
    return {key: {"output_unit": unit[key], "to_nondimensional": factor[key], "reference": reference[key]} for key in unit}


def resolve_region(fields: list[str], region: str = "auto") -> str:
    """Choose the output cell region; Fluid-only quantities never enter Solid cells."""
    if region not in REGIONS:
        raise ValueError(f"Unknown Mercury output region {region!r}; choose from {list(REGIONS)}")
    fluid_only = sorted(name for name in fields if _FIELDS[name][0] == "Fluid")
    if region == "auto":
        return "fluid" if fluid_only else "all"
    if fluid_only and region != "fluid":
        raise ValueError(f"{fluid_only} are undefined in Solid cells; use region 'fluid' (or 'auto'), "
                         f"or request only fields defined in both domains: {sorted(n for n, v in _FIELDS.items() if v[0] == 'all' and not n.endswith(ND_SUFFIX))}")
    return region


def _map(path: Path, dtype, shape, fill=None) -> np.memmap:
    value = np.memmap(path, dtype=dtype, mode="w+", shape=shape)
    if fill is not None:
        value[...] = fill; value.flush()
    return value


def _descriptor(name: str, scales: dict[str, dict[str, Any]]) -> dict[str, Any]:
    domain, kind, unit, description, provenance = _FIELDS[name]
    result = {"kind": kind, "components": 3 if kind == "vector" else 1, "unit": unit, "provenance": provenance,
              "description": description, "physics_domain": "Fluid" if domain == "Fluid" else "Fluid and Solid"}
    if kind == "vector": result["component_system"] = "Cartesian"
    base = base_field(name)
    if base in _CATEGORY:
        scale = scales[_CATEGORY[base]]
        if base == name:
            result["nondimensional"] = {"field": _nd_name(name), "scale": scale["to_nondimensional"], "reference": scale["reference"]}
        else:
            result["dimensional"] = {"field": base, "unit": scale["output_unit"], "scale_from_dimensional": scale["to_nondimensional"],
                                     "reference": scale["reference"]}
    return result


def _rows(offsets: np.ndarray) -> np.ndarray:
    return np.repeat(np.arange(len(offsets) - 1), np.diff(offsets))


def _apply(offsets: np.ndarray, weights: np.ndarray, inputs: np.ndarray) -> np.ndarray:
    """Apply one CSR operator; vector weights give Cartesian (rows, 3) output."""
    rows, count = _rows(offsets), len(offsets) - 1
    if weights.ndim == 1:
        return np.bincount(rows, weights=weights * inputs, minlength=count)
    return np.stack([np.bincount(rows, weights=weights[:, c] * inputs, minlength=count) for c in range(weights.shape[1])], axis=1)


def _accumulate(store: np.memmap, index: np.ndarray, values: np.ndarray, label: str) -> None:
    """Add operator rows into a NaN-initialised store, like merged multi-rank rows."""
    if np.unique(index).size != index.size:
        raise ValueError(f"{label}: operator repeats an output row within one rank")
    current = store[index]
    store[index] = np.where(np.isfinite(current), current, 0.0) + values


def _operator_apply(offsets: np.ndarray, source: np.ndarray, weights: np.ndarray, components: int,
                    link_valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = _rows(offsets)
    source = source.reshape((-1, components)) if components > 1 else source.reshape((-1, 1))
    finite = np.isfinite(source) & link_valid[:, None]
    numerator = np.empty((len(offsets) - 1, components))
    denominator = np.empty_like(numerator)
    for component in range(components):
        numerator[:, component] = np.bincount(rows, weights=weights * np.where(finite[:, component], source[:, component], 0.0), minlength=len(numerator))
        denominator[:, component] = np.bincount(rows, weights=weights * finite[:, component], minlength=len(numerator))
    return numerator, denominator


def _species(raw: np.ndarray, gamma: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Nondimensional rho, u, p from [rho, rho u, E]; invalid rows are NaN."""
    rho = raw[:, 0]
    valid = np.isfinite(raw).all(axis=1) & (rho > 0)
    velocity = np.full((len(raw), 3), np.nan); pressure = np.full(len(raw), np.nan)
    velocity[valid] = raw[valid, 1:4] / rho[valid, None]
    pressure[valid] = (gamma - 1.0) * (raw[valid, 4] - .5 * rho[valid] * np.sum(velocity[valid] ** 2, axis=1))
    return np.where(valid, rho, np.nan), velocity, pressure, valid & np.isfinite(pressure)


def _curvilinear_gradient(xyz: np.ndarray, scalar: np.ndarray) -> np.ndarray:
    """Cartesian gradient of a scalar on one structured curvilinear block."""
    if min(scalar.shape) < 2:
        raise ValueError(f"Fluid block of shape {scalar.shape} is too thin for a pressure gradient")
    order = 2 if min(scalar.shape) >= 3 else 1
    # metric[..., computational_axis, Cartesian_component] = d x_component / d axis
    metric = np.swapaxes(np.stack([np.stack(np.gradient(xyz[..., c], axis=(0, 1, 2), edge_order=order), axis=-1)
                                   for c in range(3)], axis=-1), -1, -2)
    derivative = np.stack(np.gradient(scalar, axis=(0, 1, 2), edge_order=order), axis=-1)
    gradient = np.empty(scalar.shape + (3,))
    determinant = np.linalg.det(metric); scale = np.linalg.norm(metric, axis=(-2, -1))
    good = np.abs(determinant) > 1e-12 * np.maximum(scale ** 3, 1e-300)
    gradient[good] = np.linalg.solve(metric[good], derivative[good, ..., None])[..., 0]
    if np.any(~good):
        gradient[~good] = np.einsum("...ij,...j->...i", np.linalg.pinv(metric[~good]), derivative[~good])
    return gradient


def convert(*, static_dir: Path, data_dir: Path, output: Path, fields: list[str], temp_dir: Path | None,
            memory_budget_gb: float | None, region: str = "auto", keep_temp: bool = False,
            verify_readback: bool = False) -> Path:
    """Convert with bounded RAM; all full-size buffers are disk-backed memmaps."""
    unknown = sorted(set(fields) - set(_FIELDS))
    if unknown: raise ValueError(f"Unknown output fields: {unknown}; choose from {sorted(_FIELDS)}")
    region = resolve_region(fields, region)
    wanted = set(fields)
    tokens = _tokens(wanted)
    need_gradient, need_current, need_additive = "grad" in tokens, "J" in tokens, "Badd" in tokens
    need_induced = "B" in tokens
    species = ({"U_H"} if "H" in tokens else set()) | ({"U_Na"} if "Na" in tokens else set())
    manifest = load_manifest(static_dir)
    norm, constants = manifest["normalization"], manifest["physical_constants"]
    fluid_bit, solid_bit = (int(manifest.get("cell_flag_bits", {}).get(key, 0)) for key in ("fluid", "solid"))
    if not fluid_bit or not solid_bit:
        raise ValueError("Mercury manifest lacks fluid/solid cell_flag_bits")
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
        cell_flags = _map(work / "cell-flags.u32", "uint32", cell_count)
        centers = _map(work / "cell-centers.f64", "float64", (cell_count, 3)) if need_gradient else None
        # Deterministic rank-order allocation from solver owner IDs, not coordinates.
        node_cursor = cell_cursor = 0
        for rank in range(ranks):
            node_gid, xyz, cell_gid = geometry(static_dir / files["geometry"][rank], manifest)
            if np.any(node_index[node_gid] >= 0) or np.any(cell_index[cell_gid] >= 0):
                raise ValueError(f"rank {rank}: duplicate purported owner global IDs")
            node_index[node_gid] = np.arange(node_cursor, node_cursor + len(node_gid)); points[node_cursor:node_cursor + len(node_gid)] = xyz
            cell_index[cell_gid] = np.arange(cell_cursor, cell_cursor + len(cell_gid))
            extra = cell_geometry(static_dir / files["geometry"][rank], manifest, centers=need_gradient)
            if not np.array_equal(extra["cell_global_id"], cell_gid):
                raise ValueError(f"rank {rank}: cell flag/centre rows do not follow cell_global_id")
            cell_flags[cell_cursor:cell_cursor + len(cell_gid)] = extra["cell_flags"]
            if centers is not None:
                centers[cell_cursor:cell_cursor + len(cell_gid)] = extra["cell_center_xyz"]
            node_cursor += len(node_gid); cell_cursor += len(cell_gid)
            diagnostics.event("index_geometry", rank=rank, processed_nodes=node_cursor, processed_cells=cell_cursor)
        if (node_cursor, cell_cursor) != (node_count, cell_count): raise AssertionError("owner index cursor mismatch")
        fluid = (cell_flags & np.uint32(fluid_bit)) != 0
        solid = ~fluid & ((cell_flags & np.uint32(solid_bit)) != 0)
        region_cells = {"fluid": fluid, "solid": solid, "all": np.ones(cell_count, dtype=bool)}[region]
        if not np.any(region_cells):
            raise ValueError(f"Mercury case has no {region} cells")

        # Phase A2: count owner cells, the global B-face span and the DEC column space.
        physical_cells = 0; face_max = -1; local_nodes = 0; alias_nodes = 0; columns = None
        for rank in range(ranks):
            maps = topology_maps(static_dir / files["topology"][rank], manifest)
            physical_cells += sum(int(item.owners.sum()) for item in maps if item.location == "cell")
            for item in maps:
                if item.location == "node": local_nodes += len(item.gids); alias_nodes += len(item.gids) - int(item.owners.sum())
                if item.location.startswith("face_"): face_max = max(face_max, int(item.gids.max(initial=-1)))
            if need_current:
                storage = face_storage(static_dir / files["topology"][rank], manifest)
                if columns not in (None, (storage.quotient_count, storage.column_count)):
                    raise ValueError("inconsistent B-face operator column metadata across ranks")
                columns = (storage.quotient_count, storage.column_count)
            diagnostics.event("scan_topology", rank=rank, processed_cells=physical_cells)
        if physical_cells != cell_count:
            raise ValueError(f"owner local-map cells {physical_cells} != owner geometry cells {cell_count}")
        if columns is not None and face_max >= columns[0]:
            raise ValueError("quotient Face IDs lie outside the v3 DEC column space")
        cells = _map(work / "connectivity.i64", "int64", physical_cells * 8)
        cell_row = _map(work / "cell-row.i64", "int64", physical_cells)
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
                i, j, k = np.argwhere(block.owners.reshape(block.shape, order="F")).T
                ids = np.stack((nids[i, j, k], nids[i+1, j, k], nids[i+1, j+1, k], nids[i, j+1, k],
                                nids[i, j, k+1], nids[i+1, j, k+1], nids[i+1, j+1, k+1], nids[i, j+1, k+1]), axis=1)
                bad = np.any(np.diff(np.sort(ids, axis=1), axis=1) == 0, axis=1)
                invalid_cells.extend(f"rank {rank} block {block.block} cell {tuple(map(int, x))}" for x in np.stack((i, j, k), axis=1)[bad])
                ids = ids[~bad]; count = len(ids)
                rows = cell_index[block.gids.reshape(block.shape, order="F")[i, j, k][~bad]]
                if np.any(rows < 0): raise ValueError(f"rank {rank} block {block.block}: topology references absent owner cell")
                cells[cursor * 8:(cursor + count) * 8] = ids.reshape(-1); cell_row[cursor:cursor + count] = rows
                source_block[cursor:cursor + count] = rank * 1_000_000 + block.block; source_rank[cursor:cursor + count] = rank
                source_local[cursor:cursor + count] = block.block; cursor += count
            diagnostics.event("build_connectivity", rank=rank, processed_cells=cursor)
        if invalid_cells or cursor != physical_cells:
            raise ValueError(f"invalid axis/degenerate cells={len(invalid_cells)}; first={invalid_cells[:4]}; no output written")

        # Phase B1: stream restart blocks into global owner-ID storage.  The B
        # store spans quotient Faces plus, for DEC current, raw restart-ghost columns.
        conserved = {name: _map(work / f"cell-{name}.f64", "float64", (cell_count, 5), np.nan) for name in sorted(species)}
        need_faces = need_induced or need_current
        b_columns = _map(work / "b-columns.f64", "float64", columns[1] if columns else face_max + 1, np.nan) if need_faces else None
        requested_raw = set(conserved) | ({"B_xi", "B_eta", "B_zeta"} if need_faces else set())
        time_value = step = None
        for rank in range(ranks):
            maps = {(item.block, item.location): item for item in topology_maps(static_dir / files["topology"][rank], manifest)}
            ghosts: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
            if need_current:
                storage = face_storage(static_dir / files["topology"][rank], manifest)
                if np.any(storage.ghost_addresses[:, 0] != rank):
                    raise ValueError(f"rank {rank}: B-face ghost columns that address another rank's restart are unsupported")
                grouped = defaultdict(list)
                for row, (block_id, code) in enumerate(storage.ghost_addresses[:, 1:3].tolist()): grouped[(block_id, code)].append(row)
                ghosts = {key: (storage.ghost_columns[rows], storage.ghost_addresses[rows, 3:6]) for key, rows in grouped.items()}
            def consume(name, block_id, lo, _hi, values):
                if values is None: return
                location = {"U_H": "cell", "U_Na": "cell", "B_xi": "face_xi", "B_eta": "face_eta", "B_zeta": "face_zeta"}[name]
                item = maps.get((block_id, location))
                if item is None: raise ValueError(f"rank {rank} block {block_id}: missing {location} map")
                sl = tuple(slice(-lo[d], -lo[d] + item.shape[d]) for d in range(3))
                local = values[sl].reshape((-1, values.shape[-1]), order="F"); owner = item.owners
                gids = item.gids[owner]
                if name in conserved:
                    conserved[name][cell_index[gids]] = local[owner]
                    return
                assert b_columns is not None
                incoming = local[owner, 0] * item.signs[owner]
                existing = b_columns[gids]; conflict = np.isfinite(existing) & ~np.isclose(existing, incoming, rtol=1e-10, atol=1e-12)
                if np.any(conflict): raise ValueError(f"rank {rank}: oriented B alias mismatch (max={np.max(np.abs(existing[conflict]-incoming[conflict]))})")
                b_columns[gids] = incoming
                # Auxiliary ghost columns are read raw (sign 1) at their restart storage address.
                ghost = ghosts.pop((block_id, {"B_xi": 1, "B_eta": 2, "B_zeta": 3}[name]), None)
                if ghost is not None:
                    ghost_columns, address = ghost; local_index = address - np.asarray(lo)
                    if np.any(local_index < 0) or np.any(local_index >= np.asarray(values.shape[:3])):
                        raise ValueError(f"rank {rank} block {block_id}: B-face ghost address outside its restart extent")
                    b_columns[ghost_columns] = values[local_index[:, 0], local_index[:, 1], local_index[:, 2], 0]
            actual_step, actual_time = restart_fields(data_dir / f"flow_field{rank:04d}.bin", manifest, requested_raw, consume)
            if ghosts:
                raise ValueError(f"rank {rank}: unresolved B-face ghost storage in (block, location) {sorted(ghosts)[:4]}")
            if time_value is None: step, time_value = actual_step, actual_time
            elif (step, time_value) != (actual_step, actual_time): raise ValueError("restart rank step/time mismatch")
            diagnostics.event("stream_restart", rank=rank, processed_cells=cell_count)

        # Phase B2: Face 2-forms -> Cartesian cell B with the supplied per-rank operator.
        def faces_to_cells(faces: np.memmap, label: str) -> np.memmap:
            result = _map(work / f"cell-{label}.f64", "float64", (cell_count, 3), np.nan)
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, ("Bcell_global_id", "Bcell_offsets", "Bcell_face_ids", "Bcell_weights"))
                face = faces[op["Bcell_face_ids"]]
                if np.any(~np.isfinite(face)): raise ValueError(f"rank {rank}: {label} operator references unfilled face storage")
                dest = cell_index[op["Bcell_global_id"]]
                if np.any(dest < 0): raise ValueError(f"rank {rank}: B operator references absent owner cell")
                _accumulate(result, dest, _apply(op["Bcell_offsets"], op["Bcell_weights"], face), label)
                diagnostics.event(f"reconstruct_{label}", rank=rank)
            if np.any(~np.isfinite(result)): raise ValueError(f"{label} reconstruction left {int((~np.isfinite(result).all(axis=1)).sum())} cells unfilled")
            return result

        b_induced = faces_to_cells(b_columns, "B_induced") if need_induced else None
        b_additive = None
        if need_additive:
            badd = _map(work / "badd-faces.f64", "float64", face_max + 1, np.nan)
            names = {"Badd_xi", "Badd_eta", "Badd_zeta"}
            for rank in range(ranks):
                for name, (gids, values) in constant_fields(static_dir / files["constant_field"][rank], manifest, names).items():
                    if np.any(gids > face_max) or np.any(np.isfinite(badd[gids])):
                        raise ValueError(f"rank {rank}: {name} has out-of-range or duplicate owner Face IDs")
                    badd[gids] = values
            b_additive = faces_to_cells(badd, "B_additive")

        # Phase B3: v3 DEC current B-face (+ghost columns) -> J-edge 1-form -> Cartesian J-cell.
        j_cells = None
        if need_current:
            assert b_columns is not None
            edge_max = max(int(reconstruction(static_dir / files["reconstruction"][rank], manifest, ("BfaceJedge_global_id",))
                               .get("BfaceJedge_global_id", np.empty(0, dtype=np.int64)).max(initial=-1)) for rank in range(ranks))
            if edge_max < 0: raise ValueError("DEC current operators are unavailable; this case needs v3 reconstruction_*.bin files")
            j_edges = _map(work / "j-edges.f64", "float64", edge_max + 1, np.nan)
            names = ("BfaceJedge_global_id", "BfaceJedge_offsets", "BfaceJedge_face_ids", "BfaceJedge_weights")
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, names)
                if set(names) - op.keys(): raise ValueError(f"rank {rank}: DEC B_face_to_J_edge operator is missing")
                column = op["BfaceJedge_face_ids"]
                if np.any(column >= len(b_columns)): raise ValueError(f"rank {rank}: DEC operator column outside the B-face column space")
                face = b_columns[column]
                if np.any(~np.isfinite(face)): raise ValueError(f"rank {rank}: DEC B-face input has {int((~np.isfinite(face)).sum())} unresolved columns")
                _accumulate(j_edges, op["BfaceJedge_global_id"], _apply(op["BfaceJedge_offsets"], op["BfaceJedge_weights"], face), "B_face_to_J_edge")
                diagnostics.event("reconstruct_J_edge", rank=rank)
            j_cells = _map(work / "cell-J.f64", "float64", (cell_count, 3), np.nan)
            names = ("JedgeJcell_global_id", "JedgeJcell_offsets", "JedgeJcell_edge_ids", "JedgeJcell_weights")
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, names)
                if set(names) - op.keys(): raise ValueError(f"rank {rank}: DEC J_edge_to_cell operator is missing")
                edge = op["JedgeJcell_edge_ids"]
                if np.any(edge > edge_max) or np.any(~np.isfinite(j_edges[edge])): raise ValueError(f"rank {rank}: DEC J_edge_to_cell references unfilled Edges")
                dest = cell_index[op["JedgeJcell_global_id"]]
                if np.any(dest < 0): raise ValueError(f"rank {rank}: DEC operator references absent owner cell")
                _accumulate(j_cells, dest, _apply(op["JedgeJcell_offsets"], op["JedgeJcell_weights"], j_edges[edge]), "J_edge_to_cell")
                diagnostics.event("reconstruct_J_cell", rank=rank)
            if np.any(~np.isfinite(j_cells)): raise ValueError("DEC J_edge_to_cell reconstruction left unfilled cells")

        # Phase C1: ion moments on Fluid cells; Solid cells stay NaN and are never projected.
        gamma = float(constants["gamma"])
        mass = {"U_H": float(constants["particle_mass_H"]), "U_Na": float(constants["particle_mass_Na"])}
        def species_chunk(name: str, start: int, stop: int):
            rho, velocity, pressure, valid = _species(np.asarray(conserved[name][start:stop]), gamma)
            bad = fluid[start:stop] & ~valid
            if np.any(bad): raise ValueError(f"{name} state is invalid (non-finite or rho<=0) in {int(bad.sum())} Fluid cells")
            return rho, velocity, pressure

        gradient = None
        if need_gradient:
            # Electron pressure closure p_e = p_H + p_Na, in Pa.
            electron_pressure = _map(work / "cell-pe.f64", "float64", cell_count, np.nan)
            for start in range(0, cell_count, _CHUNK):
                stop = min(start + _CHUNK, cell_count); part = fluid[start:stop]
                total = species_chunk("U_H", start, stop)[2] + species_chunk("U_Na", start, stop)[2]
                electron_pressure[start:stop][part] = total[part] * norm["pressure_ref"]
            # Blockwise curvilinear gradient on uniformly Fluid blocks, in rank/block order.
            gradient = _map(work / "cell-grad-pe.f64", "float64", (cell_count, 3), np.nan)
            for rank in range(ranks):
                for block in (x for x in topology_maps(static_dir / files["topology"][rank], manifest) if x.location == "cell"):
                    rows = cell_index[block.gids]
                    if np.any(rows < 0): raise ValueError(f"rank {rank} block {block.block}: topology references absent owner cell")
                    flags = np.unique(cell_flags[rows])
                    if flags.size != 1 or not int(flags[0]) & fluid_bit: continue
                    xyz = np.asarray(centers[rows]).reshape(block.shape + (3,), order="F") * norm["length_ref"]
                    value = np.asarray(electron_pressure[rows]).reshape(block.shape, order="F")
                    gradient[rows] = _curvilinear_gradient(xyz, value).reshape((-1, 3), order="F")
                diagnostics.event("gradient_pe", rank=rank)

        # Phase C2: requested cell values in output units, then their nondimensional twins.
        scales = nondimensional_scales(norm, constants)
        mu0 = float(constants["mu0"])
        cell_values = {name: _map(work / f"out-{name}.f64", "float64", (cell_count, 3) if _FIELDS[name][1] == "vector" else cell_count, np.nan) for name in fields}
        for start in range(0, cell_count, _CHUNK):
            stop = min(start + _CHUNK, cell_count); part = fluid[start:stop]
            primitive = {name: species_chunk(name, start, stop) for name in sorted(species)}
            out: dict[str, np.ndarray] = {}
            for name in conserved:
                prefix = name[2:]; rho, velocity, pressure = primitive[name]
                out[f"{prefix}_density"] = rho * norm["density_ref"]
                out[f"{prefix}_velocity"] = velocity * norm["velocity_ref"] * 1e-3
                out[f"{prefix}_pressure"] = pressure * norm["pressure_ref"] * 1e9
                out[f"{prefix}_number_density"] = out[f"{prefix}_density"] / mass[name] * 1e-6
                out[f"{prefix}_temperature"] = pressure * norm["pressure_ref"] * mass[name] / (rho * norm["density_ref"] * _BOLTZMANN)
                out[f"{prefix}_dynamic_pressure"] = rho * np.sum(velocity ** 2, axis=1) * norm["density_ref"] * norm["velocity_ref"] ** 2 * 1e9
            if len(conserved) == 2:
                (rho_h, vel_h, p_h), (rho_na, vel_na, p_na) = primitive["U_H"], primitive["U_Na"]
                n_h = rho_h * norm["density_ref"] / mass["U_H"]; n_na = rho_na * norm["density_ref"] / mass["U_Na"]
                n_e = n_h + n_na
                out["electron_number_density"] = n_e * 1e-6
                out["ion_mass_density"] = (rho_h + rho_na) * norm["density_ref"]
                u_plus = (n_h[:, None] * vel_h + n_na[:, None] * vel_na) * norm["velocity_ref"] / n_e[:, None]
                out["ion_charge_velocity"] = u_plus * 1e-3
                out["thermal_pressure"] = (p_h + p_na) * norm["pressure_ref"] * 1e9
                out["dynamic_pressure"] = out["H_dynamic_pressure"] + out["Na_dynamic_pressure"]
            b_total_nd = None
            if b_induced is not None: out["B_induced"] = b_induced[start:stop] * norm["magnetic_field_ref"] * 1e9
            if b_additive is not None: out["B_additive"] = b_additive[start:stop] * norm["magnetic_field_ref"] * 1e9
            if b_induced is not None and b_additive is not None:
                b_total_nd = b_induced[start:stop] + b_additive[start:stop]; out["B_total"] = b_total_nd * norm["magnetic_field_ref"] * 1e9
                out["magnetic_pressure"] = np.sum((b_total_nd * norm["magnetic_field_ref"]) ** 2, axis=1) / (2 * mu0) * 1e9
                if len(conserved) == 2:
                    out["total_pressure"] = out["thermal_pressure"] + out["magnetic_pressure"]
                    out["plasma_beta"] = out["thermal_pressure"] / out["magnetic_pressure"]
            if j_cells is not None: out["J_induced"] = j_cells[start:stop] * norm["current_density_ref"] * 1e9
            if len(conserved) == 2 and any(base_field(name).startswith("E_") for name in wanted):
                charge = _ELEMENTARY_CHARGE * n_e[:, None]
                electric = {name: np.full((stop - start, 3), np.nan) for name in ("E_motional", "E_Hall", "E_ambipolar", "E_generalized")}
                if b_total_nd is not None:
                    b_tesla = b_total_nd[part] * norm["magnetic_field_ref"]
                    electric["E_motional"][part] = -np.cross(u_plus[part], b_tesla)
                if j_cells is not None and b_total_nd is not None:
                    current = j_cells[start:stop][part] * norm["current_density_ref"]
                    electric["E_Hall"][part] = np.cross(current, b_tesla) / charge[part]
                if gradient is not None:
                    electric["E_ambipolar"][part] = -gradient[start:stop][part] / charge[part]
                if gradient is not None and j_cells is not None:
                    electric["E_generalized"][part] = electric["E_motional"][part] + electric["E_Hall"][part] + electric["E_ambipolar"][part]
                out.update({name: value * 1e3 for name, value in electric.items()})
            for name in fields:
                base = base_field(name)
                value = out[base]
                cell_values[name][start:stop] = value * scales[_CATEGORY[base]]["to_nondimensional"] if name != base else value
        for name in fields:
            for start in range(0, cell_count, _CHUNK):
                stop = min(start + _CHUNK, cell_count)
                values = np.asarray(cell_values[name][start:stop]).reshape(stop - start, -1)[region_cells[start:stop]]
                if np.any(~np.isfinite(values)):
                    raise ValueError(f"{name} is non-finite in {int((~np.isfinite(values)).any(axis=1).sum())} {region} cells")
        diagnostics.event("cell_fields", fields=list(fields))

        # Phase D: scalar cell-to-node operator restricted to the output region,
        # accumulated safely across rank fragments with renormalized weights.
        node_fields: dict[str, np.memmap] = {}
        for name, values in cell_values.items():
            components = 3 if values.ndim == 2 else 1
            sums = _map(work / f"node-sum-{name}.f64", "float64", (node_count, components) if components > 1 else node_count, 0.0)
            denoms = _map(work / f"node-denom-{name}.f64", "float64", (node_count, components) if components > 1 else node_count, 0.0)
            for rank in range(ranks):
                op = reconstruction(static_dir / files["reconstruction"][rank], manifest, ("NodeScalar_global_id", "NodeScalar_offsets", "NodeScalar_cell_ids", "NodeScalar_weights"))
                rows = cell_index[op["NodeScalar_cell_ids"]]
                if np.any(rows < 0): raise ValueError(f"rank {rank}: node reconstruction references absent owner cell")
                numerator, denominator = _operator_apply(op["NodeScalar_offsets"], values[rows], op["NodeScalar_weights"], components, region_cells[rows])
                dest = node_index[op["NodeScalar_global_id"]]
                if np.any(dest < 0): raise ValueError(f"rank {rank}: node reconstruction references absent owner node")
                sums[dest] += numerator if components > 1 else numerator[:, 0]; denoms[dest] += denominator if components > 1 else denominator[:, 0]
                diagnostics.event("project_to_nodes", rank=rank, field=name)
            final = _map(work / f"point-{name}.f64", "float64", sums.shape, np.nan)
            # Chunked finalisation prevents an expression-size spike.
            for start in range(0, node_count, _CHUNK):
                stop = min(start + _CHUNK, node_count); valid = denoms[start:stop] > 0
                final[start:stop][valid] = sums[start:stop][valid] / denoms[start:stop][valid]
            node_fields[name] = final

        # Phase E: keep only cells of the output region and the nodes they use.
        physics = _map(work / "physics-code.u8", "uint8", physical_cells)
        keep = _map(work / "keep-cell.u8", "uint8", physical_cells)
        for start in range(0, physical_cells, _CHUNK):
            stop = min(start + _CHUNK, physical_cells); rows = cell_row[start:stop]
            physics[start:stop] = np.where(fluid[rows], 1, np.where(solid[rows], 2, 0))
            keep[start:stop] = region_cells[rows]
        kept_cells = int(np.count_nonzero(keep))
        if region == "all":
            out_cells, out_points, out_fields = cells, points, node_fields
            out_cell_data = {"SourceBlockId": source_block, "SourceRank": source_rank, "SourceLocalBlockId": source_local, "PhysicsCode": physics}
        else:
            used = _map(work / "node-used.u8", "uint8", node_count, 0)
            for start in range(0, physical_cells, _CHUNK):
                stop = min(start + _CHUNK, physical_cells)
                used[np.asarray(cells[start * 8:stop * 8]).reshape(-1, 8)[keep[start:stop].astype(bool)].reshape(-1)] = 1
            kept_nodes = int(np.count_nonzero(used))
            renumber = _map(work / "node-renumber.i64", "int64", node_count, -1)
            out_points = _map(work / "out-points.f64", "float64", (kept_nodes, 3))
            out_fields = {name: _map(work / f"out-point-{name}.f64", "float64", (kept_nodes,) + value.shape[1:]) for name, value in node_fields.items()}
            cursor = 0
            for start in range(0, node_count, _CHUNK):
                stop = min(start + _CHUNK, node_count); selected = np.flatnonzero(used[start:stop]) + start; count = len(selected)
                renumber[selected] = np.arange(cursor, cursor + count); out_points[cursor:cursor + count] = points[selected]
                for name, value in node_fields.items(): out_fields[name][cursor:cursor + count] = value[selected]
                cursor += count
            out_cells = _map(work / "out-connectivity.i64", "int64", kept_cells * 8)
            out_cell_data = {name: _map(work / f"out-{name}.cell", value.dtype, kept_cells) for name, value in
                             {"SourceBlockId": source_block, "SourceRank": source_rank, "SourceLocalBlockId": source_local, "PhysicsCode": physics}.items()}
            sources = {"SourceBlockId": source_block, "SourceRank": source_rank, "SourceLocalBlockId": source_local, "PhysicsCode": physics}
            cursor = 0
            for start in range(0, physical_cells, _CHUNK):
                stop = min(start + _CHUNK, physical_cells); selected = np.flatnonzero(keep[start:stop]) + start; count = len(selected)
                out_cells[cursor * 8:(cursor + count) * 8] = renumber[np.asarray(cells[start * 8:stop * 8]).reshape(-1, 8)[selected - start].reshape(-1)]
                for name, value in sources.items(): out_cell_data[name][cursor:cursor + count] = value[selected]
                cursor += count
        offsets = _map(work / "offsets.i64", "int64", kept_cells)
        types = _map(work / "types.u8", "uint8", kept_cells, 12)
        for start in range(0, kept_cells, _CHUNK):
            stop = min(start + _CHUNK, kept_cells); offsets[start:stop] = (np.arange(start, stop) + 1) * 8
        for name, value in out_fields.items():
            for start in range(0, len(out_points), _CHUNK):
                bad = ~np.isfinite(np.asarray(value[start:start + _CHUNK]))
                if np.any(bad):
                    raise RuntimeError(f"{name} has non-finite values at {int(bad.reshape(len(bad), -1).any(axis=1).sum())}+ output nodes; "
                                       "no output written (check the region and source data)")
        diagnostics.event("select_region", region=region, cells=kept_cells, points=int(len(out_points)))

        report = {"ranks_processed": ranks, "blocks_processed": int(manifest["number_of_blocks"]), "local_nodes": local_nodes,
                  "unique_global_nodes": node_count, "interface_aliases": alias_nodes, "physical_cells": physical_cells,
                  "fluid_cells": int(np.count_nonzero(fluid)), "solid_cells": int(np.count_nonzero(solid)),
                  "region": region, "output_cells": kept_cells, "output_points": int(len(out_points)),
                  "cell_types": {"VTK_HEXAHEDRON": kept_cells}, "invalid_cells": 0, "skipped_cells": 0,
                  "owner_alias_discrepancies": 0, "source_fields": sorted(requested_raw), "output_fields": list(fields),
                  "reconstruction_methods": {"B": "MPCNS B_face_to_cell_cartesian", "J_induced": "MPCNS v3 DEC B_face_to_J_edge + J_edge_to_cell",
                                             "grad_p_e": "blockwise curvilinear cell-centre gradient on Fluid blocks",
                                             "nodal": f"MPCNS cell_scalar_to_node restricted to {region} cells, renormalized"},
                  "electron_model": {"n_e": "n_H + n_Na (singly charged ions)", "p_e": "p_H + p_Na"},
                  "temporary_directory": str(work), "temporary_bytes": sum(p.stat().st_size for p in work.iterdir() if p.is_file()),
                  "peak_memory": diagnostics.peak_rss}
        metadata = Data3D.standard_metadata(physical_time=float(time_value), time_unit="s", coordinate_unit="R_M",
            source={"name": "mercury_to_data3d", "version": "3-streaming", "mesh_uuid": manifest["mesh_uuid"], "case_uuid": manifest["case_uuid"]},
            fields={name: _descriptor(name, scales) for name in fields},
            cell_fields={"SourceBlockId": {"role": "source_block_id"}, "SourceRank": {"role": "source_rank"}, "SourceLocalBlockId": {"role": "source_local_block_id"},
                         "PhysicsCode": {"role": "physics_code", "values": {"1": "Fluid", "2": "Solid"}}},
            normalization={**norm, "coordinate_reference": "Mercury radius R_M", "coordinate_scale_m": norm["length_ref"],
                           "physical_constants": {**{k: float(v) for k, v in constants.items()}, "elementary_charge": _ELEMENTARY_CHARGE,
                                                  "boltzmann_constant": _BOLTZMANN},
                           "nondimensional_scales": scales,
                           "convention": "nondimensional = SI value / <name>_ref; fields named <X>_nd = <X> * nondimensional_scales[category].to_nondimensional; "
                                         "coordinates are already in units of length_ref (R_M)"},
            conversion={"report": report, "memory": diagnostics.report()})
        partial = output.with_suffix(output.suffix + ".partial")
        write_vtu(partial, metadata=metadata, points=out_points, fields=out_fields, cells=out_cells, offsets=offsets, types=types,
                  cell_data=out_cell_data)
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
