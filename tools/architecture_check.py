#!/usr/bin/env python3
"""Repository-specific architecture boundary checks.

The checker parses Python source with :mod:`ast`, so comments, docstrings and ordinary string
literals are not treated as imports. It enforces only boundaries that are valid for the current
repository; future ``app/domain`` and ``app/application`` rules activate automatically if those
directories are introduced.

Enforced rules:
  ARCH001  backend runtime must not import the ML implementation
  ARCH002  ML production code must not import backend implementation
  ARCH003  future domain code must not import framework/outward implementation
  ARCH004  future application code must not import HTTP/concrete infrastructure/ML implementation
  ARCH005  API adapters must not construct executable raw SQL

ARCH006 (Alembic migration authority) is documented but deferred: current ML ingestion legitimately
creates ephemeral DuckDB tables, and a static repository-wide DDL scan cannot reliably distinguish
those from PostgreSQL schema mutation without connection/data-flow analysis.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    rule: str
    file: str
    line: int | None
    problem: str
    remediation: str

    def format(self) -> str:
        location = f"{self.file}:{self.line}" if self.line is not None else self.file
        return f"{self.rule} {location}: {self.problem}. Remediation: {self.remediation}"


@dataclass(frozen=True)
class ImportRule:
    rule: str
    source: str
    forbidden: tuple[str, ...]
    problem: str
    remediation: str


ML_IMPLEMENTATION = ("hqai_ml", "ml.hqai_ml", "ml.pipelines")
BACKEND_IMPLEMENTATION = ("app", "backend.app")
DOMAIN_OUTWARD = (
    "fastapi",
    "sqlalchemy",
    "psycopg",
    *ML_IMPLEMENTATION,
    "app.api",
    "app.application",
    "app.core",
    "app.db",
    "app.infrastructure",
    "app.main",
    "app.schemas",
    "app.services",
    "backend.app.api",
    "backend.app.application",
    "backend.app.core",
    "backend.app.db",
    "backend.app.infrastructure",
    "backend.app.main",
    "backend.app.schemas",
    "backend.app.services",
)
APPLICATION_OUTWARD = (
    "fastapi",
    "sqlalchemy",
    "psycopg",
    *ML_IMPLEMENTATION,
    "app.api",
    "app.core",
    "app.db",
    "app.infrastructure",
    "app.main",
    "app.schemas",
    "app.services",
    "backend.app.api",
    "backend.app.core",
    "backend.app.db",
    "backend.app.infrastructure",
    "backend.app.main",
    "backend.app.schemas",
    "backend.app.services",
)

IMPORT_RULES = (
    ImportRule(
        "ARCH001",
        "backend/app",
        ML_IMPLEMENTATION,
        "backend runtime must not import ML implementation",
        "consume persisted predictions, registry metadata or serving tables instead",
    ),
    ImportRule(
        "ARCH002",
        "ml/hqai_ml",
        BACKEND_IMPLEMENTATION,
        "ML production code must not import backend implementation",
        "use documented data/database contracts instead of backend Python code",
    ),
    ImportRule(
        "ARCH002",
        "ml/pipelines",
        BACKEND_IMPLEMENTATION,
        "ML production code must not import backend implementation",
        "use documented data/database contracts instead of backend Python code",
    ),
    ImportRule(
        "ARCH003",
        "backend/app/domain",
        DOMAIN_OUTWARD,
        "domain code must not import framework or outward implementation",
        "depend only on domain-owned abstractions and framework-independent values",
    ),
    ImportRule(
        "ARCH004",
        "backend/app/application",
        APPLICATION_OUTWARD,
        "application code must not import HTTP, concrete infrastructure or ML implementation",
        "depend on domain code and application-owned ports; wire adapters at the composition root",
    ),
)

_SQL_START = re.compile(r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|CREATE|ALTER|DROP|TRUNCATE)\b", re.I)


def _is_prefix(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


def _python_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _package_parts(root: Path, path: Path) -> tuple[list[str], bool]:
    """Return import-package parts and whether *path* is a package ``__init__.py``."""
    for base in (root / "backend", root / "ml"):
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        parts = list(relative.with_suffix("").parts)
        is_package = bool(parts and parts[-1] == "__init__")
        if is_package:
            parts.pop()
        return parts, is_package
    return [path.stem], path.name == "__init__.py"


def _resolve_from(root: Path, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    module_parts, is_package = _package_parts(root, path)
    package = module_parts if is_package else module_parts[:-1]
    keep = max(0, len(package) - (node.level - 1))
    resolved = package[:keep]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _imports(root: Path, path: Path, tree: ast.AST) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from(root, path, node)
            for alias in node.names:
                name = module if alias.name == "*" else ".".join(filter(None, (module, alias.name)))
                imports.append((name, node.lineno))
    return imports


def _parse(root: Path, path: Path) -> tuple[ast.AST | None, Violation | None]:
    relative = path.relative_to(root).as_posix()
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative), None
    except (OSError, UnicodeError, SyntaxError) as exc:
        line = exc.lineno if isinstance(exc, SyntaxError) else None
        return None, Violation(
            "ARCH000",
            relative,
            line,
            f"could not parse Python source: {exc}",
            "fix the source so architecture dependencies can be inspected",
        )


def _check_import_rule(root: Path, rule: ImportRule) -> list[Violation]:
    violations: list[Violation] = []
    for path in _python_files(root / rule.source):
        tree, parse_error = _parse(root, path)
        if parse_error:
            violations.append(parse_error)
            continue
        assert tree is not None
        for imported, line in _imports(root, path, tree):
            forbidden = next((prefix for prefix in rule.forbidden if _is_prefix(imported, prefix)), None)
            if forbidden:
                violations.append(
                    Violation(
                        rule.rule,
                        path.relative_to(root).as_posix(),
                        line,
                        f"{rule.problem}: {imported}",
                        rule.remediation,
                    )
                )
    return violations


def _sqlalchemy_text_names(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    direct: set[str] = set()
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"sqlalchemy", "sqlalchemy.sql"}:
            direct.update(alias.asname or alias.name for alias in node.names if alias.name == "text")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"sqlalchemy", "sqlalchemy.sql"}:
                    modules[alias.asname or alias.name.split(".")[0]] = alias.name
    return direct, modules


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "{}"
            for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_text(node.left), _literal_text(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _is_sqlalchemy_text_call(call: ast.Call, direct: set[str], modules: dict[str, str]) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id in direct
    if (
        not isinstance(call.func, ast.Attribute)
        or call.func.attr != "text"
        or not isinstance(call.func.value, ast.Name)
    ):
        return False
    return modules.get(call.func.value.id) in {"sqlalchemy", "sqlalchemy.sql"}


def _check_api_raw_sql(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in _python_files(root / "backend/app/api"):
        tree, parse_error = _parse(root, path)
        if parse_error:
            violations.append(parse_error)
            continue
        assert tree is not None
        direct, modules = _sqlalchemy_text_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            problem: str | None = None
            if _is_sqlalchemy_text_call(node, direct, modules):
                problem = "API adapter constructs raw SQL with sqlalchemy.text"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany"} and node.args:
                sql = _literal_text(node.args[0])
                match = _SQL_START.match(sql) if sql is not None else None
                if match:
                    keyword = match.group(0).strip().split()[0].upper()
                    problem = f"API adapter passes a raw {keyword} statement to {node.func.attr}()"
            if problem:
                violations.append(
                    Violation(
                        "ARCH005",
                        path.relative_to(root).as_posix(),
                        node.lineno,
                        problem,
                        "move persistence/query logic behind a service or infrastructure adapter",
                    )
                )
    return violations


def check_repository(root: Path) -> list[Violation]:
    root = root.resolve()
    violations = [violation for rule in IMPORT_RULES for violation in _check_import_rule(root, rule)]
    violations.extend(_check_api_raw_sql(root))
    return sorted(violations, key=lambda item: (item.file, item.line or 0, item.rule, item.problem))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    args = parser.parse_args(argv)
    violations = check_repository(args.root)
    if violations:
        print(f"architecture boundaries: FAIL ({len(violations)} violation(s))")
        for violation in violations:
            print(violation.format())
        return 1
    print("architecture boundaries: PASS (ARCH001-ARCH005 enforced; ARCH006 deferred)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
