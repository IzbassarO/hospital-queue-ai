#!/usr/bin/env python3
"""Repository audit — run before every commit: `make audit`. Prints a table, exits 1 if any check fails.

Checks
  layout     every tracked-candidate file (not ignored by .gitignore) is under an allowed top-level directory or is
             an allowed root config file
  secrets    no tracked-candidate file is a .env or contains a common secret pattern (private keys, cloud / GitHub /
             Slack / API tokens, hqai_ API keys, hard-coded passwords, tokens or keys in assignments or connection
             URLs);
             placeholders such as change-me and ${VAR} are allowed. scratch/ is ignored by .gitignore, so never scanned
  architecture  AST-based backend/ML dependency boundaries and API raw-SQL guard (tools/architecture_check.py)
  openapi    stable operation IDs and a current deterministic backend/openapi.json snapshot
  alembic    `alembic check`: the SQLAlchemy models and the migrations agree (needs the database)
  ruff       `ruff check` and `ruff format --check` on backend/, ml/, tools/
  pytest     the API tests (needs the database with marts built)
  api-docs   the endpoints documented in docs/api.md (### `METHOD /path` headings) are exactly the app's /api/v1 routes
  api-auth   every FastAPI route except the health checks (/health, /api/v1/health) depends on an auth dependency
             (app.core.security.require_role, marked `__hqai_auth__`), directly or through a router include
  web-lint   when frontend/package.json exists: `npm run lint` (ESLint + Prettier check)
  web-contract when frontend/package.json exists: generated TypeScript transport types match backend/openapi.json
  web-build  when frontend/package.json exists: `npm run build` (TypeScript check + Vite production build)
  web-bundle the built frontend (frontend/dist) contains no API key or other secret: credentials are added by the
             proxy server-side, never compiled into the bundle the browser downloads (docs/security.md)

Tracked candidates are found without git: the working tree minus what .gitignore matches (the patterns used in this
repository: names, globs, trailing-slash directories, root-anchored paths, `!` negation).
"""

import fnmatch
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

ALLOWED_DIRS = {"backend", "ml", "frontend", "db", "docs", "tools", ".github"}
ALLOWED_ROOT_FILES = {
    "README.md",
    "Makefile",
    "docker-compose.yml",
    "requirements.txt",
    "pyproject.toml",
    ".gitignore",
    ".env.example",
    ".dockerignore",
    ".python-version",
}
ALWAYS_SKIPPED = {".git"}

SECRET_PATTERNS: dict[str, re.Pattern] = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "API key (sk-…)": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    "hospital-queue-ai API key": re.compile(r"\bhqai_[A-Za-z0-9_-]{40,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "credential assignment": re.compile(
        r"(?i)\b(?P<name>[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)[\w.-]*)\b"
        r"[\"']?\s*[:=]\s*(?P<quote>[\"'])?(?P<value>[^\s\"',;)}]{6,})"
    ),
    "password in URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:(?P<value>[^\s@/]{3,})@"),
}
# values that are clearly not secrets: placeholders, variable references, code expressions
PLACEHOLDER = re.compile(
    r"(?i)^(?:change-?me|changeme|postgres|example|placeholder|dummy|test|secret|password|x+|\*+|<[^>]*>|"
    r"\$\{?\w+(?::?-[^}]*)?\}?|\$\(\w+\)|\{\{.*\}\}|%\(\w+\)s|settings\.\w+|self\.\w+|os\.environ.*|none|null|true|false|str|int|"
    r"bool|required|optional)$"
)
# in source files an unquoted value is an expression (apiKey, process.env.X), not a hard-coded secret; a real
# secret in code would be a quoted literal. Config and env files have no quoting convention, so they keep the check.
CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".java", ".go", ".rb"}
IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[\w$]+)*$")

# names that describe a credential rather than hold one: API_KEY_HEADER = "X-API-Key", api_key_label=..., key_prefix
METADATA_NAME = re.compile(r"(?i)(?:_|-)(?:header|label|prefix|name|field|column|id|url|path|file|env|var)$")
CODE_EXPRESSION = re.compile(r"^[\w.]+[(\[]|^\{")  # a call, subscript or f-string field, not a literal
# dependency version ranges ("js-tokens": "^4.0.0" in package-lock.json)
VERSION_RANGE = re.compile(r"^[~^<>=v]*\d+(?:\.[\dx*]+){0,3}(?:-[\w.]+)?$")


def looks_like_secret(value: str) -> bool:
    """A literal value with some entropy: digits, mixed case, symbols, or long. Plain words and code are not."""
    value = value.strip("\"'`")
    if PLACEHOLDER.match(value) or CODE_EXPRESSION.match(value) or VERSION_RANGE.match(value):
        return False
    has_digit = any(c.isdigit() for c in value)
    mixed_case = any(c.islower() for c in value) and any(c.isupper() for c in value)
    has_symbol = any(not c.isalnum() and c not in "_-." for c in value)
    return has_digit or mixed_case or has_symbol or len(value) >= 16


TEXT_SUFFIXES_SKIP = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".parquet", ".duckdb"}


# ------------------------------------------------------------------------------------------ .gitignore
@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negate: bool
    dir_only: bool
    anchored: bool

    def matches(self, rel: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        if self.anchored:
            return fnmatch.fnmatchcase(rel, self.pattern)
        return fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], self.pattern)


def load_ignore_rules(path: Path) -> list[IgnoreRule]:
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        line = line.lstrip("!")
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        rules.append(IgnoreRule(line.lstrip("/"), negate, dir_only, anchored))
    return rules


def is_ignored(rel: str, is_dir: bool, rules: list[IgnoreRule]) -> bool:
    ignored = False
    for rule in rules:
        if rule.matches(rel, is_dir):
            ignored = not rule.negate
    return ignored


def tracked_candidates(root: Path = ROOT) -> Iterator[str]:
    rules = load_ignore_rules(root / ".gitignore")
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if base == "." else f"{base}/"
        dirnames[:] = sorted(d for d in dirnames if d not in ALWAYS_SKIPPED and not is_ignored(prefix + d, True, rules))
        for name in sorted(filenames):
            rel = prefix + name
            if not is_ignored(rel, False, rules):
                yield rel


# ------------------------------------------------------------------------------------------ checks
@dataclass
class Result:
    name: str
    ok: bool
    summary: str
    details: list[str]


def check_layout(files: list[str]) -> Result:
    bad = [
        f
        for f in files
        if ("/" in f and f.split("/", 1)[0] not in ALLOWED_DIRS) or ("/" not in f and f not in ALLOWED_ROOT_FILES)
    ]
    return Result("layout", not bad, f"{len(files)} files, {len(bad)} outside the allowed set", bad)


def _read_text(path: Path) -> str | None:
    if path.suffix in TEXT_SUFFIXES_SKIP:
        return None
    try:
        data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    except (OSError, gzip.BadGzipFile):
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_secrets(rel: str, text: str) -> list[str]:
    found = []
    in_code = Path(rel).suffix in CODE_SUFFIXES
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in SECRET_PATTERNS.items():
            for m in pattern.finditer(line):
                value = m.groupdict().get("value")
                if value is not None and not looks_like_secret(value):
                    continue
                if METADATA_NAME.search(m.groupdict().get("name") or ""):
                    continue
                if in_code and value is not None and not m.groupdict().get("quote") and IDENTIFIER.match(value):
                    continue
                found.append(f"{rel}:{lineno}: {label}")
    return found


def check_secrets(files: list[str]) -> Result:
    problems = [
        f"{f}: .env file must not be committed"
        for f in files
        if re.fullmatch(r"(?:.*/)?\.env(?:\.(?!example$)[\w.-]+)?", f)
    ]
    for rel in files:
        text = _read_text(ROOT / rel)
        if text is not None:
            problems.extend(scan_secrets(rel, text))
    return Result("secrets", not problems, f"{len(files)} files scanned, {len(problems)} findings", problems)


def _run(name: str, cmd: list[str], cwd: Path, ok_summary: str, parse: Callable[[str], str] | None = None) -> Result:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Result(name, False, f"could not run: {exc}", [])
    output = (proc.stdout + proc.stderr).strip()
    lines = [line for line in output.splitlines() if line.strip()]
    if proc.returncode == 0:
        return Result(name, True, parse(output) if parse else ok_summary, [])
    return Result(name, False, lines[-1] if lines else f"exit code {proc.returncode}", lines[-15:])


def check_alembic() -> Result:
    return _run(
        "alembic", [sys.executable, "-m", "alembic", "check"], BACKEND, "no drift between models and migrations"
    )


def check_architecture() -> Result:
    return _run(
        "architecture",
        [sys.executable, str(ROOT / "tools" / "architecture_check.py"), "--root", str(ROOT)],
        ROOT,
        "ARCH001-ARCH005 pass; ARCH006 deferred",
    )


def check_openapi_contract() -> Result:
    return _run(
        "openapi",
        [sys.executable, str(ROOT / "tools" / "openapi_contract.py"), "check"],
        ROOT,
        "stable operation IDs; backend/openapi.json current",
    )


def check_ruff() -> Result:
    targets = ["backend", "ml", "tools"]
    lint = _run("ruff", [sys.executable, "-m", "ruff", "check", *targets], ROOT, "")
    if not lint.ok:
        lint.summary = f"ruff check: {lint.summary}"
        return lint
    fmt = _run(
        "ruff",
        [sys.executable, "-m", "ruff", "format", "--check", *targets],
        ROOT,
        "",
        parse=lambda out: out.splitlines()[-1],
    )
    if not fmt.ok:
        fmt.summary = f"ruff format: {fmt.summary}"
        return fmt
    return Result("ruff", True, f"lint clean; format: {fmt.summary}", [])


def check_pytest() -> Result:
    def summary(out: str) -> str:
        m = re.search(r"\d+ passed.*", out)
        return m.group(0) if m else "passed"

    return _run("pytest", [sys.executable, "-m", "pytest"], BACKEND, "passed", parse=summary)


# every APIRoute of the app, with the auth role its dependency tree requires (None = no auth dependency)
_AUTH_SCRIPT = """
import json
from fastapi.routing import APIRoute
from app.main import app

def auth_roles(dependencies):
    for dep in dependencies:
        role = getattr(dep.call, "__hqai_auth__", None)
        if role:
            yield role
        yield from auth_roles(dep.dependencies)

def walk(routes, prefix="", inherited=()):
    for route in routes:
        if isinstance(route, APIRoute):
            roles = list(inherited) + list(auth_roles(route.dependant.dependencies))
            yield {"path": prefix + route.path, "methods": sorted(route.methods), "roles": roles}
        elif hasattr(route, "original_router"):  # router included with app.include_router
            ctx = route.include_context
            extra = [getattr(d.dependency, "__hqai_auth__", None) for d in (ctx.dependencies or [])]
            roles = [*inherited, *filter(None, extra)]
            yield from walk(route.original_router.routes, prefix + (ctx.prefix or ""), roles)
        elif hasattr(route, "routes"):
            yield from walk(route.routes, prefix + getattr(route, "path", ""), inherited)

print(json.dumps(list(walk(app.routes))))
"""
AUTH_EXEMPT = {"/health", "/api/v1/health"}


def check_api_auth() -> Result:
    proc = subprocess.run([sys.executable, "-c", _AUTH_SCRIPT], cwd=BACKEND, capture_output=True, text=True)
    if proc.returncode != 0:
        return Result("api-auth", False, "could not import the app", proc.stderr.strip().splitlines()[-5:])
    routes = json.loads(proc.stdout)
    missing = [
        f"{','.join(r['methods'])} {r['path']}: no auth dependency"
        for r in routes
        if r["path"] not in AUTH_EXEMPT and not r["roles"]
    ]
    protected = sum(1 for r in routes if r["roles"])
    summary = f"{len(routes)} routes: {protected} with auth, {len(routes) - protected - len(missing)} exempt (health)"
    return Result("api-auth", not missing, summary if not missing else f"{len(missing)} routes without auth", missing)


def check_frontend() -> list[Result]:
    """Frontend lint and production build; skipped (not listed) while frontend/ has no package.json."""
    if not (FRONTEND / "package.json").exists():
        return []
    npm = shutil.which("npm")
    if npm is None:
        return [
            Result(name, False, "npm not found (install Node.js >= 22.18.0)", [])
            for name in ("web-contract", "web-lint", "web-build")
        ]
    if not (FRONTEND / "node_modules").is_dir():
        return [
            Result(name, False, "frontend/node_modules missing: run `make web-install`", [])
            for name in ("web-contract", "web-lint", "web-build")
        ]

    def build_summary(out: str) -> str:
        m = re.search(r"built in [\d.]+\s*m?s", out)
        return f"tsc + vite {m.group(0)}" if m else "tsc + vite build ok"

    results = [
        _run(
            "web-contract",
            [npm, "run", "--silent", "api:check"],
            FRONTEND,
            "generated TypeScript transport types current",
        ),
        _run("web-lint", [npm, "run", "--silent", "lint"], FRONTEND, "eslint + prettier clean"),
        _run("web-build", [npm, "run", "--silent", "build"], FRONTEND, "", parse=build_summary),
    ]
    results.append(check_web_bundle())
    return results


def check_web_bundle() -> Result:
    """No secret may be compiled into the bundle the browser downloads (the proxy adds the API key server-side)."""
    dist = FRONTEND / "dist"
    if not dist.is_dir():
        return Result("web-bundle", False, "frontend/dist missing: run `make web-build`", [])
    findings: list[str] = []
    files = 0
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        files += 1
        findings.extend(scan_secrets(path.relative_to(ROOT).as_posix(), text))
    return Result("web-bundle", not findings, f"{files} built files scanned, {len(findings)} findings", findings)


# the OpenAPI schema lists every public route (the prefix-less liveness probe is excluded from it)
_ROUTES_SCRIPT = """
import json
from app.core.config import get_settings
from app.main import app
prefix = get_settings().api_prefix
print(json.dumps(sorted(f"{method.upper()} {path[len(prefix):]}" for path, ops in app.openapi()["paths"].items()
                        if path.startswith(prefix + "/") for method in ops)))
"""


def _normalise(endpoint: str) -> str:
    method, path = endpoint.split(" ", 1)
    path = re.sub(r"\{[^}]*\}", "{}", path.split("?", 1)[0])
    return f"{method} {path}"


def check_api_docs() -> Result:
    doc = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    documented = {
        _normalise(m.group(1)) for m in re.finditer(r"^### `((?:GET|POST|PUT|PATCH|DELETE) /[^`]*)`", doc, re.M)
    }
    proc = subprocess.run([sys.executable, "-c", _ROUTES_SCRIPT], cwd=BACKEND, capture_output=True, text=True)
    if proc.returncode != 0:
        return Result("api-docs", False, "could not import the app", proc.stderr.strip().splitlines()[-5:])
    exposed = {_normalise(e) for e in json.loads(proc.stdout)}
    details = [f"documented, not exposed: {e}" for e in sorted(documented - exposed)]
    details += [f"exposed, not documented: {e}" for e in sorted(exposed - documented)]
    return Result(
        "api-docs",
        not details,
        f"{len(exposed)} routes, {len(documented)} documented, {len(details)} mismatches",
        details,
    )


def main() -> int:
    files = list(tracked_candidates())
    results = [
        check_layout(files),
        check_secrets(files),
        check_architecture(),
        check_openapi_contract(),
        check_alembic(),
        check_ruff(),
        check_pytest(),
        check_api_docs(),
        check_api_auth(),
        *check_frontend(),
    ]
    width = max(len(r.name) for r in results)
    print(f"{'check':<{width}}  status  summary")
    print(f"{'-' * width}  ------  {'-' * 60}")
    for r in results:
        print(f"{r.name:<{width}}  {'PASS' if r.ok else 'FAIL':<6}  {r.summary}")
    failed = [r for r in results if not r.ok]
    for r in failed:
        if r.details:
            print(f"\n{r.name}:")
            for line in r.details[:30]:
                print(f"  {line}")
            if len(r.details) > 30:
                print(f"  … {len(r.details) - 30} more")
    print(f"\n{'FAILED: ' + ', '.join(r.name for r in failed) if failed else 'all checks passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
