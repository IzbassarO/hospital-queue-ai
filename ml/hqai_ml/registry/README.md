# hqai_ml.registry

The local registry has two deterministic records:

- `artifacts/runs/<run_id>/run.json`: experiment identity, lifecycle, evaluation summaries and resumable
  model-level checkpoints;
- `artifacts/models/<model>/<version>/`: model files and metadata plus `artifact-manifest.json`, a sorted SHA256
  manifest for every file in the version.

Critical JSON pointers/manifests and model-directory publication use temporary writes followed by an atomic rename.
`store.load()` verifies the full artifact before deserializing a model. `ml/pipelines/predict.py` applies the same
verification and evaluation/lineage eligibility gate before mirroring current versions into PostgreSQL
`model_registry`.

Legacy artifacts are adopted by writing a checksum sidecar on first load, then are reported as
`legacy_unattributed`. Newly trained artifacts cannot pass registration unless they identify their successful run,
evaluation, family/target, and code/config/data lineage.
