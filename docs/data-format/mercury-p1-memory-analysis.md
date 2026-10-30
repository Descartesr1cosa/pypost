# Mercury P1 memory analysis and streaming design

## Observed baseline

The supplied case contains 84 rank files and 96 blocks.  Its static `DATA_bin`
directory is 3.4 GiB; the supplied restart is 218 MiB.  The previous converter
called `MPCNSCase.load()`, which retains every geometry, topology,
reconstruction, constant-field, and restart rank object, then builds global
concatenated copies and asks PyVista to assemble another complete mesh.  A real
run reached 6.2 GiB RSS before it wrote a file.

That establishes the primary cause: whole-case static-section retention and
global NumPy copies, not the small restart alone.  The former `BinaryReader`
also reads each complete static file into a `bytes` object before decoding.

## P1 replacement

`examples/converters/mercury/streaming.py` decodes the documented MPCNSBIN v3
header/section layout selectively, one rank at a time.  It reads only geometry
node/cell IDs and coordinates, structured topology maps, requested restart
blocks, and the two required reconstruction operators.  All full-size arrays
are `numpy.memmap` files in an explicit temporary directory:

1. owner global node/cell ID indices and points;
2. owner-only cell connectivity plus source identifiers;
3. selected cell fields and oriented face flux storage;
4. per-field nodal numerator/denominator and final PointData arrays.

The converter never uses coordinates to merge nodes.  It checks owner IDs,
block node/cell shapes, B-face alias conflicts, missing operator inputs, and
repeated nodes in a candidate hex.  A collapsed axis cell is a hard failure;
it is not skipped or retained as a degenerate hexahedron.

The standard single-piece `.vtu` is written directly as VTK XML appended raw
binary from the memmaps.  This avoids PyVista's final full-mesh copy.  It uses
64-bit block lengths, connectivity, and offsets.  Output is first written as
`*.vtu.partial`, and renamed only after writing finishes.  `--verify-readback`
is intentionally opt-in because VTK must materialise every selected field to
read a very large file.

## Diagnostics and budgets

`--memory-budget-gb` (default 4) samples actual RSS from `/proc/self/statm`
after every rank/phase and fails as soon as the ceiling is exceeded.  With
`--keep-temp`, `diagnostics.json` records phase, rank, processed nodes/cells,
elapsed seconds, RSS, and peak RSS.  The embedded conversion report records
`ranks_processed`, `blocks_processed`, `local_nodes`,
`unique_global_nodes`, `interface_aliases`, `physical_cells`, `cell_types`,
`invalid_cells`, `skipped_cells`, `owner_alias_discrepancies`, source/output
fields, reconstruction methods, temporary bytes, and memory diagnostics.

`pypost validate --deep` now streams SHA-256 input in 8 MiB chunks rather than
calling `read_bytes()` on an entire large `.vtu`.

## Current verification boundary

The appended-raw writer has a synthetic tetrahedron round-trip test with
PyVista and Data3D v1 validation.  Full supplied-case conversion remains a
separate integration run because its expected temporary disk/output size and
optional VTK readback exceed normal CI resources.  It must be run with a
dedicated temp filesystem and enough disk, then validated independently on a
machine that can load the final file.

## Supplied-case B-field acceptance run

On the supplied `Step_003532299_Time_7.988853e+01` restart, the command below
completed under its 4 GiB budget:

```bash
python -m examples.converters.mercury \
  --config mercury.yml
```

The artifact is `/tmp/mercury_B_003532299.vtu` (144,115,106 bytes; 138 MiB),
with SHA-256
`214eb5ab2ccf9d25fd7f7f94273ae6d98e6b9c2c9173854b6f2ea187a8ef8558`.
Its independent `pypost validate --deep` result is valid with no issues.

| Measure | Result |
| --- | ---: |
| Physical time | 79.88853291177699 s |
| Unique nodes | 1,054,616 |
| Local node references | 1,202,712 |
| Interface aliases | 148,096 |
| Physical cells | 1,049,760 |
| Cell types | 1,049,760 `VTK_HEXAHEDRON` |
| Invalid/skipped cells | 0 / 0 |
| Output PointData | `B_induced` `(N,3)` in nT |
| Peak RSS | 417,091,584 bytes (398 MiB) |
| End-to-end converter elapsed time | 8.3 s |
| Temporary buffers | 291,323,536 bytes |

Independent VTK/PyVista loading through `pypost inspect` and the strict
validator accepted every hexahedron, including near-axis geometry; no repeated
cell node IDs or zero-volume cells were reported.  The output deliberately names the field
`B_induced`, rather than implying that constant/additive field reconstruction
was included.  Multi-species fields can be added with `--fields` after their
chosen temporary-disk capacity is provisioned.
