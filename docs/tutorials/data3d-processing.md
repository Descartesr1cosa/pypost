# Data3D v1 processing: fields, slices, and lines

These operations require only a self-contained Data3D v1 `.vtu`; they do not
load Mercury readers or solver-specific reconstruction code.

## Python API

```python
from sciplot import Data3D
from sciplot.processing import derive_field, extract_slice, sample_line

volume = Data3D.from_file("mercury_B_003532299.vtu")
bmag = derive_field(volume, name="B_induced_mag", operation="magnitude", field="B_induced")

xz = extract_slice(
    volume, origin=[0, 0, 0], normal=[0, -1, 0], u_direction=[1, 0, 0],
    fields=["B_induced", "B_induced_mag"], derived={"B_induced_mag": bmag},
)
xz.save("xz.vtp")

profile = sample_line(
    volume, start=[-3, 0, 0], end=[3, 0, 0], n_points=501,
    fields=["B_induced", "B_induced_mag"], derived={"B_induced_mag": bmag},
)
```

`derive_field` returns just the new array and descriptor; it does not clone or
rewrite the full volume.  A requested VTK slice intersects the real volume
mesh, preserves physical holes, and writes world coordinates plus `plane_u`
and `plane_v`.  Vector fields retain Cartesian components; use
`slice.project_vector("B_induced")` for in-plane `(u,v)` values.

Line output is `Data1D` with coordinate `s`, world `x/y/z`, `valid`, selected
arrays, and scalar `*_x`, `*_y`, `*_z` components for each selected vector.
Points outside the actual mesh have `valid=0` and NaN field values—they are
never extrapolated or filled with zero.

Save a reusable line through the normal I/O API:

```python
from sciplot.io import save_dataset
save_dataset(profile, "x_profile.npz")
```

The resulting components can be selected directly by existing 1-D plotting
YAML, for example `B_induced_x`, `B_induced_y`, or `B_induced_z`.

## Declarative processing

```yaml
kind: data3d-process
input:
  path: mercury_B_003532299.vtu
derived:
  - name: B_induced_mag
    operation: magnitude
    field: B_induced
slices:
  - name: xz
    origin: [0, 0, 0]
    normal: [0, -1, 0]
    u_direction: [1, 0, 0]
    fields: [B_induced, B_induced_mag]
    output: derived/xz.vtp
lines:
  - name: x_profile
    start: [-3, 0, 0]
    end: [3, 0, 0]
    n_points: 501
    fields: [B_induced, B_induced_mag]
    output: derived/x_profile.npz
```

Run it once per source volume:

```bash
pypost process process.yml
```

Metadata in each VTP/NPZ records the source path/size/mtime, physical time,
coordinate and field units, dependencies, and operation parameters.  These
are cache keys for workflow tooling; a changed source identity or parameters
requires regeneration.

## Scope

This is ordinary VTK geometric interpolation of node fields.  It is not a
Mercury CT/DEC/Hodge operator and does not claim exact behavior at arbitrary
non-structural discontinuities or solver-specific staggered locations.

## Mercury acceptance run

The supplied `/tmp/mercury_B_003532299.vtu` was processed with the YAML above
on Linux.  Creating `B_induced_mag`, an XZ slice, an oblique slice, and a
501-point X line took 0.827 s with a 443,002,880-byte peak RSS.  The outputs
were 2.0 MiB (`xz.vtp`), 2.1 MiB (`oblique.vtp`), and 27 KiB
(`x_profile.npz`), rather than another full volume.  The XZ plane residual was
zero; the oblique-plane maximum residual was `1.8e-15`.  The line had 368
valid and 133 invalid samples; every invalid magnetic value was NaN.
