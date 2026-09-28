# Deploying on a shared server (rootless Docker)

A repeatable procedure for running the stack on a shared Ubuntu 22.04 server where you are an ordinary user:
rootless Docker, no `sudo`, `umask 0007`, and one public HTTPS address that an external reverse proxy forwards to
`127.0.0.1:<FRONTEND_PORT>` on this host. Everything below runs as your own user.

[operations.md](operations.md) is the general operations guide (production overlay, nightly refresh, backups, closed
network); this page is the shared-server variant of its first-install and update sections. The commands are wrapped
in [`tools/deploy.sh`](../tools/deploy.sh):

| Command | What it does | Changes anything |
|---|---|---|
| `make deploy-check` (`tools/deploy.sh check`) | prerequisites, `.env` settings, free ports, file permissions | no |
| `tools/deploy.sh update` | check → `git pull --ff-only` → `chmod -R o+rX db seed` → `make up` → health | yes |
| `tools/deploy.sh health` | health checks of the running stack | no |
| `tools/deploy.sh rollback [COMMIT]` | back to the commit before the last update (§10) | yes |

The script stops at the first failing step and prints what to do next. It reads single values from `.env` (ports,
`UI_BIND`, whether a secret is set) without sourcing the file and never prints the file or any secret.

This deployment uses the base `docker-compose.yml` (the same one as `make up`), not the production overlay: the
overlay drops the host ports of PostgreSQL and the API, and the SSH-tunnel load in §6 needs the PostgreSQL port on
the loopback interface.

## 1. Prerequisites: rootless Docker and linger

Once per user. The administrator must already have installed `docker-ce-rootless-extras` and `uidmap` and given
your user a range in `/etc/subuid` and `/etc/subgid`; everything else is yours.

```bash
dockerd-rootless-setuptool.sh install          # installs ~/.config/systemd/user/docker.service
systemctl --user enable --now docker           # daemon starts together with your systemd user manager
loginctl enable-linger "$USER"                 # keep the user manager, and so Docker, running after you log out
echo 'export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock' >> ~/.bashrc
```

If `loginctl enable-linger` is refused by policy, ask an administrator to run `loginctl enable-linger <you>`.
Without linger the whole stack stops when your last SSH session closes, and it does not come back after a reboot.

Also needed: `git`, `make`, `curl`, Docker Compose v2.24 or newer (`docker compose version`). Check it all with:

```bash
make deploy-check
```

Rootless Docker cannot publish ports below 1024 (`net.ipv4.ip_unprivileged_port_start`), so every port in `.env`
must be 1024 or higher. That is fine here: the public HTTPS port belongs to the reverse proxy, not to this stack.

## 2. `.env` settings

Create `.env` once (`make env` generates `POSTGRES_PASSWORD` and `DEMO_API_KEY`), then set the host side of the
three ports and the UI binding. Other users on the server run their own stacks, so the defaults 3000/8000/5432 are
probably taken — choose free ports (list what is taken with `ss -Hltn | awk '{print $4}' | sort -u`):

```bash
make env
chmod 600 .env                 # with umask 0007 it is created 0660: readable by your group
$EDITOR .env
```

```ini
UI_BIND=127.0.0.1              # the UI listens on loopback only; the reverse proxy is the only way in
FRONTEND_PORT=<free port>      # the port the reverse proxy forwards to: 127.0.0.1:<FRONTEND_PORT>
API_PORT=<free port>           # always bound to 127.0.0.1 by docker-compose.yml
POSTGRES_PORT=<free port>      # always bound to 127.0.0.1; also the end of the SSH tunnel in §6
```

`make deploy-check` fails when `UI_BIND` is not `127.0.0.1`, a port is missing, below 1024, used twice, or already
taken by another process; a port held by this stack's own containers (`hqai-*`) counts as fine.

Loopback is not private on a shared host: any local user can open `127.0.0.1:<FRONTEND_PORT>`, and the UI's nginx
adds `DEMO_API_KEY` to every request (security.md §3). On a server shared with people who must not see the data,
leave `DEMO_API_KEY` empty and hand out personal keys (`make create-key`), or put the UI behind the proxy's own
authentication. The API and PostgreSQL ports are protected by the API keys and the database password.

## 3. The umask problem

With `umask 0007` everything `git clone` and `git pull` create is `0660`/`0770`: no permission for "other". The
compose file bind-mounts two directories from the checkout into containers:

- `./db/init.sql` → the `postgres` container, read by the `postgres` user (uid 999 in the container);
- `./seed` → the `seed` container, read by the `app` user (uid 10001).

Under rootless Docker those container users map to subordinate uids on the host, which are neither you nor your
group, so they are "other". Without the "other" read bit, PostgreSQL skips or fails `init.sql` on a fresh volume
and the seed loader cannot open `manifest.json`. Hence, after every clone and every pull:

```bash
chmod -R o+rX db seed
```

`o+rX` adds read to files and search to directories only, nothing else in the checkout changes. `tools/deploy.sh
update` runs it every time; `make deploy-check` reports when it is missing. `backups/` (from `make backup`) is
created 0770 by the same umask, which is what you want for a full database dump.

## 4. First install

```bash
git clone <repo> hospital-queue-ai && cd hospital-queue-ai
make env && chmod 600 .env && $EDITOR .env     # §2
make deploy-check                              # fix every FAIL before going on
tools/deploy.sh update                         # chmod, build, start, migrate, health
```

`update` on a fresh clone has nothing to pull and simply converges the stack. The database is empty at this point:
load the demo seed either on the server, if it has several GB of memory free,

```bash
docker compose --profile demo run --rm seed
```

or from a workstation through an SSH tunnel (§6). Then point the reverse proxy at `127.0.0.1:<FRONTEND_PORT>`.

## 5. Update procedure

```bash
cd hospital-queue-ai
tools/deploy.sh update
```

What it does, in order, stopping at the first failure:

1. `check` — the same checks as `make deploy-check`; any FAIL stops the update.
2. Refuses to go on with local changes to tracked files, a detached HEAD (after a rollback, §10) or a diverged branch.
3. `git fetch`; if there is something new it prints the incoming commits and records the current commit and the
   database's Alembic revision in `.git/hqai-deploy-state` (inside `.git`, never committed) for the rollback.
4. If the incoming commits change `backend/alembic/versions/`, runs `make backup` first
   (`backups/hqai_<timestamp>.dump`).
5. `git pull --ff-only`.
6. `chmod -R o+rX db seed` (§3).
7. `make up` — `docker compose up -d --build --wait`. The backend applies Alembic migrations on start
   (`alembic upgrade head` in its command), so there is no separate migration step. The `pgdata` volume is kept:
   `make up` never removes volumes.
8. Health checks (§7).

Running it again when nothing changed is safe: no pull, the same chmod, and `make up` finds the images cached and
the containers up to date. By hand, the same procedure is:

```bash
git pull --ff-only
chmod -R o+rX db seed
make up
tools/deploy.sh health
```

Never use `docker compose down -v` as part of an update: `-v` deletes the `pgdata` volume, i.e. the database.

## 6. Loading publications from a workstation (SSH tunnel)

Loading the seed or a publish bundle reads a whole bundle into the loader's memory, and the `seed` service has no
memory limit on purpose (docker-compose.prod.yml). On a server that is short of memory the kernel OOM killer then
picks the largest process — often a PostgreSQL backend — and PostgreSQL goes into recovery (§8). Run the loader on
your workstation instead; the server only receives rows over the tunnel.

On the workstation, in a checkout of **the same commit** as the server (the loader must match the migrated schema;
`git rev-parse HEAD` on the server):

```bash
# 1. tunnel: workstation 127.0.0.1:15432 -> server 127.0.0.1:<POSTGRES_PORT>; leave it running
ssh -N -L 127.0.0.1:15432:127.0.0.1:<POSTGRES_PORT> <you>@<server>

# 2. in a second terminal: the backend's Python dependencies (once)
python3 -m venv .venv && .venv/bin/pip install ./backend

# 3. connection settings for this shell only; the password goes into a variable, not onto the screen or a file
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=15432 POSTGRES_USER=hqai POSTGRES_DB=hqai
POSTGRES_PASSWORD=$(ssh <you>@<server> "sed -n 's/^POSTGRES_PASSWORD=//p' hospital-queue-ai/.env")
export POSTGRES_PASSWORD

# 4. load (run from backend/)
cd backend
../.venv/bin/python -m app.cli load-seed --dir ../seed                  # empty database: tables + publications
../.venv/bin/python -m app.cli load-seed --dir ../seed --replace        # reload the seed into a non-empty one
../.venv/bin/python -m app.cli publish-operational-intelligence --bundle /path/to/operational_intelligence.json
../.venv/bin/python -m app.cli publish-review-evidence --bundle /path/to/review_evidence.json
../.venv/bin/python -m app.cli publish-waiting-list --bundle /path/to/waiting_list.json
../.venv/bin/python -m app.cli publish-assurance --bundle /path/to/model_assurance.json
```

Use `python -m app.cli` directly rather than the `make … -publish` targets: the Makefile includes the workstation's
own `.env`, whose `POSTGRES_PORT` would override the exported tunnel port. Environment variables take precedence
over `.env` in the backend settings, so the direct call always goes through the tunnel. Close the tunnel and the
shell afterwards (`unset POSTGRES_PASSWORD`). Publication is transactional: an interrupted load leaves the previous
publication active. Then, on the server, `tools/deploy.sh health` and `make smoke`.

## 7. Health checks

```bash
tools/deploy.sh health       # what update runs at the end
make smoke                   # additionally: the three publications and the active publication identity
docker compose ps            # container state and healthcheck status
```

| Check | Address | Meaning |
|---|---|---|
| PostgreSQL | `pg_isready` in the container | accepts connections (not starting up or in recovery) |
| API liveness | `http://127.0.0.1:<API_PORT>/health` | the process runs; does not touch the database |
| API readiness | `http://127.0.0.1:<API_PORT>/api/v1/health` | database reachable, serving marts fresh |
| UI | `http://127.0.0.1:<FRONTEND_PORT>/healthz` | nginx serves; this is also what the reverse proxy reaches |

A green `health` with a 502 from the public address means the reverse proxy points at the wrong port or host:
it must forward to `127.0.0.1:<FRONTEND_PORT>` of this server.

## 8. Logs

```bash
docker compose logs --tail=200 backend                 # last lines
docker compose logs -f --since 30m backend frontend    # follow
docker compose logs backend | grep '"level": "ERROR"'  # backend writes one JSON object per line
docker compose logs --tail=100 postgres
journalctl --user -u docker --since today              # the rootless daemon itself (start failures, port binding)
```

The backend lines carry `request_id`; the same id is in the `X-Request-ID` response header, so one failing request
can be followed from the browser to the log. The base compose file does not rotate container logs (the production
overlay does); on a long-running shared server check `docker system df` from time to time.

## 9. PostgreSQL in recovery mode

Symptoms: `/api/v1/health` fails or the API answers 503, and the postgres log shows

```
FATAL:  the database system is in recovery mode
LOG:    server process (PID …) was terminated by signal 9: Killed
LOG:    terminating any other active server processes
```

Signal 9 almost always means the kernel OOM killer (a loader or another user's job took the memory), or the
container was killed mid-write. PostgreSQL is replaying its write-ahead log; the data is intact. What to do:

1. **Do not** run `docker compose down -v`, delete the `pgdata` volume, or restart the container in a loop —
   every restart starts the replay over.
2. Stop whatever used the memory: an on-server `seed` or publish run (`docker ps`, then `docker stop <name>`).
3. Watch the replay finish: `docker compose logs -f postgres` until
   `database system is ready to accept connections`. On this database size it takes seconds to a few minutes.
4. `tools/deploy.sh health`. The backend's pool replaces dropped connections by itself; if readiness still fails,
   `docker compose restart backend`.
5. Re-run the load that was interrupted, this time through the tunnel (§6).

If recovery does not finish — the log shows `No space left on device`, or PostgreSQL exits again right after
replay — free disk space first (`df -h`, `docker system df`, old `backups/`) and restart once with
`docker compose up -d --wait postgres`. Only when the data directory is damaged beyond that, restore the last dump
into a fresh volume — this deletes the current database:

```bash
make backup || true                                         # try to keep whatever can still be read
docker compose down
docker volume rm "$(basename "$PWD")_pgdata"                # the compose project is the directory name
chmod -R o+rX db seed && make up                            # fresh volume, init.sql, migrations
make restore FILE=backups/hqai_<timestamp>.dump
docker compose restart backend && tools/deploy.sh health
```

## 10. Rollback to the previous commit

```bash
tools/deploy.sh rollback             # the commit recorded by the last update
tools/deploy.sh rollback <commit>    # or an explicit one
```

1. Refuses with local changes to tracked files.
2. If `backend/alembic/versions/` differs between the current and the target commit, it downgrades the database
   first, **with the currently running backend** — only the newer code knows how to undo its own migrations:
   `docker compose exec -T backend alembic downgrade <revision recorded before the update>`. When no revision was
   recorded (an explicit commit, or the stack was down during the update) it stops and asks you to restore the
   backup that `update` took (`make restore FILE=backups/hqai_<timestamp>.dump`) or to downgrade by hand.
3. `git checkout --detach <commit>`, `chmod -R o+rX db seed`, `make up` (rebuilds the older images), health.

After a rollback HEAD is detached, so `update` refuses to run until you decide how to proceed: `git checkout main`
followed by `tools/deploy.sh update` goes forward again, to the same version you just left, once it is fixed
upstream. The same by hand:

```bash
git log --oneline -5                                          # find the previous commit
docker compose exec -T backend alembic downgrade <revision>   # only if migrations differ
git checkout --detach <commit>
chmod -R o+rX db seed
make up
tools/deploy.sh health
```

Published data is rolled back separately: every publication stays in the database, so republishing the previous
bundle (§6) makes it active again (operations.md §8).

## 11. What is and is not verified

- `tools/deploy.sh` passes `shellcheck`. `bash tools/deploy_test.sh` runs shellcheck and then the script against a
  throwaway checkout with a local bare "origin" and stubbed `docker`/`make`/`curl`/`loginctl`/`systemctl`:
  `check` catches the umask problem, `UI_BIND`, missing, low, duplicate and taken ports and changes nothing on disk;
  `update` pulls, backs up before a new migration, makes pulled files world-readable under `umask 0007` and is a
  no-op the second time; `rollback` downgrades to the recorded revision before the checkout; `update` refuses on
  the detached HEAD a rollback leaves; and no command prints a value from `.env`.
- `update`, `rollback` and `health` against a real rootless daemon on the target server have not been rehearsed from
  this repository; run `make deploy-check` and a first `tools/deploy.sh update` there and note anything that differs.
