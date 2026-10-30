# Data3D v1: solver-independent three-dimensional exchange contract

Data3D v1 is the only formal pypost 3-D interface between a solver-specific
converter and generic post-processing.  A conforming file is one self-contained
binary (or ASCII) VTK XML **UnstructuredGrid** file:

```text
mercury_000100.vtu
```

It can be opened by VTK/PyVista, but this document adds requirements that VTK
alone does not express.  In particular, v1 is not a `.vtm` collection and is
not a collection of independently numbered blocks.

## Normative storage rules

- The file extension is `.vtu` and the dataset is `vtkUnstructuredGrid`.
- `Points` has shape `(N, 3)` and is `float64` on output from a converter.
- Connectivity uses one global zero-based point table.  A topological node has
  exactly one PointData tuple.  Coincident coordinates are not proof of
  topological identity and must not be coalesced on that basis.
- The VTK cells retain their actual valid three-dimensional VTK type.  A
  collapsed hexahedron at a rotation axis is invalid; a converter must emit an
  appropriate valid cell, use a separately validated conversion, or fail.
- Every physical variable is VTK `PointData`; scalar shape is `(N,)`, Cartesian
  vector shape `(N,3)`, and tensor shape `(N,9)`.  Tensors are flattened in
  `xx,xy,xz,yx,yy,yz,zx,zy,zz` row-major order.
- `CellData` is reserved for mesh/source information.  `SourceBlockId` is a
  required integer CellData array with one entry per cell.  `RegionId`, owner
  rank, and similar non-physical topology provenance are allowed only when
  described in metadata.
- `NaN` means an explicitly documented unavailable/invalid value. `Inf` is
  forbidden.  A field does not silently move from cell/face/edge to points.

## Embedded metadata (required)

The metadata document is UTF-8 JSON encoded as an unsigned-byte VTK FieldData
array named `pypost_data3d_v1_json_utf8`.  It is not a VTK string array: byte
encoding is intentional so readers can round-trip it reliably.  No sidecar is
required to understand a v1 file.  A sidecar may be added for human readers but
is non-authoritative.

The JSON object requires these keys:

```json
{
  "format": "pypost-data3d",
  "format_version": 1,
  "physical_time": 79.88853,
  "time_unit": "s",
  "coordinates": {"system": "Cartesian", "unit": "m", "components": ["x", "y", "z"]},
  "node_identity": {"contract": "global_unique"},
  "source": {"name": "mercury_to_data3d", "version": "..."},
  "fields": {},
  "cell_fields": {"SourceBlockId": {"role": "source_block_id"}},
  "normalization": {},
  "conversion": {}
}
```

`physical_time` and all coordinate/time units are required even for normalized
data (use an explicit unit such as `1` and document reference scales in
`normalization`).  `source` identifies the producing converter/data version.
`normalization` holds named reference values and units; it must not be inferred
from field magnitudes.

Each PointData name has a field descriptor.  Required descriptor keys are
`kind`, `components`, `unit`, and `provenance`; `description` is strongly
recommended.  `kind` is `scalar`, `vector`, or `tensor`; its component count is
respectively 1, 3, or 9.  `provenance` is `native`, `reconstructed`, or
`derived`.  Vectors additionally require `component_system: "Cartesian"`;
tensors additionally require the exact `flattening` string
`row-major-xx-xy-xz-yx-yy-yz-zx-zy-zz`.

Example vector descriptor:

```json
"B": {
  "kind": "vector", "components": 3, "unit": "T",
  "component_system": "Cartesian", "provenance": "reconstructed",
  "description": "Magnetic flux density reconstructed from solver face 2-form"
}
```

Separate `Bx`, `By`, `Bz` scalar arrays may coexist with `B`; their relationship
must be documented by the converter.  Solver contravariant/covariant
components, face fluxes, edge forms, halos, and Hodge data are not Data3D
physical fields.  They must be reconstructed and transformed by the converter
before this interface is written.

## Converter obligations

A multi-block converter establishes `(block_id, local_node_index) -> global_id`
from authoritative topology/owner/alias information.  It chooses one
deterministic owner, checks alias values against declared tolerances, and stops
on a discrepancy instead of averaging silently.  It records its reconciliation
report in `conversion`, including local/unique/alias counts, cell counts by
type, skipped/invalid cells, and field-consistency statistics.

The `global_unique` declaration is a converter contract, not a geometric
deduplication request.  Axis nodes, seams, and physically distinct coincident
nodes require solver topology to distinguish them.  The pypost validator can
check connectivity, field lengths, finite values, descriptors, cell volumes,
and the declared contract; it cannot reconstruct solver aliases after the fact.

## Public API and validation

```python
from sciplot import Data3D, inspect_dataset, validate_dataset

data = Data3D.from_file("mercury_000100.vtu")
assert data.is_data3d_v1
print(data.field_info)
print(inspect_dataset("mercury_000100.vtu"))
assert validate_dataset("mercury_000100.vtu", deep=True)["valid"]
```

`pypost validate --deep` verifies version, embedded JSON, point/cell tuple
counts, connectivity bounds, duplicated cell-node IDs, volume-cell geometry,
finite points/fields, field descriptors, source metadata, and the global-node
contract declaration.  It deliberately does not claim to prove a solver's
unavailable topology-equivalence data.

## Compatibility and time series

Legacy VTK (`.vti`, `.vts`, `.vtp`, `.vtm`) remains readable by `Data3D` for
existing OpenFOAM and Q workflows, but is not automatically Data3D v1.  A `.vtm`
with per-block point arrays cannot satisfy this standard unless a converter has
already assembled it into one `.vtu` global point table.

Each time step remains self-contained.  An optional `pypost-3d-time-index`
may reference several files, but it never supplies metadata that a single v1
file needs in order to be read or validated.

## Large-file conversion reports

A converter should put its audit trail in `conversion.report`.  Data3D v1
defines these report keys: `ranks_processed`, `blocks_processed`,
`local_nodes`, `unique_global_nodes`, `interface_aliases`, `physical_cells`,
`cell_types`, `invalid_cells`, `skipped_cells`, `owner_alias_discrepancies`,
`source_fields`, `output_fields`, `reconstruction_methods`, and `peak_memory`.
Counts are integers, `cell_types` is a name-to-count object, and memory values
are byte counts.  Converter-specific tolerance definitions, worst alias
discrepancy, source rank/block/local index, temporary disk usage, and timing
may be added as JSON values.  A zero discrepancy is not evidence that aliases
were discovered from coordinates: the method must be stated explicitly.
