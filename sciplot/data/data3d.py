"""PyVista-backed 3-D/OpenFOAM data access with field-location metadata."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Literal
import json

FieldLocation = Literal["point", "cell", "face", "edge"]


@dataclass(frozen=True)
class FieldInfo:
    name: str
    location: FieldLocation
    components: int


@dataclass
class Data3D:
    mesh: object
    source: str | None = None
    time: float | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path, time: float | None = None, patches: list[str] | None = None) -> "Data3D":
        import pyvista as pv
        path = Path(path)
        if path.suffix.lower() == ".foam":
            reader = pv.OpenFOAMReader(str(path))
            if time is not None:
                reader.set_active_time_value(time)
            if patches is not None and hasattr(reader, "disable_all_patch_arrays"):
                reader.disable_all_patch_arrays()
                for patch in patches:
                    reader.enable_patch_array(patch)
            mesh = reader.read()
            return cls(mesh, str(path), time)
        metadata_path = path.with_suffix(path.suffix + ".pypost.json")
        metadata = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {"metadata_warning": f"unreadable sidecar: {metadata_path}"}
        return cls(pv.read(path), str(path), time, metadata)

    @classmethod
    def validate_openfoam_case(cls, path: str | Path, time: float | None = None) -> dict:
        """Read and verify the pieces needed for an OpenFOAM volume workflow.

        This is deliberately an explicit validation operation: a case is only
        reported valid after the requested time, ``internalMesh``, boundary
        collection, and field shapes have all been observed from the reader.
        """
        import pyvista as pv
        path = Path(path)
        if path.suffix.lower() != ".foam":
            raise ValueError("OpenFOAM validation requires a .foam marker file")
        reader = pv.OpenFOAMReader(str(path))
        times = [float(value) for value in reader.time_values]
        selected = time if time is not None else (times[-1] if times else None)
        if selected is None or selected not in times:
            raise ValueError(f"Requested time {selected} unavailable; reader times: {times}")
        reader.set_active_time_value(float(selected))
        mesh = reader.read()
        if not isinstance(mesh, pv.MultiBlock) or "internalMesh" not in mesh.keys():
            names = list(mesh.keys()) if isinstance(mesh, pv.MultiBlock) else []
            raise ValueError(f"OpenFOAM reader did not return internalMesh; blocks: {names}")
        internal = mesh["internalMesh"]
        boundary = mesh["boundary"] if "boundary" in mesh.keys() else None
        fields = []
        for item in cls(internal).field_info:
            arrays = internal.point_data if item.location == "point" else internal.cell_data
            fields.append({"name": item.name, "location": item.location, "components": item.components,
                           "dtype": str(getattr(arrays[item.name], "dtype", "unknown"))})
        return {"source": str(path), "available_times": times, "time": float(selected),
                "internal_mesh": {"type": type(internal).__name__, "points": internal.n_points, "cells": internal.n_cells},
                "boundary_patches": boundary.n_blocks if isinstance(boundary, pv.MultiBlock) else 0,
                "fields": fields}

    @property
    def field_info(self) -> list[FieldInfo]:
        """List fields while retaining PointData/CellData distinction."""
        import pyvista as pv
        if isinstance(self.mesh, pv.MultiBlock):
            infos: list[FieldInfo] = []
            for block in self.mesh.recursive_iterator(skip_none=True):
                infos.extend(Data3D(block).field_info)
            return list(dict.fromkeys(infos))
        infos = []
        for location, arrays in (("point", self.mesh.point_data), ("cell", self.mesh.cell_data)):
            for name in arrays:
                shape = getattr(arrays[name], "shape", ())
                infos.append(FieldInfo(str(name), location, shape[1] if len(shape) > 1 else 1))
        return infos

    def location_of(self, field: str) -> FieldLocation:
        locations = {info.location for info in self.field_info if info.name == field}
        if len(locations) != 1:
            raise KeyError(f"Field {field!r} is absent or ambiguous across locations: {locations}")
        return locations.pop()

    def save(self, path: str | Path, binary: bool = True) -> None:
        """Write VTK XML data (e.g. .vtu or .vtm) readable by ParaView."""
        path = Path(path)
        if path.suffix.lower() not in {".vtu", ".vts", ".vti", ".vtm", ".vtp"}:
            raise ValueError("3-D normalized output must be VTK XML (.vtu/.vts/.vti/.vtm/.vtp)")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.mesh.save(path, binary=binary)
        record = {
            "format": "pypost-3d", "format_version": 1, "source": self.source,
            "physical_time": self.time, "fields": [info.__dict__ for info in self.field_info],
            "metadata": self.metadata, "encoding": "binary" if binary else "ascii",
        }
        path.with_suffix(path.suffix + ".pypost.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )

    @staticmethod
    def save_time_index(path: str | Path, steps: list[dict], metadata: dict | None = None) -> None:
        """Write the portable index used for normalized multi-time VTK data.

        Each step has an explicit physical ``time`` and VTK XML ``path``. The
        index intentionally references files instead of collapsing grids into a
        synthetic ImageData volume.
        """
        target = Path(path).resolve()
        normalized = []
        for step in steps:
            source = Path(step["path"])
            if source.is_absolute():
                try:
                    source = source.resolve().relative_to(target.parent)
                except ValueError:
                    # External volumes remain explicit rather than producing a
                    # misleading relative path that cannot be resolved later.
                    source = source.resolve()
            normalized.append({"time": float(step["time"]), "path": str(source)})
        if len({item["time"] for item in normalized}) != len(normalized):
            raise ValueError("Time-series index cannot contain duplicate times")
        normalized.sort(key=lambda item: item["time"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"format": "pypost-3d-time-index", "format_version": 1,
                                      "steps": normalized, "metadata": metadata or {}}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    @staticmethod
    def load_time_index(path: str | Path) -> dict:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != "pypost-3d-time-index" or not isinstance(data.get("steps"), list):
            raise ValueError(f"Not a pypost 3-D time index: {path}")
        return data
