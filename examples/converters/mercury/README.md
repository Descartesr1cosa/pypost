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
fields (`H_*`, `Na_*`), every mixture/pressure-balance field except
`magnetic_pressure`, and every electric term (`E_*`) are **Fluid-only** (the same
holds for their `_nd` twins). Solid cells are never given
zeros or NaNs for them. The optional top-level `region` key selects the output:

- `auto` (default): `fluid` if any Fluid-only field is requested, else `all`.
- `fluid` / `solid` / `all`: explicit; a Fluid-only field with `solid`/`all`
  is rejected before any rank is read.

`B_induced`, `B_additive`, `B_total`, `J_induced` and `magnetic_pressure` exist in both domains.
Output keeps only cells of the region and the nodes they use; nodal values use
the solver's cell→node weights restricted to that region and renormalized.
Every output value is checked finite before writing, and `PhysicsCode`
(1=Fluid, 2=Solid) is stored per cell.

## Fields

Every field is computed per Fluid/Solid cell from the MPCNS v3 files and then
projected to nodes (so nonlinear quantities such as `magnetic_pressure` are
computed per cell first, not from projected components). Units: `B` nT,
`J` nA/m², `E` mV/m, velocity km/s, pressure nPa, density kg/m³,
number density cm⁻³, temperature K.

| Group | Fields |
| --- | --- |
| Magnetic | `B_induced`, `B_additive` (static `Badd`), `B_total` |
| Current | `J_induced` — v3 DEC `B-face (+raw ghost columns) → J-edge → J-cell`, induced B only |
| H⁺ / Na⁺ (Fluid) | `*_density`, `*_velocity`, `*_pressure`, `*_number_density` (ρ/m), `*_temperature` (p m/ρk_B), `*_dynamic_pressure` (ρ\|u\|², no ½) |
| Mixture (Fluid) | `electron_number_density` (n_H+n_Na), `ion_mass_density`, `ion_charge_velocity` u₊, `thermal_pressure` (p_H+p_Na = p_e), `dynamic_pressure` |
| Pressure balance | `magnetic_pressure` (\|B_total\|²/2μ₀, both domains), `total_pressure` (thermal + magnetic, Fluid), `plasma_beta` |
| Electric (Fluid) | `E_motional = -u₊×B_total`, `E_Hall = J×B_total/(e n_e)`, `E_ambipolar = -∇p_e/(e n_e)` (blockwise curvilinear gradient), `E_generalized` = sum |

## Data-only vs solver-model Hall/ambipolar fields

`E_Hall`, `E_ambipolar`, `E_generalized` are computed **from the data alone**
(`n_e = n_H + n_Na`, no taper). The solver (MPCNS_Mercury, branch `Mercury`,
`Z4_Mercury`) advances slightly different quantities, so the `*_solver` twins
reproduce its induction/momentum sources:

- `n_e,eff = sqrt(n_e² + ne_hall_floor²)`, with `n_e` and the floor in units of
  the reference number density (`ne_hall_floor = 0.01`, `n_ref = 4×10⁷ m⁻³`);
  used by Hall, ambipolar and the species weights `n_s/n_e,eff`.
- Hall induction EMF only is multiplied by the radial taper
  `½[1+tanh(2(r−mid)/(r_max−r_min))]`, `mid=(r_min+r_max)/2`, `r_min=1.3`,
  `r_max=1.7` (`CASE/setup/3_MHD_Control.txt`), `r` = cell-centre radius in R_M.
- The ambipolar EMF has no taper. The **momentum** Hall source
  `(n_s/n_e,eff) J×B` and `−(n_s/n_e,eff)∇p_e` has **no taper** either, so
  `E_Hall_solver` is *not* the field behind the momentum Hall force.

| Switch | Result |
| --- | --- |
| `hall_model: data` (default) | requested `E_*` fields as given |
| `hall_model: solver` | `E_Hall`, `E_ambipolar`, `E_generalized` replaced by `E_Hall_solver`, `E_ambipolar_solver`, `E_generalized_solver` |
| `hall_model: both` | both versions side by side |

Solver-model fields (also requestable by name; need the case parameters in
YAML `solver_model` — they are never guessed):
`electron_number_density_reg`, `hall_taper`, `E_Hall_solver`,
`E_ambipolar_solver`, `E_generalized_solver`, and momentum sources
`{H,Na,ion}_Hall_force`, `{H,Na,ion}_ambipolar_force` (fN/m³).

```yaml
hall_model: both
solver_model: {hall_taper_r_min: 1.3, hall_taper_r_max: 1.7, ne_hall_floor: 0.01}
```

CLI: `--hall-model both --hall-taper-r-min 1.3 --hall-taper-r-max 1.7 --ne-hall-floor 0.01`.
The parameters are stored under `normalization.solver_model` in the file. The
solver's edge EMFs also contain a numerical Rusanov-type Hall diffusion term;
it is not part of the physical `E_Hall_solver` here.

## Dimensional and nondimensional results

`nondimensional: none | both | only` (YAML top level, or `--nondimensional`)
adds a `<field>_nd` twin to every field that has a physical dimension
(`beta` is already dimensionless): `X_nd = SI value / solver reference`, i.e.
the numbers the solver itself evolves. `both` keeps dimensional and
nondimensional fields side by side; `only` writes just the twins. Each
descriptor links the pair (`nondimensional` / `dimensional` entries with the
scale and reference name).

The file's `normalization` block stores everything needed to convert or to
compute further quantities downstream, so later steps never need the solver:

- all solver references (`density_ref`, `velocity_ref`, `pressure_ref`,
  `magnetic_field_ref`, `current_density_ref`, `electric_field_ref`,
  `temperature_ref`, `time_ref`, `length_ref`) in SI;
- `coordinate_scale_m` — coordinates are in `length_ref` (R_M) units;
- `physical_constants` — `gamma`, `mu0`, `particle_mass_H/Na`,
  `elementary_charge`, `boltzmann_constant`;
- `nondimensional_scales.<category>` — output unit, reference name and
  `to_nondimensional` factor (`X_nd = X * factor`);
- `convention` — a short text summary. Number density is nondimensionalized as
  `n m_H / density_ref`.

`pypost process` can use them directly: operands such as `"@pressure_ref"` or
`"@physical_constants.mu0"` resolve against the file (see
`examples/workflows/data3d/data3d_process.yml`), and slice/line outputs carry
the same `normalization` block.

On the example case (84 ranks) all 28 dimensional fields plus their twins (55
fields) convert in ~32 s; every value agrees with the original `Postprocess`
script to ≤2e-15 relative and `X_nd` matches `X` / reference to ≤5e-16.

The converter stops on missing owner maps, topology mismatches, duplicate owner
IDs, alias inconsistencies, and degenerate polar hexahedra. It never merges
nodes by coordinate or silently averages interface values. See the
[memory analysis](../../../docs/data-format/mercury-p1-memory-analysis.md) for
the validated streaming design and measured artifact.
