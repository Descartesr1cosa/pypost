"""PyVista-backed 3-D/OpenFOAM data access with field-location metadata."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Literal
import json

import numpy as np

from .data3d_protocol import FORMAT as DATA3D_FORMAT
from .data3d_protocol import VERSION as DATA3D_VERSION
from .data3d_protocol import METADATA_ARRAY as DATA3D_METADATA_ARRAY
from .data3d_protocol import encode_metadata, metadata_from_mesh, standard_metadata

FieldLocation = Literal["point", "cell", "face", "edge"]


@dataclass(frozen=True)
class FieldInfo:
    name: str
    location: FieldLocation
    components: int
    shape: tuple[int, ...] = ()
    dtype: str = "unknown"
    unit: str | None = None
    description: str | None = None
    provenance: str | None = None


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
        mesh = pv.read(path)
        embedded = metadata_from_mesh(mesh)
        if embedded is not None:
            physical_time = embedded.get("physical_time")
            return cls(mesh, str(path), float(physical_time) if time is None and physical_time is not None else time, embedded)
        metadata_path = path.with_suffix(path.suffix + ".pypost.json")
        metadata = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {"metadata_warning": f"unreadable sidecar: {metadata_path}"}
        return cls(mesh, str(path), time, metadata)

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
                infos.extend(Data3D(block, metadata=self.metadata).field_info)
            return list(dict.fromkeys(infos))
        descriptors = self.metadata.get("fields", {}) if isinstance(self.metadata.get("fields", {}), dict) else {}
        infos = []
        for location, arrays in (("point", self.mesh.point_data), ("cell", self.mesh.cell_data)):
            for name in arrays:
                values = np.asarray(arrays[name])
                descriptor = descriptors.get(str(name), {}) if location == "point" else {}
                infos.append(FieldInfo(str(name), location,
                                       int(np.prod(values.shape[1:])) if values.ndim > 1 else 1,
                                       tuple(values.shape), str(values.dtype), descriptor.get("unit"),
                                       descriptor.get("description"), descriptor.get("provenance")))
        return infos

    @property
    def is_data3d_v1(self) -> bool:
        """Whether this object carries the strict self-contained v1 contract."""
        return self.metadata.get("format") == DATA3D_FORMAT and self.metadata.get("format_version") == DATA3D_VERSION

    standard_metadata = staticmethod(standard_metadata)

    def location_of(self, field: str) -> FieldLocation:
        locations = {info.location for info in self.field_info if info.name == field}
        if len(locations) != 1:
            raise KeyError(f"Field {field!r} is absent or ambiguous across locations: {locations}")
        return locations.pop()

    def save_data3d_v1(self, path: str | Path, binary: bool = True) -> Path:
        """Write a strict, self-contained Data3D v1 ``.vtu`` file.

        Metadata is encoded in VTK FieldData rather than in a sidecar.  The
        bytes are immediately re-read to prove that the selected VTK writer
        preserved the complete JSON document.
        """
        import pyvista as pv
        from .data3d_protocol import validate_v1_mesh

        target = Path(path)
        if target.suffix.lower() != ".vtu":
            raise ValueError("Data3D v1 requires a single .vtu UnstructuredGrid file")
        if not isinstance(self.mesh, pv.UnstructuredGrid):
            raise TypeError("Data3D v1 requires pyvista.UnstructuredGrid, not structured or MultiBlock data")
        metadata = dict(self.metadata)
        if self.time is not None and "physical_time" not in metadata:
            metadata["physical_time"] = float(self.time)
        candidate = self.mesh.copy(deep=False)
        candidate.field_data[DATA3D_METADATA_ARRAY] = encode_metadata(metadata)
        issues = validate_v1_mesh(candidate, metadata)
        if issues:
            raise ValueError("Cannot write invalid Data3D v1: " + "; ".join(issues))
        target.parent.mkdir(parents=True, exist_ok=True)
        candidate.save(target, binary=binary)
        persisted = metadata_from_mesh(pv.read(target))
        if persisted != metadata:
            raise RuntimeError("VTK writer did not preserve Data3D v1 embedded metadata exactly")
        return target

    def save(self, path: str | Path, binary: bool = True) -> None:
        """Write VTK XML data (e.g. .vtu or .vtm) readable by ParaView."""
        path = Path(path)
        if self.is_data3d_v1:
            self.save_data3d_v1(path, binary=binary)
            return
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
