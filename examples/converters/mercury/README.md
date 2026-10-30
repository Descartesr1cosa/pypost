# Mercury → Data3D v1

This is a one-time, Mercury-specific adapter.  It uses the supplied
`mpcns_post` package to parse its documented binary files, reconcile global
owner/alias maps, apply its face-form/DEC reconstruction operators, and project
approved cell values to the globally unique node table.  No module in
`sciplot/` imports `mpcns_post`.

```bash
python examples/converters/mercury/mercury_to_data3d.py \
  --static-dir /workspace/tCOM/pypost_examples/exampleMercury_data/DATA_bin \
  --data-dir /workspace/tCOM/pypost_examples/exampleMercury_data/DATA_archive/Step_003532299_Time_7.988853e+01 \
  --output mercury_003532299.vtu

pypost inspect mercury_003532299.vtu
pypost validate mercury_003532299.vtu --deep
```

The converter stops on a missing owner map, a topology shape mismatch, or a
collapsed axis cell.  It does not merge coordinates, average interface values,
or write a superficially valid degenerate hexahedron.  A polar-cell conversion
rule must be implemented from authoritative solver topology before a case with
such cells can be exported.

The default is a 4 GiB observed-RSS ceiling and disk-backed temporary buffers.
For a small first acceptance artifact, request only the confirmed magnetic
field and retain diagnostics:

```bash
python examples/converters/mercury/mercury_to_data3d.py \
  --static-dir .../DATA_bin --data-dir .../Step_003532299_Time_7.988853e+01 \
  --output mercury_B.vtu --fields B_induced --memory-budget-gb 4 \
  --temp-dir /fast/scratch --keep-temp
```

The supported output names are `B_induced`, `H_density`, `H_velocity`,
`H_pressure`, `Na_density`, `Na_velocity`, and `Na_pressure`.  The converter
uses the documented `MPCNSBIN` v3/restart layout directly; it has no runtime
dependency on `mpcns_post`.  `--verify-readback` uses PyVista after writing and
may require memory comparable to the output dataset.
