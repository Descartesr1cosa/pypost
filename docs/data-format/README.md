# pypost standard data format, version 1

This document is the contract for converter authors. A converter reads any
solver, instrument, or laboratory format and writes a pypost standard dataset.
The core library deliberately does not need to learn every external format.

```text
external data -> converter Python script -> standard dataset -> validate -> YAML plot/render
```

Use the public API only:

```python
from sciplot.io import save_dataset, load_dataset, inspect_dataset, validate_dataset
```

`save_dataset` is strict for new files. It records a `pypost-dataset` JSON
header with `format_version: 1`, rejects Inf, never uses pickle, and does not
silently reshape, interpolate, relocate fields, or discard topology. Legacy
CSV, NPZ, and VTK files remain readable through `load_dataset`, but may not
carry the full versioned header.

## Compatibility policy

Format versions are integer protocol versions. A v1 reader accepts v1 files.
An unknown version is an error, never a best-effort reinterpretation. New
optional metadata may be added without changing the version; required semantic
or array-layout changes require a new version and an explicit migration tool.

Every standard file records:

- `format: "pypost-dataset"`, `format_version: 1`, `dimension`, and `encoding`;
- field name, location, shape, dtype and number of components;
- units and coordinate information where relevant;
- JSON-serializable `metadata`, normally including external source, case,
  physical time, converter version, and non-destructive conversion notes.

Paths in metadata and index files should be relative to their containing
standard-data directory whenever possible. A converter must not store Python
objects, code, or untrusted pickle payloads.

## Numeric rules

Arrays are NumPy numeric arrays. Binary NPZ preserves each array dtype and
shape, including `float32`, `float64`, signed/unsigned integer types, and a
field's trailing component axes. No dtype is silently promoted by standard
binary storage. VTK XML stores arrays through VTK/PyVista and preserves field
location and components subject to VTK's supported numeric types.

ASCII CSV and ASCII VTK are interoperable text formats. CSV is intentionally
limited to scalar 1-D fields; use NPZ for vector/tensor 1-D data. Text readers
may infer a platform numeric dtype, so exact dtype identity is guaranteed only
for binary storage. UTF-8 is used for JSON/YAML/CSV metadata and field names.

NaN is permitted and reported by `inspect`/`validate`; it must be deliberate
and documented by the converter. Infinite values are rejected by strict
`save_dataset`, because their physical meaning is too ambiguous for a default
scientific interchange format. NPZ follows NumPy's normal byte-order markers;
VTK XML declares byte order in its XML header. Both are portable readers, not
native-memory dumps. NPZ uses ZIP compression; VTK XML's compression is owned
by VTK.

## 1-D data

Use `Data1D(x, fields, x_name=..., sort=False)` when sample order is
meaningful. The historical `Data1D.from_file` default still sorts by coordinate
for plotting compatibility; standard binary loading uses `sort=False` and
therefore preserves saved order.

- Coordinate: numeric array with shape `(N,)`, named by `x_name`, optional
  `x_unit`.
- Scalar field: shape `(N,)`.
- Vector/tensor field: shape `(N, c1, c2, ...)`; component axes are retained in
  NPZ and are not accepted by CSV.
- All fields have first dimension `N`; no implicit alignment is performed.
- Binary: `.npz`, `encoding="binary"`.
- ASCII: `.csv`, `encoding="ascii"`, scalar fields only, with a `.csv.json`
  version header beside it.

Example:

```python
data = Data1D(time, {"Cd": cd, "U": velocity}, x_name="time", sort=False)
save_dataset(data, "standard/force_history.npz")
```

## 2-D data

`Data2D.points` has shape `(N, 2)` in an explicitly defined planar coordinate
system. If a 2-D slice comes from an arbitrary 3-D plane, put the mapping in
metadata:

```yaml
plane:
  origin: [x0, y0, z0]
  basis_u: [ux, uy, uz]
  basis_v: [vx, vy, vz]
```

Then local point `[u, v]` maps to `origin + u*basis_u + v*basis_v`. Omitting
this metadata means local Cartesian XY coordinates only.

- Point fields have shape `(N, ...)` and are stored in `point_fields`.
- Cell fields have shape `(M, ...)` and are stored in `cell_fields`; their
  centers have shape `(M, 2)`.
- Strict topology is VTK cell-stream connectivity: `[n, id0, ..., id(n-1),
  n, ...]`, with zero-based point IDs. `cell_types`, when supplied, has one VTK
  cell-type integer per cell.
- Connectivity IDs must be in `[0, N)`, and cell field/center counts must
  match the number of connectivity cells. Failure is an error with its cell or
  offset named.
- Binary point clouds or arbitrary planar meshes: `.npz`.
- ASCII/Binary mesh interchange: VTK XML `.vtu`/`.vtp` when connectivity is
  present. A point cloud without connectivity must use `.npz`.

The old `Data2D.save_npz` is compatible for reading. New converters should use
`save_dataset`, which stores metadata and connectivity rather than dropping
them.

## 3-D data

3-D data uses VTK XML (`.vti`, `.vtu`, `.vts`, `.vtp`, `.vtm`) and a JSON
sidecar. `Data3D.mesh` may be a VTK dataset or MultiBlock dataset.

- PointData contains arrays with one tuple per mesh point.
- CellData contains arrays with one tuple per mesh cell.
- Scalar arrays have shape `(N,)`; vectors `(N, 3)`; tensors commonly
  `(N, 9)` or `(N, 3, 3)` before VTK flattening. Converters must record the
  component convention in metadata for tensors.
- PointData and CellData are never merged or silently interpolated.
- `encoding="binary"` selects binary VTK XML; `encoding="ascii"` selects
  human-readable VTK XML.
- `.vtm` is the MultiBlock root. Referenced child files are dependencies and
  must remain relative/movable with the root. `validate` checks each reference.

For multiple physical times, write one standard VTK file per time and one
`pypost-3d-time-index` JSON file with sorted, unique `{time, path}` entries.
Paths are stored relative to the index when possible. This is the input used by
the existing Q workflow.

## Inspection and validation

```bash
pypost inspect standard/force_history.npz
pypost validate standard/force_history.npz
pypost validate standard/case.vtm --deep
```

`inspect` reports format/version/encoding, field dtype/shape/components,
locations, ranges, NaN/Inf counts, mesh/topology counts, file size and memory
estimate. `validate` checks that structure without modifying it. `--deep` also
calculates SHA-256 for the root and `.vtm` dependencies. Validation errors name
the field, topology offset, dependency, or header that failed; no physical data
is automatically repaired.

Python callers receive JSON-serializable dictionaries:

```python
report = inspect_dataset("standard/slice.npz")
result = validate_dataset("standard/slice.npz", deep=True)
assert result["valid"], result["issues"]
```

## Future Prepare / Edit / Freeze boundary

This protocol separates full-precision data from presentation state. A future
`prepare` step may write a lightweight preview package and manifest that names
its full dataset, decimation policy, checksums and protocol versions. A desktop
editor should write only portable camera/layout/style JSON or YAML relative to
that manifest. A later `freeze` step can merge presentation configuration into
`final.yml`; cluster rendering must return to the full standard dataset, not
the preview. Changing a camera, font, layout JSON, or annotation must not
invalidate physical conversion or derived-field caches.
