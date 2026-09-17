# hqai_ml.registry

The local registry has three deterministic record types:

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
an approval or promotion decision. Training creates immutable evaluated candidates; only an operator's explicit
`--promote` request atomically publishes the selected multi-model set in `artifacts/models/manifest.json`.
PostgreSQL stores the verified SHA256 and nullable run/data/config/code/evaluation lineage. Historical artifacts
remain distinguishable because only their checksum is populated and their unavailable provenance stays `NULL`.

The filesystem manifest is the candidate-selection authority and is replaced in one atomic write only after every
selected artifact is verified. `model_registry` is the transactional serving snapshot written by prediction or
registry publication. These stores do not form a distributed transaction: if the database write fails, the prior
database transaction rolls back while the filesystem selection remains available for an idempotent retry.

A run's scientific identity includes its model/candidate set, data/config/source identities, temporal protocols,
scientific hyperparameters, seeds and relevant implementation versions. Resource profile, detected CPU count,
model threads, trial/process concurrency and platform/architecture are recorded per execution and checkpoint but do
not invalidate compatible science. The global resource contract prevents the product of nested concurrency from
exceeding the profile CPU budget.

Only the coordinator process writes run and checkpoint metadata; workers return computed results to it. Run
mutation requires an atomically acquired `.run.lock`, and every mutation rereads the on-disk lock identity as a
fencing check. A second writer is rejected with the owner diagnostic; normal completion, exceptions and Ctrl+C
release the lock. A hard-kill lock is handled only by
`--recover-stale-lock <run-id> --confirm-lock-id <exact-id>`. A same-host live owner is never recoverable, PID reuse
is detected with process-start identity, and an unknown/remote owner additionally requires
`--force-remote-lock-recovery`. Successful recovery writes a durable audit record; PID visibility never causes
automatic deletion.
