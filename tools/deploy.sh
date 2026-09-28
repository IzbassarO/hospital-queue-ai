#!/usr/bin/env bash
# Update procedure for a shared Ubuntu server with rootless Docker (docs/deploy-shared-server.md).
#
#   tools/deploy.sh check              prerequisites, .env settings, ports and permissions; changes nothing
#   tools/deploy.sh update             check -> git pull --ff-only -> chmod -R o+rX db seed -> make up -> health
#   tools/deploy.sh rollback [COMMIT]  back to the commit before the last update (or COMMIT), same steps after it
#   tools/deploy.sh health             health checks of the running stack only
#
# Every step is idempotent: running `update` twice leaves the same state as running it once. The script stops at the
# first failed step and says what to do. It reads single settings from .env (ports, UI_BIND, whether a secret is set)
# and never prints the file or a secret value.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE="$ROOT/.env"
MIN_COMPOSE="2.24.0"
# Written inside .git, so it is never committed: the commit and Alembic revision before the last update.
STATE_FILE=""

FAILS=0
WARNS=0

if [ -t 1 ]; then
  C_OK=$'\033[32m' C_WARN=$'\033[33m' C_FAIL=$'\033[31m' C_STEP=$'\033[1m' C_OFF=$'\033[0m'
else
  C_OK="" C_WARN="" C_FAIL="" C_STEP="" C_OFF=""
fi

ok() { printf '  %sok%s    %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() {
  printf '  %swarn%s  %s\n' "$C_WARN" "$C_OFF" "$*"
  WARNS=$((WARNS + 1))
}
fail() {
  printf '  %sFAIL%s  %s\n' "$C_FAIL" "$C_OFF" "$*"
  FAILS=$((FAILS + 1))
}
hint() { printf '        -> %s\n' "$*"; }
step() { printf '\n%s== %s%s\n' "$C_STEP" "$*" "$C_OFF"; }
die() {
  printf '\n%sSTOPPED:%s %s\n' "$C_FAIL" "$C_OFF" "$*" >&2
  exit 1
}

usage() {
  sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# The value of one KEY from .env: last assignment wins, surrounding quotes removed. The file is never sourced, so
# nothing in it is executed, and callers print the value only for non-secret keys.
env_get() {
  local key=$1 line value=""
  [ -r "$ENV_FILE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case $line in
      "$key="*) value=${line#"$key="} ;;
    esac
  done < "$ENV_FILE"
  value=${value%$'\r'}
  case $value in
    \"*\") value=${value#\"} value=${value%\"} ;;
    \'*\') value=${value#\'} value=${value%\'} ;;
  esac
  printf '%s' "$value"
}

have() { command -v "$1" > /dev/null 2>&1; }

version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

compose() { (cd "$ROOT" && docker compose "$@"); }

# Names of this stack's running containers that publish host port $1 (empty when none).
port_owner() {
  docker ps --filter "publish=$1" --format '{{.Names}}' 2> /dev/null | grep '^hqai-' || true
}

port_listening() {
  local port=$1
  if have ss; then
    [ -n "$(ss -Hltn "sport = :$port" 2> /dev/null)" ]
  else
    (exec 3<> "/dev/tcp/127.0.0.1/$port") 2> /dev/null
  fi
}

# ---------------------------------------------------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------------------------------------------------

check_tools() {
  step "tools"
  local t
  for t in git make curl; do
    if have "$t"; then ok "$t"; else fail "$t is not installed"; fi
  done
  if ! have docker; then
    fail "docker CLI not found"
    hint "rootless Docker: dockerd-rootless-setuptool.sh install (docs/deploy-shared-server.md §1)"
    return
  fi
  local cv
  cv=$(docker compose version --short 2> /dev/null || true)
  cv=${cv#v}
  if [ -z "$cv" ]; then
    fail "docker compose v2 plugin not found"
  elif version_ge "$cv" "$MIN_COMPOSE"; then
    ok "docker compose $cv"
  else
    fail "docker compose $cv is older than $MIN_COMPOSE (needed for !reset and profiles)"
  fi
}

check_docker() {
  step "rootless docker"
  have docker || return 0
  if [ "$(id -u)" = "0" ]; then
    warn "running as root: this procedure is written for an ordinary user with rootless Docker"
  fi
  local info
  if ! info=$(docker info --format '{{json .SecurityOptions}}' 2> /dev/null); then
    fail "the Docker daemon does not answer (DOCKER_HOST=${DOCKER_HOST:-<unset>})"
    hint "systemctl --user start docker; export DOCKER_HOST=unix://\$XDG_RUNTIME_DIR/docker.sock"
    return
  fi
  if printf '%s' "$info" | grep -q rootless; then
    ok "daemon is rootless (DOCKER_HOST=${DOCKER_HOST:-docker context})"
  else
    warn "daemon is not rootless: on a shared server use your own rootless daemon, not the system one"
  fi
  if have systemctl; then
    if [ "$(systemctl --user is-enabled docker 2> /dev/null || true)" = "enabled" ]; then
      ok "systemd user unit docker.service enabled (starts with your user manager)"
    else
      warn "systemctl --user docker.service is not enabled: the stack will not come back after a reboot"
      hint "systemctl --user enable docker"
    fi
  fi
  if have loginctl; then
    local linger
    linger=$(loginctl show-user "$(id -un)" --property=Linger --value 2> /dev/null || true)
    if [ "$linger" = "yes" ]; then
      ok "linger enabled: the user manager and rootless Docker keep running after logout"
    else
      fail "linger is not enabled: rootless Docker stops when your last session ends"
      hint "loginctl enable-linger $(id -un)   (or ask an administrator to run it for you)"
    fi
  else
    warn "loginctl not found: cannot verify linger"
  fi
  local root
  root=$(docker info --format '{{.DockerRootDir}}' 2> /dev/null || true)
  if [ -n "$root" ] && [ -d "$root" ]; then
    ok "docker data dir $root: $(df -h --output=avail "$root" | tail -n1 | tr -d ' ') free"
  fi
}

check_env() {
  step ".env settings"
  if [ ! -f "$ENV_FILE" ]; then
    fail ".env not found"
    hint "make env, then set the ports and UI_BIND (docs/deploy-shared-server.md §2)"
    return
  fi
  local mode
  mode=$(stat -c '%a' "$ENV_FILE")
  if [ $((8#$mode & 8#077)) -ne 0 ]; then
    warn ".env mode $mode: readable beyond your user on a shared server"
    hint "chmod 600 .env"
  else
    ok ".env mode $mode"
  fi

  local pw
  pw=$(env_get POSTGRES_PASSWORD)
  if [ -z "$pw" ] || [ "$pw" = "change-me" ]; then
    fail "POSTGRES_PASSWORD is empty or the placeholder"
    hint "make env generates one for a new .env"
  else
    ok "POSTGRES_PASSWORD is set"
  fi
  if [ -n "$(env_get DEMO_API_KEY)" ]; then
    ok "DEMO_API_KEY is set"
  else
    warn "DEMO_API_KEY is empty: the UI will ask for an API key"
  fi

  local bind
  bind=$(env_get UI_BIND)
  if [ "$bind" = "127.0.0.1" ]; then
    ok "UI_BIND=127.0.0.1 (only the reverse proxy on this host reaches the UI)"
  else
    fail "UI_BIND=${bind:-<unset, 0.0.0.0>}: the UI would listen on every interface"
    hint "set UI_BIND=127.0.0.1 in .env"
  fi

  local name port seen=" "
  for name in FRONTEND_PORT API_PORT POSTGRES_PORT; do
    port=$(env_get "$name")
    if [ -z "$port" ]; then
      fail "$name is not set: the default port is almost certainly taken on a shared server"
      continue
    fi
    if ! [[ $port =~ ^[0-9]+$ ]] || [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
      fail "$name=$port is not a port in 1024-65535 (rootless Docker cannot bind below 1024)"
      continue
    fi
    case $seen in
      *" $port "*)
        fail "$name=$port is used twice in .env"
        continue
        ;;
    esac
    seen="$seen$port "
    ok "$name=$port"
  done
}

check_ports() {
  step "ports"
  local name port owner
  for name in FRONTEND_PORT API_PORT POSTGRES_PORT; do
    port=$(env_get "$name")
    [[ $port =~ ^[0-9]+$ ]] || continue
    owner=""
    have docker && owner=$(port_owner "$port")
    if [ -n "$owner" ]; then
      ok "$name=$port is published by this stack ($owner)"
    elif port_listening "$port"; then
      fail "$name=$port is already taken by another process or user"
      hint "pick a free port: ss -Hltn | awk '{print \$4}' | sort -u"
    else
      ok "$name=$port is free"
    fi
  done
}

check_files() {
  step "repository and permissions"
  cd "$ROOT"
  ok "umask $(umask) (with 0007 new files are not world-readable, see §3)"
  local bad
  bad=$( (find db seed \( -type d ! -perm -o=rx \) -o \( -type f ! -perm -o=r \)) 2> /dev/null | head -n5)
  if [ -n "$bad" ]; then
    fail "db/ and seed/ are bind-mounted but not world-readable, e.g. $(printf '%s' "$bad" | head -n1)"
    hint "chmod -R o+rX db seed   (tools/deploy.sh update does this)"
  else
    ok "db/ and seed/ are world-readable"
  fi
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    warn "tracked files have local changes: update will refuse to pull"
    hint "git status; git stash or git checkout -- <file>"
  else
    ok "working tree clean ($(git rev-parse --short HEAD))"
  fi
  if git symbolic-ref -q HEAD > /dev/null; then
    if git rev-parse --abbrev-ref '@{u}' > /dev/null 2>&1; then
      ok "branch $(git rev-parse --abbrev-ref HEAD) tracks $(git rev-parse --abbrev-ref '@{u}')"
    else
      warn "branch $(git rev-parse --abbrev-ref HEAD) has no upstream: update cannot pull"
    fi
  else
    warn "HEAD is detached (after a rollback?): update needs a branch"
    hint "git checkout main"
  fi
  if have free; then
    local avail
    avail=$(free -m | awk '/^Mem:/ {print $7}')
    if [ -n "$avail" ] && [ "$avail" -lt 2048 ]; then
      warn "only ${avail} MB of memory available: load publications from a workstation (§6)"
    else
      ok "${avail:-?} MB of memory available"
    fi
  fi
}

run_check() {
  FAILS=0 WARNS=0
  check_tools
  check_docker
  check_env
  check_ports
  check_files
  printf '\n'
  if [ "$FAILS" -gt 0 ]; then
    printf '%scheck: %d failed, %d warnings%s\n' "$C_FAIL" "$FAILS" "$WARNS" "$C_OFF"
    return 1
  fi
  printf '%scheck: passed%s (%d warnings)\n' "$C_OK" "$C_OFF" "$WARNS"
}

# ---------------------------------------------------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------------------------------------------------

run_health() {
  step "health"
  FAILS=0
  local api ui status
  api="http://127.0.0.1:$(env_get API_PORT)"
  ui="http://127.0.0.1:$(env_get FRONTEND_PORT)"
  # shellcheck disable=SC2016 # expanded inside the container, where POSTGRES_USER/POSTGRES_DB are set
  if compose exec -T postgres sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2> /dev/null; then
    ok "postgres accepts connections"
  else
    fail "postgres does not accept connections (in recovery? see docs/deploy-shared-server.md §9)"
    hint "docker compose logs --tail=50 postgres"
  fi
  if curl -fsS -m 5 -o /dev/null "$api/health"; then
    ok "API liveness $api/health"
  else
    fail "API liveness $api/health"
    hint "docker compose logs --tail=100 backend"
  fi
  status=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "$api/api/v1/health" || true)
  if [ "$status" = "200" ]; then
    ok "API readiness $api/api/v1/health (database and marts)"
  else
    fail "API readiness $api/api/v1/health: HTTP ${status:-none}"
  fi
  if curl -fsS -m 5 -o /dev/null "$ui/healthz"; then
    ok "UI $ui/healthz"
  else
    fail "UI $ui/healthz"
    hint "docker compose logs --tail=50 frontend"
  fi
  [ "$FAILS" -eq 0 ]
}

# ---------------------------------------------------------------------------------------------------------------------
# update / rollback
# ---------------------------------------------------------------------------------------------------------------------

# Alembic revision the database is at, via the running backend container; empty when it is not running.
db_revision() {
  compose exec -T backend alembic current 2> /dev/null | awk '/^[0-9a-f]+/ {print $1; exit}' || true
}

save_state() {
  local rev
  rev=$(db_revision)
  printf 'commit=%s\nrevision=%s\ndate=%s\n' "$(git rev-parse HEAD)" "$rev" "$(date -u +%FT%TZ)" > "$STATE_FILE"
  ok "recorded commit $(git rev-parse --short HEAD), database revision ${rev:-unknown} in $(basename "$STATE_FILE")"
}

state_get() { sed -n "s/^$1=//p" "$STATE_FILE" 2> /dev/null | tail -n1; }

fix_permissions() {
  step "permissions of bind-mounted directories"
  chmod -R o+rX "$ROOT/db" "$ROOT/seed"
  ok "chmod -R o+rX db seed"
}

start_stack() {
  step "build and start (make up; the backend applies migrations on start)"
  (cd "$ROOT" && make --no-print-directory up) || die "make up failed: docker compose ps; docker compose logs --tail=100 backend"
  ok "containers are up and healthy"
}

require_clean_tree() {
  [ -z "$(git status --porcelain --untracked-files=no)" ] \
    || die "tracked files have local changes; commit, stash or discard them first (git status)"
}

run_update() {
  run_check || die "fix the failed checks above, then run tools/deploy.sh update again"
  cd "$ROOT"
  step "git"
  require_clean_tree
  git symbolic-ref -q HEAD > /dev/null || die "HEAD is detached (after a rollback?): git checkout main, then update"
  git rev-parse --abbrev-ref '@{u}' > /dev/null 2>&1 || die "branch has no upstream: git branch -u origin/main"
  git fetch --quiet || die "git fetch failed"
  local head upstream
  head=$(git rev-parse HEAD)
  upstream=$(git rev-parse '@{u}')
  if [ "$head" = "$upstream" ]; then
    ok "already at $(git rev-parse --short HEAD); no pull needed"
  else
    git merge-base --is-ancestor HEAD '@{u}' || die "local branch has diverged from $(git rev-parse --abbrev-ref '@{u}'); resolve by hand"
    git log --oneline "HEAD..@{u}" | sed 's/^/        /'
    save_state
    if ! git diff --quiet HEAD '@{u}' -- backend/alembic/versions; then
      if [ -n "$(state_get revision)" ]; then
        step "backup (the update brings new migrations)"
        (cd "$ROOT" && make --no-print-directory backup) || die "make backup failed; not updating"
      else
        warn "the update brings new migrations but the stack is not running, so no backup was taken"
      fi
    fi
    git pull --ff-only --quiet || die "git pull --ff-only failed"
    ok "updated $(git rev-parse --short "$head") -> $(git rev-parse --short HEAD)"
  fi
  fix_permissions
  start_stack
  run_health || die "the stack is up but a health check failed (see above)"
  printf '\n%supdate complete%s at %s\n' "$C_OK" "$C_OFF" "$(git rev-parse --short HEAD)"
}

run_rollback() {
  local target=${1:-}
  cd "$ROOT"
  step "rollback"
  require_clean_tree
  if [ -z "$target" ]; then
    target=$(state_get commit)
    [ -n "$target" ] || die "no previous update recorded; pass the commit: tools/deploy.sh rollback <commit>"
  fi
  target=$(git rev-parse --verify --quiet "$target^{commit}") || die "unknown commit: ${1:-recorded commit}"
  [ "$target" != "$(git rev-parse HEAD)" ] || die "already at $(git rev-parse --short "$target")"
  ok "target $(git log -1 --format='%h %s' "$target")"

  if ! git diff --quiet "$target" HEAD -- backend/alembic/versions; then
    local want current
    want=""
    [ "$target" = "$(state_get commit)" ] && want=$(state_get revision)
    [ -n "$want" ] || die "migrations differ between the commits and the target's database revision is unknown;
  restore the backup taken before the update (make restore FILE=backups/...) or downgrade by hand (docs §10)"
    current=$(db_revision)
    [ -n "$current" ] || die "the backend is not running, so the database cannot be downgraded with the new code;
  start it (make up) and run the rollback again"
    if [ "$current" != "$want" ]; then
      step "downgrade database $current -> $want (with the code that knows both revisions)"
      compose exec -T backend alembic downgrade "$want" || die "alembic downgrade failed; restore the backup (docs §9-10)"
      ok "database at revision $want"
    fi
  fi

  git checkout --quiet --detach "$target" || die "git checkout failed"
  ok "checked out $(git rev-parse --short HEAD) (detached; git checkout main returns to updates)"
  fix_permissions
  start_stack
  run_health || die "the stack is up but a health check failed (see above)"
  printf '\n%srollback complete%s at %s\n' "$C_OK" "$C_OFF" "$(git rev-parse --short HEAD)"
}

main() {
  local cmd=${1:-}
  [ $# -gt 0 ] && shift
  if have git && git -C "$ROOT" rev-parse --git-dir > /dev/null 2>&1; then
    STATE_FILE=$(git -C "$ROOT" rev-parse --absolute-git-dir)/hqai-deploy-state
  elif [ "$cmd" = update ] || [ "$cmd" = rollback ]; then
    die "$ROOT is not a git checkout"
  fi
  case $cmd in
    check) run_check ;;
    health) run_health ;;
    update) run_update ;;
    rollback) run_rollback "$@" ;;
    -h | --help | help) usage ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
