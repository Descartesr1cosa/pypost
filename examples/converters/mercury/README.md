# Mercury MPCNS v3 → Data3D v1

This repository-local adapter converts one Mercury MPCNS binary restart into a
self-contained, globally unique-node Data3D v1 `.vtu`. It is not imported by
`sciplot`. The streaming reader uses the documented MPCNSBIN v3 layout,
owner/alias topology maps, solver reconstruction operators, and disk-backed
buffers; no generic pypost feature knows about halo cells, DEC, Hodge, or MPI.

## Run with YAML

Copy a template outside the repository, set `paths.data_root`, and run:

```bash
cp examples/converters/mercury/configs/b_only.example.yml mercury.yml
python -m examples.converters.mercury --config mercury.yml
```

Available templates:

- `configs/b_only.example.yml` — `B_induced` only, for a small acceptance artifact.
- `configs/all_fields.example.yml` — all currently confirmed H/Na/B fields.

```yaml
kind: mercury-data3d
paths: {data_root: /path/to/exampleMercury_data}
input:
  static_dir: DATA_bin
  data_dir: DATA_archive/Step_003532299_Time_7.988853e+01
fields: [B_induced]
output: {path: processed/mercury_B.vtu}
runtime:
  memory_budget_gb: 4
  temp_dir: processed/tmp
  keep_temp: false
  verify_readback: false
```

`data_root` is absolute as written, or relative to the YAML file. Every
relative path in `input`, `output`, and `runtime.temp_dir` is then resolved
under it. Absolute values are preserved, so the rule is independent of the
current working directory.

Before opening any rank payload, the entry point verifies manifest and rank
files, supported fields, a positive memory budget, legal temporary directory,
and a non-directory `.vtu` target. It refuses an existing output unless
`output.overwrite: true` is explicitly set.

```bash
pypost inspect /path/to/processed/mercury_B.vtu
pypost validate /path/to/processed/mercury_B.vtu --deep
```

## Compatibility flags

The lower-level flags remain available for development diagnostics:

```bash
python -m examples.converters.mercury \
  --static-dir /data/DATA_bin --data-dir /data/DATA_archive/Step_000000001 \
  --output /scratch/mercury.vtu --fields B_induced --memory-budget-gb 4
```

Prefer YAML for repeatable work. `--overwrite` is mandatory to replace a
result. `--verify-readback` uses PyVista after writing and may require memory
comparable to the final output. `--keep-temp` preserves memmaps and diagnostics
for troubleshooting.

The converter stops on missing owner maps, topology mismatches, duplicate owner
IDs, alias inconsistencies, and degenerate polar hexahedra. It never merges
nodes by coordinate or silently averages interface values. See the
[memory analysis](../../../docs/data-format/mercury-p1-memory-analysis.md) for
the validated streaming design and measured artifact.
