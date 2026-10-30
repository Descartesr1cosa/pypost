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
- `configs/all_fields.example.yml` — H/Na fields, induced/additive/total B,
  DEC current, and all electric terms (Fluid-only output, see below).

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

## Fluid and Solid domains

`U_H`/`U_Na` are undefined in Mercury Solid cells (no density), so the ion
fields (`H_*`, `Na_*`) and every electric term (`E_motional`, `E_Hall`,
`E_ambipolar`, `E_generalized`) are **Fluid-only**. Solid cells are never given
zeros or NaNs for them. The optional top-level `region` key selects the output:

- `auto` (default): `fluid` if any Fluid-only field is requested, else `all`.
- `fluid` / `solid` / `all`: explicit; a Fluid-only field with `solid`/`all`
  is rejected before any rank is read.

`B_induced`, `B_additive`, `B_total` and `J_induced` exist in both domains.
Output keeps only cells of the region and the nodes they use; nodal values use
the solver's cell→node weights restricted to that region and renormalized.
Every output value is checked finite before writing, and `PhysicsCode`
(1=Fluid, 2=Solid) is stored per cell.

## Electromagnetic fields

All are computed from the MPCNS v3 files themselves; no external Mercury
post-processing package is needed.

- `B_induced`: restart face fluxes → `Bcell` operator. `B_additive`: static
  `Badd_*` face constants through the same operator. `B_total` is their sum.
- `J_induced`: v3 DEC chain `B-face (+raw ghost columns, Bstore) → J-edge →
  J-cell`, from induced B only (as in the solver).
- With `n_e = n_H + n_Na`, `u+ = (n_H u_H + n_Na u_Na)/n_e`, `p_e = p_H + p_Na`:
  `E_motional = -u+ × B_total`, `E_Hall = J_induced × B_total/(e n_e)`,
  `E_ambipolar = -∇p_e/(e n_e)` (blockwise curvilinear gradient on Fluid
  blocks), `E_generalized` = sum. Output in mV/m; `J` in nA/m², `B` in nT.

On the example case (84 ranks) all 14 fields convert in ~16 s with ~1.6 GB
peak RSS and agree with the original `Postprocess` script to ≤2e-15 relative.

The converter stops on missing owner maps, topology mismatches, duplicate owner
IDs, alias inconsistencies, and degenerate polar hexahedra. It never merges
nodes by coordinate or silently averages interface values. See the
[memory analysis](../../../docs/data-format/mercury-p1-memory-analysis.md) for
the validated streaming design and measured artifact.
