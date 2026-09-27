# Offline ML pipelines (ingest, forecast evidence, bundles) as a container, so the nightly refresh does not need a
# host Python with a working LightGBM/XGBoost toolchain. Build context: the repository root.
#   docker compose --profile pipelines build pipelines
#   make pipe CMD='ml/pipelines/flow_quantile.py --plan'
# The image carries the interpreter and the pinned dependencies; the checkout (code, data/, artifacts/,
# ml/configs) is mounted at /work at run time, so a run record names the commit it came from.
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
# tag python:3.12-slim, digest resolved 2026-09-27 with `docker buildx imagetools inspect python:3.12-slim`

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/work/ml

WORKDIR /work

# libgomp1: the OpenMP runtime LightGBM links against (the wheel does not ship it).
# git: every run record stores the commit and worktree state it was produced from (hqai_ml/registry/experiment.py
# calls `git rev-parse HEAD` and `git status --short` in /work), so provenance needs the client and the checkout.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

# the same pinned set the accepted runs used (requirements.txt), cached until that file changes
COPY requirements.txt ./
RUN pip install -r requirements.txt

# a copy of the pipelines so the image is self-describing; at run time /work is the mounted checkout, which is what
# the run records refer to (docker-compose.yml service `pipelines`)
COPY ml ./ml

# The pipelines write into the mounted checkout (data/, artifacts/, reports/), so the container user must own
# those directories on the host. uid 10001 matches the backend image; on Linux pass `--user $(id -u):$(id -g)`
# (make pipe does) when the checkout belongs to someone else.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin pipelines
USER pipelines

# no default pipeline: every run names its own (make pipe CMD='…'). The default command only proves the
# scientific stack imports, which is what a fresh install checks first.
ENTRYPOINT []
CMD ["python", "-c", "import lightgbm, xgboost, duckdb; print('ml image ready')"]
