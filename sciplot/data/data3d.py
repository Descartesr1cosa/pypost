"""PyVista-backed 3-D/OpenFOAM data access with field-location metadata."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
        return cls(pv.read(path), str(path), time)

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

    def save(self, path: str | Path) -> None:
        """Write VTK XML data (e.g. .vtu or .vtm) readable by ParaView."""
        self.mesh.save(path)
