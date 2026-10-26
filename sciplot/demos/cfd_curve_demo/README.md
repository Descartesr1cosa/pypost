# CFD curve workflow

The inputs are explicitly synthetic OpenFOAM-style sampled tables. This is a
fully independent workflow: no `demo run` path aliases are required.

```bash
pypost demo init cfd-curve-workflow --dest cfd-plot
cd cfd-plot
pypost convert --config convert_case_a.yml
pypost convert --config convert_case_b.yml
pypost curve compare --config compare.yml
```

The first two commands create `standardized/case_a.csv` and
`standardized/case_b.csv` plus JSON metadata sidecars. The final command reads
only those standard files and creates `cfd_coefficients.pdf` and `.svg`.
Change `compare.yml` and rerun only the final command to restyle the plot;
there is no need to convert raw files again. `pypost demo run
cfd-curve-workflow` stages this same project under `pypost-demo-output/` and
executes the same YAML steps for a quick preview.
