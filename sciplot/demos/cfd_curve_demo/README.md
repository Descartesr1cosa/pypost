# CFD curve workflow

The inputs are explicitly synthetic OpenFOAM-style sampled tables. Convert
each raw table with `pypost convert`, then use `compare.yml` with `pypost curve
compare`. `pypost demo run cfd-curve-workflow` performs those same core steps
into `pypost-demo-output/`, keeping raw conversion and plotting artifacts
separate.
