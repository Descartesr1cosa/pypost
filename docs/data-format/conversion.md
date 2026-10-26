# Writing a pypost converter

Start with the [data format specification](README.md). A converter is an
ordinary Python script owned by the external-data project; it does not need to
register a plugin in pypost.

The runnable example is
[`examples/converters/convert_table_to_pypost.py`](../../examples/converters/convert_table_to_pypost.py).
It reads a whitespace/CSV table, creates `Data1D`, writes binary NPZ and an
optional ASCII CSV, reloads the binary result, checks all numeric arrays, and
optionally exports a scalar standardized table.

```bash
python examples/converters/convert_table_to_pypost.py \
  examples/converters/sample_external_table.txt output/force_history.npz \
  --x time --ascii output/force_history.csv --export output/reexport.csv
pypost validate output/force_history.npz --deep
pypost inspect output/force_history.npz
```

Use binary NPZ when exact dtype, sample order, vectors, or tensors matter. Use
CSV only for scalar 1-D interchange. Verify standard-data numerical round trips
with `numpy.testing.assert_array_equal` (or an explicitly selected tolerance
when the external parser itself converts precision).

An external solver format usually cannot be reconstructed byte-for-byte:
comments, ordering, sparse options, proprietary metadata, and solver-specific
boundary semantics may have no standard-data equivalent. You may export a
lossless subset such as a standardized scalar table, but do not claim complete
reverse conversion unless the mapping is documented and tested.

Once conversion is validated, plot the standard CSV directly with existing
YAML:

```bash
pypost plot plot.yml
# `plot.yml` datasets[].path can be output/force_history.csv
```

For a binary-only 1-D dataset, a small project-specific conversion/export step
can write a scalar CSV view for the existing 1-D YAML plotter. This explicit
step prevents silent loss of vector components.
