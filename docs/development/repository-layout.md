# Repository layout and Phase 6 cleanup

## Maintained locations

| Location | Responsibility |
| --- | --- |
| `sciplot/` | portable library, CLI, and wheel-bundled self-contained demos |
| `examples/converters/<name>/` | one upstream format adapter, its YAML templates and README |
| `examples/workflows/` | standard-data YAML examples only |
| `examples/python_api/` | short public API demonstrations |
| `tests/` | synthetic tests and tiny fixtures, never personal solver cases |
| `docs/` | user and development documentation |

## Phase 6 audit and decisions

| Classification | Files / directories | Decision |
| --- | --- | --- |
| Keep | `sciplot/`, `tests/`, `docs/`, `.github/` | Core code, CI, protocol, and synthetic tests remain maintained. |
| Move | root `configs/` | Moved to `examples/workflows/{curve,data3d,q}/` by workflow type. |
| Move | root `examples/example_*.py`, `scripts/*.py` | Moved to `examples/python_api/`; these are teaching helpers, not library entry points. |
| Move | table converter | Moved to `examples/converters/table/` with module/YAML entry points. |
| Move | Mercury converter main module | Renamed to `examples/converters/mercury/converter.py`; code remains outside `sciplot`. |
| Delete | `examples/assets/curve_demo/` | Its CSV inputs duplicated `sciplot/demos/curve_demo/`; PDF/SVG were generated expected output. |
| Delete | `examples/assets/q_demo/` | Its 4.5 MB VTP, camera, and YAML duplicated wheel demos; old Q scripts were superseded by `sciplot.q`. |
| Preserve externally | `pypost_examples/exampleMercury_data/` | Never tracked, moved, read by ordinary tests, or deleted. |
| Preserve locally | `.env/`, `build/`, `output/`, `*.egg-info/`, caches | Untracked/ignored generated state; not deleted by this cleanup. |

## Command migration

| Old checkout path | Maintained equivalent |
| --- | --- |
| `python examples/converters/mercury/mercury_to_data3d.py …` | `python -m examples.converters.mercury --config mercury.yml` |
| `python examples/converters/convert_table_to_pypost.py …` | `python -m examples.converters.table …` or `--config table.yml` |
| `python scripts/convert_data.py config.yml` | `pypost convert --config config.yml` |
| `python scripts/calculate_and_plot.py config.yml` | `examples/python_api/calculate_and_plot.py` for its combined teaching workflow; prefer `pypost plot` for normal Data1D plot YAML. |
| `configs/examples/*.yml` | `examples/workflows/{curve,data3d,q}/*.yml` |

The migration changes paths and entry points only. It does not change Mercury reconstruction, Data3D v1, Q calculation, or generic processing algorithms.
