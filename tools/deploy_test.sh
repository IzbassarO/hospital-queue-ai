#!/usr/bin/env bash
# Tests for tools/deploy.sh: shellcheck, then the script itself in a throwaway checkout with a local bare "origin"
# and stub docker/make/curl/loginctl/systemctl, so no Docker daemon or network is needed.
#
#   bash tools/deploy_test.sh        (needs shellcheck: apt install shellcheck, or pip install shellcheck-py)
#
# Asserts that `check` finds the documented problems (world-unreadable db/ and seed/, UI_BIND, missing, clashing or
# taken ports), passes on a correct setup and changes nothing on disk; that `update` pulls, backs up before a new
# migration, fixes permissions under umask 0007 and is idempotent; that `rollback` downgrades the database before
# checking out the previous commit; and that no command ever prints a value from .env.
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

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# --- stubs: a rootless daemon with no containers, linger on, docker.service enabled -----------------------------------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" << 'EOF'
#!/bin/sh
case "$1 $2" in
  "compose version") echo "2.29.1" ;;
  "info --format")
    case "$3" in
      *SecurityOptions*) echo '["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]' ;;
      *) echo "" ;;
    esac ;;
  "ps --filter") ;;
  *) echo "stub docker: unexpected $*" >&2; exit 1 ;;
esac
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
expect() { # description, expected exit code, grep pattern expected in the output
  if [ "$RC" -eq "$2" ] && grep -Eq "$3" "$OUT"; then
    pass "$1"
  else
    failed "$1 (exit $RC, expected $2; pattern '$3')"
    sed 's/^/        | /' "$OUT"
  fi
}
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
expect ".env readable by the group warns" 0 "warn.*\.env mode 660"

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
# The stack stubs: the backend reports Alembic revision 0015, every health endpoint answers 200, make and docker
# record what they were asked to do in $CALLS.
CALLS="$WORK/calls.log"
: > "$CALLS"
export CALLS
cat > "$WORK/bin/docker" << 'EOF2'
#!/bin/sh
echo "docker $*" >> "$CALLS"
case "$1 $2" in
  "compose version") echo "2.29.1" ;;
  "info --format")
    case "$3" in
      *SecurityOptions*) echo '["name=seccomp,profile=builtin","name=rootless"]' ;;
      *) echo "" ;;
    esac ;;
  "ps --filter") ;;
  "compose exec")
    case "$*" in
      *"alembic current"*) echo "${STUB_REVISION:-0015} (head)" ;;
    esac ;;
  *) echo "stub docker: unexpected $*" >&2; exit 1 ;;
esac
EOF2
cat > "$WORK/bin/make" << 'EOF2'
#!/bin/sh
echo "make $*" >> "$CALLS"
EOF2
cat > "$WORK/bin/curl" << 'EOF2'
#!/bin/sh
case "$*" in *%{http_code}*) printf 200 ;; esac
EOF2
chmod +x "$WORK/bin/"*

ORIGIN="$WORK/origin.git"
git clone --quiet --bare "$REPO" "$ORIGIN"
git -C "$REPO" remote add origin "$ORIGIN"
git -C "$REPO" fetch --quiet origin
git -C "$REPO" branch --quiet -u "origin/$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
OLD=$(git -C "$REPO" rev-parse HEAD)
# upstream gets a migration and a new seed file
UP="$WORK/upstream"
git clone --quiet "$ORIGIN" "$UP"
mkdir -p "$UP/backend/alembic/versions"
echo "revision = '0016'" > "$UP/backend/alembic/versions/0016_new.py"
echo "y" > "$UP/seed/tables/new.csv"
git -C "$UP" add .
git -C "$UP" -c user.name=t -c user.email=t@example.invalid commit --quiet -m "new migration"
git -C "$UP" push --quiet origin HEAD
NEW=$(git -C "$UP" rev-parse HEAD)

write_env 127.0.0.1 "$UI" "$API" "$PG"
run_deploy() {
  set +e
  (umask 0007 && bash "$REPO/tools/deploy.sh" "$@") > "$OUT" 2>&1
  RC=$?
  set -e
  if grep -q "$MARK" "$OUT"; then failed "deploy.sh $*: output contains a value from .env"; fi
}

run_deploy update
expect "update pulls and reports the new commit" 0 "update complete"
if [ "$(git -C "$REPO" rev-parse HEAD)" = "$NEW" ]; then pass "HEAD is the upstream commit"; else failed "HEAD after update"; fi
if grep -q "^make .*backup" "$CALLS"; then pass "incoming migration -> make backup before the pull"; else failed "no backup"; fi
if grep -q "^make .*up" "$CALLS"; then pass "make up ran"; else failed "make up did not run"; fi
if [ -n "$(find "$REPO/seed/tables/new.csv" -perm -o=r)" ]; then
  pass "a file pulled under umask 0007 is made world-readable"
else
  failed "seed/tables/new.csv is not world-readable after update"
fi
state="$(git -C "$REPO" rev-parse --absolute-git-dir)/hqai-deploy-state"
if grep -q "^commit=$OLD" "$state" && grep -q "^revision=0015" "$state"; then
  pass "previous commit and database revision recorded in .git"
else
  failed "state file"
fi

: > "$CALLS"
run_deploy update
expect "second update is a no-op pull and still converges" 0 "already at"
if grep -q "^make .*backup" "$CALLS"; then failed "second update took a backup"; else pass "no backup when nothing is pulled"; fi

: > "$CALLS"
export STUB_REVISION=0016 # the database is at the new migration now
run_deploy rollback
unset STUB_REVISION
expect "rollback returns to the recorded commit" 0 "rollback complete"
if [ "$(git -C "$REPO" rev-parse HEAD)" = "$OLD" ]; then pass "HEAD is the previous commit"; else failed "HEAD after rollback"; fi
if grep -q "alembic downgrade 0015" "$CALLS"; then
  pass "database downgraded to the recorded revision before the checkout"
else
  failed "no alembic downgrade"
fi

run_deploy update
expect "update refuses on a detached HEAD after a rollback" 1 "HEAD is detached"

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
