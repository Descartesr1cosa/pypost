"""Low-memory readers and VTU writer for the documented MPCNS v3 wire format.

This module is deliberately converter-local.  It implements only the sections
used to create Data3D v1 and is based on the supplied ``mpcns_post`` readers
and manifest, not inferred from coordinates or file-size heuristics.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
import time
from typing import Callable, Iterable

import numpy as np


_STATIC_TYPES = {"geometry": 1, "topology": 2, "reconstruction": 3, "constant_field": 4}
_DTYPES = {1: np.dtype("i1"), 2: np.dtype("u1"), 3: np.dtype("<i4"), 4: np.dtype("<u4"),
           5: np.dtype("<i8"), 6: np.dtype("<u8"), 7: np.dtype("<f8")}
_HEADER = struct.Struct("<8sIIQQQQQQIIII")
_SECTION = struct.Struct("<32sIIQQ")


@dataclass(frozen=True)
class LocalMap:
    block: int
    location: str
    shape: tuple[int, int, int]
    gids: np.ndarray
    signs: np.ndarray
    owners: np.ndarray


class Diagnostics:
    """JSON-friendly wall-clock/RSS diagnostics and a hard RSS guard."""
    def __init__(self, budget_gb: float | None):
        self.started = time.monotonic()
        self.budget_bytes = None if budget_gb is None else int(float(budget_gb) * 1024 ** 3)
        self.events: list[dict] = []
        self.peak_rss = 0

    @staticmethod
    def rss_bytes() -> int:
        try:
            with open("/proc/self/statm", encoding="ascii") as stream:
                return int(stream.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            import resource
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(value) * (1024 if os.name != "darwin" else 1)

    def event(self, phase: str, **details) -> None:
        rss = self.rss_bytes(); self.peak_rss = max(self.peak_rss, rss)
        record = {"phase": phase, "elapsed_s": round(time.monotonic() - self.started, 3), "rss_bytes": rss, **details}
        self.events.append(record)
        if self.budget_bytes is not None and rss > self.budget_bytes:
            raise MemoryError(f"RSS {rss / 1024 ** 3:.2f} GiB exceeds --memory-budget-gb {self.budget_bytes / 1024 ** 3:.2f}")

    def report(self) -> dict:
        return {"peak_rss_bytes": self.peak_rss, "elapsed_s": round(time.monotonic() - self.started, 3), "events": self.events}


def load_manifest(directory: Path) -> dict:
    data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if data.get("format_name") != "MPCNS_PostData" or data.get("format_version") != 3:
        raise ValueError("streaming converter supports supplied MPCNS_PostData v3 only")
    if data.get("endianness") != "little" or data.get("float_type") != "float64" or data.get("index_type") != "int64":
        raise ValueError("unsupported MPCNS scalar layout")
    return data


def _sections(path: Path, expected: str, manifest: dict, wanted: Callable[[str], bool]) -> dict[str, np.ndarray]:
    """Scan a static MPCNSBIN file, materialising only requested sections."""
    output: dict[str, np.ndarray] = {}
    with path.open("rb") as stream:
        raw = stream.read(_HEADER.size)
        if len(raw) != _HEADER.size:
            raise ValueError(f"{path}: truncated MPCNSBIN header")
        magic, version, typ, header_bytes, payload_bytes, case_hi, case_lo, mesh_hi, mesh_lo, endian, fbytes, ibytes, reserved = _HEADER.unpack(raw)
        if (magic, version, typ, header_bytes, endian, fbytes, ibytes, reserved) != (b"MPCNSBIN", 1, _STATIC_TYPES[expected], 80, 1, 8, 8, 0):
            raise ValueError(f"{path}: unsupported {expected} header")
        if f"{case_hi:016x}{case_lo:016x}" != manifest["case_uuid"] or f"{mesh_hi:016x}{mesh_lo:016x}" != manifest["mesh_uuid"]:
            raise ValueError(f"{path}: case/mesh UUID mismatch")
        if payload_bytes != path.stat().st_size - _HEADER.size:
            raise ValueError(f"{path}: payload byte count mismatch")
        while stream.tell() < path.stat().st_size:
            pos = stream.tell(); raw = stream.read(_SECTION.size)
            if len(raw) != _SECTION.size:
                raise ValueError(f"{path}: truncated section header at {pos}")
            name_raw, code, components, count, nbytes = _SECTION.unpack(raw)
            name = name_raw.split(b"\0", 1)[0].decode("ascii")
            dtype = _DTYPES.get(code)
            if not name or dtype is None or components <= 0 or nbytes != count * components * dtype.itemsize:
                raise ValueError(f"{path}: invalid section {name!r} at {pos}")
            if wanted(name):
                payload = stream.read(nbytes)
                if len(payload) != nbytes:
                    raise ValueError(f"{path}: truncated section {name}")
                value = np.frombuffer(payload, dtype=dtype).copy()
                output[name] = value.reshape((count, components)) if components > 1 else value
            else:
                stream.seek(nbytes, os.SEEK_CUR)
    return output


def geometry(path: Path, manifest: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = _sections(path, "geometry", manifest, lambda n: n in {"node_global_id", "node_xyz", "cell_global_id"})
    required = {"node_global_id", "node_xyz", "cell_global_id"}
    if required - values.keys() or values["node_xyz"].shape != (values["node_global_id"].size, 3):
        raise ValueError(f"{path}: invalid required geometry sections")
    return values["node_global_id"].astype(np.int64, copy=False), values["node_xyz"], values["cell_global_id"].astype(np.int64, copy=False)


def cell_geometry(path: Path, manifest: dict, *, centers: bool) -> dict[str, np.ndarray]:
    """Read owner cell IDs with their physics flags and, optionally, centres."""
    wanted = {"cell_global_id", "cell_flags"} | ({"cell_center_xyz"} if centers else set())
    values = _sections(path, "geometry", manifest, lambda n: n in wanted)
    count = values.get("cell_global_id", np.empty(0)).size
    if wanted - values.keys() or values["cell_flags"].shape != (count,) or (centers and values["cell_center_xyz"].shape != (count, 3)):
        raise ValueError(f"{path}: missing/invalid cell flag or centre sections")
    values["cell_global_id"] = values["cell_global_id"].astype(np.int64, copy=False)
    values["cell_flags"] = values["cell_flags"].astype(np.uint32, copy=False)
    return values


def constant_fields(path: Path, manifest: dict, names: set[str]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Read selected manifest-described static constants, preserving global IDs."""
    descriptors = {str(item["name"]): str(item["section_prefix"]) for item in manifest.get("fields", [])}
    missing = names - descriptors.keys()
    if missing:
        raise ValueError(f"constant fields are absent from manifest: {sorted(missing)}")
    prefixes = {descriptors[name] for name in names}
    values = _sections(path, "constant_field", manifest,
                       lambda key: any(key.startswith(prefix + "_") for prefix in prefixes))
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in names:
        prefix = descriptors[name]
        try:
            meta, gids, raw = values[prefix + "_meta"], values[prefix + "_ids"], values[prefix + "_values"]
        except KeyError as exc:
            raise ValueError(f"{path}: missing constant sections for {name}") from exc
        meta = np.asarray(meta).reshape(-1)
        if meta.size != 3 or int(meta[1]) != 1 or raw.shape != gids.shape or not np.all(np.isfinite(raw)):
            raise ValueError(f"{path}: invalid constant field {name}")
        result[name] = (np.asarray(gids, dtype=np.int64), np.asarray(raw, dtype=np.float64))
    return result


def topology_maps(path: Path, manifest: dict) -> list[LocalMap]:
    values = _sections(path, "topology", manifest, lambda n: n.startswith("b") and n.endswith(("_shape", "_gid", "_sign", "_owner")))
    groups: dict[str, dict[str, np.ndarray]] = {}
    for name, value in values.items():
        base, part = name.rsplit("_", 1); groups.setdefault(base, {})[part] = value
    locations = ("node", "cell", "edge_xi", "edge_eta", "edge_zeta", "face_xi", "face_eta", "face_zeta")
    maps = []
    for base, group in sorted(groups.items()):
        if set(group) != {"shape", "gid", "sign", "owner"}:
            raise ValueError(f"{path}: incomplete selected local map {base}")
        shape = np.asarray(group["shape"]).reshape(-1)
        if shape.size != 5:
            raise ValueError(f"{path}: invalid local-map shape {base}")
        block, location, ni, nj, nk = map(int, shape)
        count = ni * nj * nk
        if location not in range(len(locations)) or any(group[key].size != count for key in ("gid", "sign", "owner")):
            raise ValueError(f"{path}: invalid local-map payload {base}")
        signs = group["sign"].astype(np.int32, copy=False)
        if not np.all((signs == 1) | (signs == -1)):
            raise ValueError(f"{path}: invalid orientation sign {base}")
        maps.append(LocalMap(block, locations[location], (ni, nj, nk), group["gid"].astype(np.int64, copy=False), signs, group["owner"].astype(bool, copy=False)))
    return maps


@dataclass(frozen=True)
class FaceStorage:
    """v3 DEC column space and this rank's raw restart-ghost B-face columns."""
    quotient_count: int
    column_count: int
    ghost_columns: np.ndarray
    ghost_addresses: np.ndarray


def face_storage(path: Path, manifest: dict) -> FaceStorage:
    names = {"Bstore_meta", "Bstore_global_id", "Bstore_quotient_id", "Bstore_address"}
    values = _sections(path, "topology", manifest, lambda n: n in names)
    if names - values.keys():
        raise ValueError(f"{path}: DEC current needs v3 Bstore_* topology; regenerate DATA_bin")
    meta = np.asarray(values["Bstore_meta"]).reshape(-1)
    gids, qids, addresses = values["Bstore_global_id"], values["Bstore_quotient_id"], values["Bstore_address"]
    if meta.size != 2 or not 0 <= meta[0] <= meta[1] or qids.shape != gids.shape or addresses.shape != (gids.size, 6):
        raise ValueError(f"{path}: invalid Bstore metadata/arrays")
    quotient = qids >= 0
    # Quotient columns are the ordinary global Face IDs; only ghosts need restart addresses.
    if np.any(gids[quotient] != qids[quotient]) or np.any(qids[quotient] >= meta[0]):
        raise ValueError(f"{path}: Bstore quotient columns are not global Face IDs")
    ghosts = ~quotient
    if np.any(gids[ghosts] < meta[0]) or np.any(gids[ghosts] >= meta[1]):
        raise ValueError(f"{path}: Bstore ghost columns lie outside the declared column space")
    return FaceStorage(int(meta[0]), int(meta[1]), gids[ghosts].astype(np.int64, copy=False), addresses[ghosts].astype(np.int64, copy=False))


def reconstruction(path: Path, manifest: dict, names: Iterable[str]) -> dict[str, np.ndarray]:
    needed = set(names)
    return _sections(path, "reconstruction", manifest, lambda n: n in needed)


def restart_fields(path: Path, manifest: dict, wanted: set[str], consume: Callable[[str, int, tuple[int, int, int], tuple[int, int, int], np.ndarray | None], None]) -> tuple[int, float]:
    """Stream selected restart blocks, immediately releasing all others."""
    specs = {str(item["name"]): item for item in manifest["existing_dynamic_data"]["fields"]}
    with path.open("rb") as stream:
        if stream.read(8) != b"MPCNSRST":
            raise ValueError(f"{path}: bad restart magic")
        version, step = struct.unpack("<ii", stream.read(8)); value_time = struct.unpack("<d", stream.read(8))[0]
        nblock, nfield = struct.unpack("<ii", stream.read(8))
        if version != 1 or nblock < 0 or nfield < 0:
            raise ValueError(f"{path}: unsupported restart header")
        for _ in range(nfield):
            count = struct.unpack("<i", stream.read(4))[0]; name = stream.read(count).decode("ascii")
            location, components, _nghost = struct.unpack("<iii", stream.read(12))
            spec = specs.get(name)
            if spec is None or (location, components) != (int(spec["location_code"]), int(spec["components"])):
                raise ValueError(f"{path}: unexpected restart field {name}")
            for block in range(nblock):
                lo = struct.unpack("<iii", stream.read(12)); hi = struct.unpack("<iii", stream.read(12)); active = struct.unpack("<i", stream.read(4))[0]
                shape = tuple(h - l for l, h in zip(lo, hi)); total = int(np.prod(shape, dtype=np.int64)) * components
                if active not in (0, 1) or min(shape) < 0:
                    raise ValueError(f"{path}: invalid {name} block {block}")
                values = None
                if active and name in wanted:
                    raw = stream.read(total * 8)
                    if len(raw) != total * 8:
                        raise ValueError(f"{path}: truncated {name} block {block}")
                    values = np.frombuffer(raw, dtype="<f8").copy().reshape((*shape, components))
                else:
                    # Inactive restart blocks retain their extent header but
                    # intentionally carry no payload (the authoritative
                    # mpcns_post reader materialises NaNs locally).
                    if active:
                        stream.seek(total * 8, os.SEEK_CUR)
                if name in wanted:
                    consume(name, block, lo, hi, values)
    return step, value_time


def write_vtu(path: Path, *, metadata: dict, points: np.memmap, fields: dict[str, np.memmap],
              cells: np.memmap, offsets: np.memmap, types: np.memmap, cell_data: dict[str, np.memmap]) -> None:
    """Write standard one-piece appended-raw VTK XML without constructing VTK."""
    from xml.sax.saxutils import quoteattr

    arrays: list[tuple[str, str, int, np.ndarray]] = [("FieldData", "pypost_data3d_v1_json_utf8", 1, np.frombuffer(json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"), dtype=np.uint8))]
    arrays.extend(("PointData", name, 1 if value.ndim == 1 else value.shape[1], value) for name, value in fields.items())
    arrays.append(("Points", "Points", 3, points))
    arrays.extend((("Cells", "connectivity", 1, cells), ("Cells", "offsets", 1, offsets), ("Cells", "types", 1, types)))
    arrays.extend(("CellData", name, 1 if value.ndim == 1 else value.shape[1], value) for name, value in cell_data.items())
    vtk_types = {np.dtype("uint8"): "UInt8", np.dtype("int32"): "Int32", np.dtype("int64"): "Int64", np.dtype("float64"): "Float64"}
    offsets_bytes = []; cursor = 0
    for _, _, _, value in arrays:
        size = int(np.asarray(value).nbytes); offsets_bytes.append(cursor); cursor += 8 + size
    groups: dict[str, list[tuple[str, int, np.ndarray, int]]] = {name: [] for name in ("FieldData", "PointData", "Points", "Cells", "CellData")}
    for (group, name, components, value), offset in zip(arrays, offsets_bytes):
        groups[group].append((name, components, value, offset))
    def data_array(name, components, value, offset):
        dtype = vtk_types.get(np.asarray(value).dtype)
        if dtype is None: raise ValueError(f"unsupported VTK dtype {np.asarray(value).dtype}")
        suffix = "" if components == 1 else f" NumberOfComponents={quoteattr(str(components))}"
        if name == "pypost_data3d_v1_json_utf8":
            suffix += f" NumberOfTuples={quoteattr(str(np.asarray(value).size))}"
        return f"<DataArray type={quoteattr(dtype)} Name={quoteattr(name)}{suffix} format=\"appended\" offset={quoteattr(str(offset))}/>"
    lines = ["<?xml version=\"1.0\"?>", "<VTKFile type=\"UnstructuredGrid\" version=\"1.0\" byte_order=\"LittleEndian\" header_type=\"UInt64\">", "<UnstructuredGrid>", "<FieldData>"]
    lines.extend(data_array(*item) for item in groups["FieldData"])
    lines.extend(["</FieldData>", f"<Piece NumberOfPoints={quoteattr(str(len(points)))} NumberOfCells={quoteattr(str(len(types)))}>"])
    for group in ("PointData", "CellData", "Points", "Cells"):
        lines.append(f"<{group}>"); lines.extend(data_array(*item) for item in groups[group]); lines.append(f"</{group}>")
    lines.extend(["</Piece>", "</UnstructuredGrid>", "<AppendedData encoding=\"raw\">_"])
    with path.open("wb") as stream:
        stream.write("\n".join(lines).encode("utf-8"))
        for _, _, _, value in arrays:
            array = np.asarray(value)
            stream.write(struct.pack("<Q", array.nbytes))
            # memmap.tofile avoids making a second full in-memory byte string.
            array.tofile(stream)
        stream.write(b"\n</AppendedData>\n</VTKFile>\n")
