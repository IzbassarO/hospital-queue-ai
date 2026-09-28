#!/usr/bin/env bash
# Tests for tools/deploy.sh: shellcheck, a static scan for destructive commands, then the script itself in a
# throwaway checkout with a local bare "origin" and stub docker/make/curl/loginctl/systemctl/id/free — no Docker
# daemon, no network, no credentials, nothing deployed. CI runs it (the deploy-tooling job).
#
#   bash tools/deploy_test.sh        (needs shellcheck: apt install shellcheck, or pip install shellcheck-py)
#
# Asserts that `check` finds the documented problems (world-unreadable db/ and seed/, UI_BIND, missing, clashing or
# taken ports, a readable .env, root, a shared rootful daemon, too little memory) and changes nothing on disk; that
# `update` refuses while PostgreSQL recovers or when no backup can precede incoming migrations, backs up with mode
# 600 before fast-forwarding exactly the inspected commits, fixes permissions under umask 0007, is idempotent, and
# fails when the app — not only its containers — is unhealthy; that `rollback` backs up and downgrades before
# checking out; and that no command ever prints a value from .env.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPT="$HERE/deploy.sh"
PASSED=0
FAILED=0

pass() {
  printf '  ok    %s\n' "$*"
  PASSED=$((PASSED + 1))
}
failed() {
  printf '  FAIL  %s\n' "$*"
  FAILED=$((FAILED + 1))
}

echo "== shellcheck"
if ! command -v shellcheck > /dev/null 2>&1; then
  echo "shellcheck not found: apt install shellcheck, or pip install shellcheck-py" >&2
  exit 1
fi
if shellcheck -x "$SCRIPT" "${BASH_SOURCE[0]}"; then
  pass "shellcheck tools/deploy.sh tools/deploy_test.sh"
else
  failed "shellcheck"
fi

echo "== no destructive or privileged command in tools/deploy.sh"
# comments are allowed to name them; code lines are not
code=$(grep -v '^[[:space:]]*#' "$SCRIPT")
# shellcheck disable=SC2016 # literal strings to search for, not expansions
for forbidden in 'sudo ' 'down -v' 'volume rm' 'volume prune' 'system prune' 'reset --hard' 'push --force' \
  'push -f' 'clean -f' 'rm -rf' 'set -x' 'cat "$ENV_FILE"' '. "$ENV_FILE"' 'source '; do
  if printf '%s' "$code" | grep -qF -- "$forbidden"; then failed "deploy.sh contains '$forbidden'"; else pass "no '$forbidden'"; fi
done
if printf '%s' "$code" | grep -q 'git pull' && ! printf '%s' "$code" | grep -q 'pull --ff-only'; then
  failed "git pull without --ff-only"
else
  pass "git only fast-forwards"
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# --- stubs ------------------------------------------------------------------------------------------------------------
# Knobs (environment): STUB_ROOTLESS=0 (a shared rootful daemon), STUB_PG=ready|recovering|down, STUB_HEAD=0 (schema
# behind the code), STUB_REVISION, STUB_DB=unavailable, STUB_STATUS=degraded, STUB_UP_RC, STUB_UID, STUB_MEM.
CALLS="$WORK/calls.log"
: > "$CALLS"
export CALLS
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" << 'EOF'
#!/bin/sh
echo "docker $*" >> "$CALLS"
if [ -n "${STUB_PG_UNTIL_UP:-}" ] && [ -f "$STUB_PG_UNTIL_UP" ]; then STUB_PG=ready; fi
case "$1 $2" in
  "compose version") echo "2.29.1" ;;
  "info --format")
    case "$3" in
      *SecurityOptions*)
        if [ "${STUB_ROOTLESS:-1}" = 1 ]; then echo '["name=seccomp,profile=builtin","name=rootless"]'
        else echo '["name=seccomp,profile=builtin"]'; fi ;;
      *) echo "" ;;
    esac ;;
  "ps --filter") ;;
  "compose ps") [ "${STUB_PG:-ready}" = down ] || echo 0123456789ab ;;
  "compose exec")
    case "$*" in
      *pg_isready*) [ "${STUB_PG:-ready}" = ready ] ;;
      *"alembic current"*)
        if [ "${STUB_HEAD:-1}" = 1 ]; then echo "${STUB_REVISION:-0015} (head)"; else echo "${STUB_REVISION:-0015}"; fi ;;
      *"alembic downgrade"*) ;;
      *) echo "stub docker: unexpected $*" >&2; exit 1 ;;
    esac ;;
  *) echo "stub docker: unexpected $*" >&2; exit 1 ;;
esac
EOF
cat > "$WORK/bin/make" << 'EOF'
#!/bin/sh
echo "make $*" >> "$CALLS"
case "$*" in
  *backup*)
    mkdir -p backups
    sleep 0.01
    echo "dump" > "backups/hqai_$(date +%s%N).dump" ;;
  *up*)
    [ -z "${STUB_PG_UNTIL_UP:-}" ] || touch "$STUB_PG_UNTIL_UP"
    exit "${STUB_UP_RC:-0}" ;;
esac
EOF
cat > "$WORK/bin/curl" << 'EOF'
#!/bin/sh
echo "curl $*" >> "$CALLS"
case "$*" in
  *%{http_code}*) printf 200 ;;
  */api/v1/health*)
    printf '{"status":"%s","database":"%s","marts_as_of_date":"2025-03-31"}' \
      "${STUB_STATUS:-ok}" "${STUB_DB:-ok}" ;;
esac
EOF
cat > "$WORK/bin/id" << 'EOF'
#!/bin/sh
case "$1" in -u) echo "${STUB_UID:-1000}" ;; -un) echo tester ;; *) echo "uid=${STUB_UID:-1000}(tester)" ;; esac
EOF
cat > "$WORK/bin/free" << 'EOF'
#!/bin/sh
echo "              total        used        free      shared  buff/cache   available"
echo "Mem:          16000        4000        8000         100        4000        ${STUB_MEM:-8000}"
EOF
printf '#!/bin/sh\necho yes\n' > "$WORK/bin/loginctl"
printf '#!/bin/sh\necho enabled\n' > "$WORK/bin/systemctl"
chmod +x "$WORK/bin/"*
export PATH="$WORK/bin:$PATH"

# --- a checkout as a fresh clone under umask 0007 leaves it -----------------------------------------------------------
REPO="$WORK/repo"
mkdir -p "$REPO/tools" "$REPO/db" "$REPO/seed/tables"
cp "$SCRIPT" "$REPO/tools/deploy.sh"
echo "select 1;" > "$REPO/db/init.sql"
echo "{}" > "$REPO/seed/manifest.json"
echo "x" > "$REPO/seed/tables/t.csv"
printf 'backups/\n.env\n' > "$REPO/.gitignore"
chmod -R o-rwx "$REPO/db" "$REPO/seed"
git -C "$REPO" init --quiet
git -C "$REPO" add .
git -C "$REPO" -c user.name=t -c user.email=t@example.invalid commit --quiet -m init

# three free high ports
free_port() {
  local p
  for p in $(seq "$1" "$(($1 + 200))"); do
    if [ -z "$(ss -Hltn "sport = :$p" 2> /dev/null)" ] && ! (exec 3<> "/dev/tcp/127.0.0.1/$p") 2> /dev/null; then
      echo "$p"
      return
    fi
  done
}
UI=$(free_port 41000)
API=$(free_port 42000)
PG=$(free_port 43000)

# Values that must never appear in the output: built at run time, so the repository holds no secret-looking literal.
MARK="never-print-$RANDOM$RANDOM"
write_env() { # UI_BIND FRONTEND_PORT API_PORT POSTGRES_PORT
  {
    echo "POSTGRES_USER=hqai"
    printf '%s=%s\n' POSTGRES_PASSWORD "$MARK-pw"
    echo "POSTGRES_DB=hqai"
    printf '%s=%s\n' DEMO_API_KEY "$MARK-key"
    printf '%s=%s\n' ASSISTANT_API_KEY "$MARK-assistant"
    echo "UI_BIND=$1"
    echo "FRONTEND_PORT=$2"
    echo "API_PORT=$3"
    echo "POSTGRES_PORT=$4"
  } > "$REPO/.env"
  chmod 600 "$REPO/.env"
}

OUT="$WORK/out.txt"
run_check() {
  set +e
  bash "$REPO/tools/deploy.sh" check > "$OUT" 2>&1
  RC=$?
  set -e
  if grep -q "$MARK" "$OUT"; then failed "$1: output contains a value from .env"; fi
}
run_deploy() {
  set +e
  (umask 0007 && bash "$REPO/tools/deploy.sh" "$@") > "$OUT" 2>&1
  RC=$?
  set -e
  if grep -q "$MARK" "$OUT"; then failed "deploy.sh $*: output contains a value from .env"; fi
}
expect() { # description, expected exit code, grep pattern expected in the output
  if [ "$RC" -eq "$2" ] && grep -Eq "$3" "$OUT"; then
    pass "$1"
  else
    failed "$1 (exit $RC, expected $2; pattern '$3')"
    sed 's/^/        | /' "$OUT"
  fi
}
called() { grep -q -- "$1" "$CALLS"; }
snapshot() { (cd "$REPO" && find . -path ./.git -prune -o -printf '%m %s %p\n' | sort && git status --porcelain); }

echo "== tools/deploy.sh check"
write_env 127.0.0.1 "$UI" "$API" "$PG"
before=$(snapshot)
run_check "umask"
expect "db/ and seed/ not world-readable -> fails with the chmod hint" 1 "chmod -R o\+rX db seed"
if [ "$(snapshot)" = "$before" ]; then pass "check changes nothing on disk"; else failed "check changed files"; fi

chmod -R o+rX "$REPO/db" "$REPO/seed"
run_check "good"
expect "correct setup passes" 0 "check: passed"
expect "ports are reported free" 0 "FRONTEND_PORT=$UI is free"
if grep -q "POSTGRES_PASSWORD is set" "$OUT"; then pass "secrets reported as set, not shown"; else failed "secret status"; fi

write_env 0.0.0.0 "$UI" "$API" "$PG"
run_check "bind"
expect "UI_BIND other than 127.0.0.1 fails" 1 "FAIL.*UI_BIND=0\.0\.0\.0"

write_env 127.0.0.1 "$UI" "$UI" "$PG"
run_check "dup"
expect "the same port twice fails" 1 "FAIL.*API_PORT=$UI is used twice"

write_env 127.0.0.1 "$UI" 80 "$PG"
run_check "low"
expect "a port below 1024 fails" 1 "FAIL.*API_PORT=80 is not a port"

sed -i '/^POSTGRES_PORT=/d' "$REPO/.env"
run_check "missing"
expect "a missing port fails" 1 "FAIL.*POSTGRES_PORT is not set"

write_env 127.0.0.1 "$UI" "$API" "$PG"
chmod 660 "$REPO/.env"
run_check "mode"
expect ".env readable by the group fails (shared server)" 1 "FAIL.*\.env mode 660"
chmod 600 "$REPO/.env"

STUB_UID=0 run_check "root"
expect "running as root fails" 1 "FAIL.*running as root"
STUB_ROOTLESS=0 run_check "rootful"
expect "a shared rootful daemon fails" 1 "FAIL.*daemon is not rootless"
STUB_MEM=800 run_check "oom"
expect "under 1 GB of memory fails" 1 "FAIL.*800 MB of memory"
STUB_MEM=800 DEPLOY_ALLOW_LOW_MEMORY=1 run_check "oom-override"
expect "DEPLOY_ALLOW_LOW_MEMORY=1 turns it into a warning" 0 "warn.*800 MB of memory"
STUB_MEM=1500 run_check "tight"
expect "under 2 GB warns" 0 "warn.*1500 MB of memory"

if command -v python3 > /dev/null 2>&1; then
  python3 -c 'import socket,sys,time; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.listen(); time.sleep(20)' "$API" &
  LISTENER=$!
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if (exec 3<> "/dev/tcp/127.0.0.1/$API") 2> /dev/null; then break; fi
    sleep 0.2
  done
  run_check "taken"
  kill "$LISTENER" 2> /dev/null || true
  expect "a port taken by someone else fails" 1 "FAIL.*API_PORT=$API is already taken"
fi

echo "== tools/deploy.sh update and rollback (stub docker, make, curl; umask 0007)"
ORIGIN="$WORK/origin.git"
git clone --quiet --bare "$REPO" "$ORIGIN"
git -C "$REPO" remote add origin "$ORIGIN"
git -C "$REPO" fetch --quiet origin
BRANCH=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)
git -C "$REPO" branch --quiet -u "origin/$BRANCH"
OLD=$(git -C "$REPO" rev-parse HEAD)
UP="$WORK/upstream"
git clone --quiet "$ORIGIN" "$UP"
push_upstream() { # message, file to add
  mkdir -p "$(dirname "$UP/$2")"
  echo "$1" > "$UP/$2"
  git -C "$UP" add .
  git -C "$UP" -c user.name=t -c user.email=t@example.invalid commit --quiet -m "$1"
  git -C "$UP" push --quiet origin HEAD
}
# upstream gets a migration and a new seed file
echo "y" > "$UP/seed/tables/new.csv"
push_upstream "revision = '0016'" backend/alembic/versions/0016_new.py
NEW=$(git -C "$UP" rev-parse HEAD)
head_is() { [ "$(git -C "$REPO" rev-parse HEAD)" = "$1" ]; }

: > "$CALLS"
STUB_PG=recovering run_deploy update
expect "PostgreSQL in recovery: update refuses before changing anything" 1 "not accepting connections \(crash recovery"
if head_is "$OLD" && ! called "make --no-print-directory up"; then pass "nothing pulled, nothing started"; else failed "update acted during recovery"; fi

: > "$CALLS"
STUB_PG=down run_deploy update
expect "incoming migration without a reachable database: refuses (no backup possible)" 1 "no backup can be taken"
if head_is "$OLD"; then pass "nothing pulled without a backup"; else failed "pulled without a backup"; fi

: > "$CALLS"
run_deploy update
expect "update fast-forwards and reports the new commit" 0 "update complete"
if head_is "$NEW"; then pass "HEAD is the upstream commit"; else failed "HEAD after update"; fi
backup_line=$(grep -n "make --no-print-directory backup" "$CALLS" | cut -d: -f1 | head -n1)
up_line=$(grep -n "make --no-print-directory up" "$CALLS" | cut -d: -f1 | head -n1)
if [ -n "$backup_line" ] && [ -n "$up_line" ] && [ "$backup_line" -lt "$up_line" ]; then
  pass "backup taken before the new code starts (and migrates)"
else
  failed "backup order (backup line ${backup_line:-none}, up line ${up_line:-none})"
fi
dump=$(find "$REPO/backups" -name 'hqai_*.dump' | head -n1)
if [ -n "$dump" ] && [ "$(stat -c %a "$dump")" = 600 ] && [ "$(stat -c %a "$REPO/backups")" = 700 ]; then
  pass "backup readable by this user only (file 600, directory 700)"
else
  failed "backup permissions ${dump:+$(stat -c %a "$dump")} / $(stat -c %a "$REPO/backups" 2> /dev/null)"
fi
if [ -n "$(find "$REPO/seed/tables/new.csv" -perm -o=r)" ]; then
  pass "a file pulled under umask 0007 is made world-readable"
else
  failed "seed/tables/new.csv is not world-readable after update"
fi
for probe in "/api/v1/health" "http://127.0.0.1:$UI/api/v1/health" "alembic current" "/healthz"; do
  if called "$probe"; then pass "health probes $probe"; else failed "health did not probe $probe"; fi
done
state="$(git -C "$REPO" rev-parse --absolute-git-dir)/hqai-deploy-state"
if grep -q "^commit=$OLD" "$state" && grep -q "^revision=0015" "$state"; then
  pass "previous commit and database revision recorded in .git"
else
  failed "state file"
fi

: > "$CALLS"
run_deploy update
expect "second update is a no-op pull and still converges" 0 "already at"
if called "backup"; then failed "second update took a backup"; else pass "no backup when nothing is pulled"; fi

STUB_STATUS=degraded run_deploy update
expect "no marts yet: a warning, not a failure (first install before the seed)" 0 "warn.*degraded"
STUB_DB=unavailable run_deploy update
expect "backend cannot reach its database: update fails" 1 "health check failed"
STUB_HEAD=0 run_deploy update
expect "schema behind the code's migration head: update fails" 1 "FAIL.*not at the code's migration head"
STUB_UP_RC=1 run_deploy update
expect "make up fails: update stops and points at rollback" 1 "make up failed.*|rollback"

: > "$CALLS"
export STUB_REVISION=0016 # the database is at the new migration now
run_deploy rollback
unset STUB_REVISION
expect "rollback returns to the recorded commit" 0 "rollback complete"
if head_is "$OLD"; then pass "HEAD is the previous commit"; else failed "HEAD after rollback"; fi
backup_line=$(grep -n "make --no-print-directory backup" "$CALLS" | cut -d: -f1 | head -n1)
downgrade_line=$(grep -n "alembic downgrade 0015" "$CALLS" | cut -d: -f1 | head -n1)
if [ -n "$backup_line" ] && [ -n "$downgrade_line" ] && [ "$backup_line" -lt "$downgrade_line" ]; then
  pass "backup, then downgrade to the recorded revision, before the checkout"
else
  failed "rollback order (backup ${backup_line:-none}, downgrade ${downgrade_line:-none})"
fi

run_deploy update
expect "update refuses on a detached HEAD after a rollback" 1 "HEAD is detached"

# a local commit that is not upstream: diverged, never merged or reset
git -C "$REPO" checkout --quiet "$BRANCH"
echo "local" > "$REPO/local.txt"
git -C "$REPO" add local.txt
git -C "$REPO" -c user.name=t -c user.email=t@example.invalid commit --quiet -m local
LOCAL=$(git -C "$REPO" rev-parse HEAD)
push_upstream "later" seed/later.txt
run_deploy update
expect "a diverged branch is refused, not merged or reset" 1 "diverged"
if head_is "$LOCAL"; then pass "local commit kept"; else failed "diverged branch was changed"; fi
git -C "$REPO" reset --quiet --hard "origin/$BRANCH" # the test's own cleanup, not the script's

push_upstream "revision = '0017'" backend/alembic/versions/0017_new.py
STUB_PG=down STUB_PG_UNTIL_UP="$WORK/started" DEPLOY_ALLOW_NO_BACKUP=1 run_deploy update
expect "DEPLOY_ALLOW_NO_BACKUP=1 proceeds without a backup, saying so" 0 "warn.*no backup was taken"

echo "local change" >> "$REPO/db/init.sql"
run_deploy rollback "$OLD"
expect "rollback refuses with local changes" 1 "local changes"

set +e
bash "$REPO/tools/deploy.sh" nonsense > "$OUT" 2>&1
RC=$?
set -e
expect "unknown command -> usage, exit 2" 2 "tools/deploy.sh check"

printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
[ "$FAILED" -eq 0 ]
