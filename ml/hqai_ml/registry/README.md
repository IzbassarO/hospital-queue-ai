# hqai_ml.registry

The local registry has two deterministic records:

- `artifacts/runs/<run_id>/run.json`: scientific identity, lifecycle and high-level evaluation summaries;
- `artifacts/runs/<run_id>/checkpoints/<deterministic-key>.json`: independently atomic candidate/trial/fold/origin
  checkpoints with their unit identity, execution reference, state, metrics and artifact checksum;
- `artifacts/models/<model>/<version>/`: model files and metadata plus `artifact-manifest.json`, a sorted SHA256
  manifest for every file in the version.

Critical JSON pointers/manifests and model-directory publication use temporary writes followed by an atomic rename.
`store.load()` verifies the full artifact before deserializing a model. `ml/pipelines/predict.py` applies the same
verification and evaluation/lineage eligibility gate before mirroring current versions into PostgreSQL
`model_registry`.

Legacy artifacts are adopted by writing a checksum sidecar on first load, then are reported as
`legacy_unattributed`. Newly trained artifacts cannot pass registration unless they identify their successful run,
completed evaluation, canonical family/target mapping, and code/config/data lineage. Evaluation completion is not
an approval or promotion decision.

A run's scientific identity includes its model/candidate set, data/config/source identities, temporal protocols,
scientific hyperparameters, seeds and relevant implementation versions. Resource profile, detected CPU count,
model threads, trial/process concurrency and platform/architecture are recorded per execution and checkpoint but do
not invalidate compatible science. The global resource contract prevents the product of nested concurrency from
exceeding the profile CPU budget.

Run mutation requires an atomically acquired `.run.lock`. A second writer is rejected with the owner diagnostic;
normal completion, exceptions and Ctrl+C release the lock. A hard-kill lock is handled only by the explicit
`--recover-stale-lock <run-id>` command—PID visibility never causes automatic deletion.
