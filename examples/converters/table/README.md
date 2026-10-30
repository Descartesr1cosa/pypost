# Table → Data1D example converter

This is a small format-adapter example, not a `sciplot` core module. It reads a named CSV/whitespace/OpenFOAM-style table through `Data1D`, writes a standard binary NPZ, reloads it, and validates the exact numeric round trip.

```bash
python -m examples.converters.table \
  --config examples/converters/table/configs/minimal.example.yml
```

All relative paths in the table YAML are resolved relative to that YAML file. `full.example.yml` additionally writes an ASCII standard-data copy and a CSV export. A direct diagnostic form is also available:

```bash
python -m examples.converters.table ../sample_external_table.txt output/history.npz --x time
```
