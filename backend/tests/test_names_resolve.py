"""Nothing the code reads from another module has been deleted or renamed.

A name removed from one package and still read in another breaks only when that path runs, and a path no test drives breaks in front of a user.
So: every module under `app` imports; every name any Python file in the repo imports (`from app.x import name`) exists; and every attribute read
through an imported module (`import app.x as m` or `from app import x as m`, then `m.NAME`) exists. Static, over the whole repo, no model call."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pkgutil
import warnings
from pathlib import Path

import pytest

import app

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TREES = [BACKEND / "app", BACKEND / "tests", ROOT / "evals", ROOT / "watcher"]
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", "recordings", "fixtures"}


def _files():
    for tree in TREES:
        if tree.exists():
            for p in sorted(tree.rglob("*.py")):
                if not SKIP_DIRS & set(p.parts):
                    yield p


def _package_of(path: Path) -> str | None:
    """The dotted package a file lives in, if it sits under a directory the interpreter can import from."""
    for base in (BACKEND, ROOT):
        try:
            rel = path.relative_to(base).with_suffix("")
        except ValueError:
            continue
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            return ".".join(parts[:-1])
        return ".".join(parts[:-1])
    return None


def _import(name: str):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return importlib.import_module(name)
    except ImportError:
        return None


def test_every_module_under_app_imports():
    failures = []
    for m in pkgutil.walk_packages(app.__path__, "app."):
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{m.name}: {type(e).__name__}: {e}")
    assert not failures, "\n".join(failures)


def test_every_imported_name_and_every_module_attribute_read_exists():
    missing = []
    for path in _files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        pkg = _package_of(path)
        aliases: dict[str, object] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = ("." * node.level) + (node.module or "")
                try:
                    modname = importlib.util.resolve_name(base, pkg) if node.level else node.module
                except (ImportError, ValueError, TypeError):
                    continue
                if not modname or not (modname == "app" or modname.startswith("app.") or modname.split(".")[0] in ("evals", "watcher")):
                    continue
                if _import(modname.split(".")[0]) is None:      # evals and watcher are importable only from the repo root; the root run checks them
                    continue
                mod = _import(modname)
                if mod is None:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}: cannot import {modname}")
                    continue
                for a in node.names:
                    if a.name == "*":
                        continue
                    sub = _import(f"{modname}.{a.name}")
                    if not hasattr(mod, a.name) and sub is None:
                        missing.append(f"{path.relative_to(ROOT)}:{node.lineno}: {modname} has no {a.name}")
                    elif sub is not None and not hasattr(mod, a.name):
                        aliases[a.asname or a.name] = sub
                    elif sub is not None:
                        aliases[a.asname or a.name] = sub
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname and (a.name.startswith("app.") or a.name.split(".")[0] in ("evals", "watcher")):
                        mod = _import(a.name)
                        if mod is not None:
                            aliases[a.asname] = mod
        guarded = {(c.args[0].id, c.args[1].value) for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "hasattr"
                   and len(c.args) == 2 and isinstance(c.args[0], ast.Name) and isinstance(c.args[1], ast.Constant)}      # an attribute the code itself checks for is optional
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases and (node.value.id, node.attr) not in guarded:
                target = aliases[node.value.id]
                if not hasattr(target, node.attr) and _import(f"{target.__name__}.{node.attr}") is None:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}: {target.__name__} has no {node.attr}")
    assert not missing, "\n".join(sorted(set(missing)))
