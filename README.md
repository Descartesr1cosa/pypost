# pypost / sciplot

`sciplot` is the Python library and `pypost` is its command-line interface for reproducible scientific post-processing. Convert solver-specific data once, then use self-contained standard data for inspection, processing, and plots.

## Install

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
python -m pip install -e '.[dev]'
```

## Main workflows

```bash
# Standard 1-D conversion and plotting
pypost convert --config convert.yml
pypost plot plot.yml

# Inspect, validate, and process a Data3D v1 volume
pypost inspect mercury.vtu
pypost validate mercury.vtu --deep
pypost process process.yml

# Mercury MPCNS v3 source data -> self-contained Data3D v1
python -m examples.converters.mercury --config mercury.yml

# Generic named table -> standard Data1D
python -m examples.converters.table --config table.yml
```

The Mercury adapter is intentionally outside `sciplot`: it handles only the solver's binary layout and reconstruction. All later work depends only on the Data3D v1 file; see [the format specification](docs/data-format/data3d-v1.md) and [Data3D processing tutorial](docs/tutorials/data3d-processing.md).

## Repository map

- `sciplot/` — supported library, CLI, I/O, processing, plotting, and wheel-bundled demos.
- `examples/converters/` — solver/input-format adapters, each with its own YAML examples and `python -m` entry point.
- `examples/workflows/` — copyable standard curve, Data3D, and Q YAML examples. They never parse Mercury binary data.
- `examples/python_api/` — small API teaching scripts; write outputs only to the working directory selected by the user.
- `tests/` — synthetic fixtures and CI tests only; no personal case data.
- `docs/` — protocol, tutorial, development, and migration documentation.

Bundled demos are a separate wheel resource and work after installation:

```bash
pypost demo list
pypost demo run curve-comparison
pypost demo init curve-comparison --dest my-plot
```

## Mercury YAML

Copy one template, edit only the data root and chosen paths, and run it from the repository root (or any directory that can import this checkout):

```bash
cp examples/converters/mercury/configs/b_only.example.yml mercury.yml
python -m examples.converters.mercury --config mercury.yml
```

`paths.data_root` is resolved relative to the YAML file. Relative static input, restart input, output, and temporary paths are resolved under that data root. The converter rejects directory outputs, unsupported fields, missing rank input, non-positive memory budgets, and accidental overwrites before it streams any rank. Details are in the [Mercury converter README](examples/converters/mercury/README.md).

Large raw solver data and generated results belong outside this repository. The project never needs `pypost_examples/` to run its normal tests.

## Documentation

- [Data formats](docs/data-format/README.md)
- [1-D tutorials](docs/tutorials/1d/README.md)
- [Data3D processing](docs/tutorials/data3d-processing.md)
- [Repository layout and migration](docs/development/repository-layout.md)
