"""Find call sites where upstream changed a recognition argument and we did not.

The log-cell bug was one instance of a whole class: upstream's color_mask
refactor redefined what `threshold` means (a similarity floor became a
tolerance), so every call site left at the old number silently matches almost
anything. This gate compares our tree against upstream for the arguments that
carry recognition semantics, site by site, and prints the ones that drifted.

Matching is by (method, enclosing function, call ordinal inside that
function), which survives reformatting and our flow rewrites of the bodies.

Usage:
    .venv\\Scripts\\python.exe dev_tools/verify_thresholds.py [ref]
    (ref defaults to upstream/master; `--check` exits non-zero on drift)
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Method -> the keyword arguments that carry recognition semantics.
WATCHED: dict[str, tuple[str, ...]] = {
    "image_color_count": ("threshold", "count"),
    "image_color_button": ("color_threshold", "threshold", "encourage"),
    "match_template_color": ("threshold", "similarity", "offset"),
    "appear": ("threshold", "similarity", "offset", "interval"),
    "is_button_active": (),
    "wait_until_stable": ("timer", "timeout"),
    "ui_page_appear": (),
    "image_color_click": ("threshold",),
    "appear_then_click": ("threshold", "similarity", "offset"),
}


def _literal(node: ast.AST) -> str | None:
    try:
        return ast.unparse(node)
    except Exception:
        return None


def collect(tree: ast.AST) -> dict[tuple[str, int], tuple[str, dict[str, str]]]:
    """(method, ordinal within its function) -> (function, {arg: literal})."""
    out: dict[tuple[str, int], tuple[str, dict[str, str]]] = {}
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        ordinal: dict[str, int] = {}
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            if method not in WATCHED:
                continue
            args: dict[str, str] = {}
            for keyword in node.keywords:
                if keyword.arg in WATCHED[method]:
                    value = _literal(keyword.value)
                    if value is not None:
                        args[keyword.arg] = value
            if not args:
                continue
            index = ordinal.get(method, 0)
            ordinal[method] = index + 1
            out[(method, index)] = (func.name, args)
    return out


def sites(ref: str) -> dict[tuple[str, str, str, int], dict[str, str]]:
    """(file, method, function, ordinal) -> args, for one tree."""
    if ref == "HEAD":
        files = [p for p in sorted(ROOT.glob("module/**/*.py")) if "assets" not in p.name]
        read = lambda p: p.read_text(encoding="utf-8")  # noqa: E731
        names = lambda p: str(p.relative_to(ROOT)).replace("\\", "/")  # noqa: E731
    else:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", "module"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
        files = [n for n in listing if n.endswith(".py") and "assets" not in n]
        names = lambda n: n  # noqa: E731
        cache: dict[str, str] = {}

        def read(n: str) -> str:
            if n not in cache:
                cache[n] = subprocess.run(
                    ["git", "show", f"{ref}:{n}"], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout
            return cache[n]

    out: dict[tuple[str, str, str, int], dict[str, str]] = {}
    for entry in files:
        text = read(entry)
        if "<<<<<<<" in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for (method, index), (func, args) in collect(tree).items():
            out[(names(entry), method, func, index)] = args
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    ref = next((a for a in argv if not a.startswith("-")), "upstream/master")
    ours, theirs = sites("HEAD"), sites(ref)

    # Guard against a false green: a gate that compares nothing must not
    # report "no drift".
    comparable = set(ours) & set(theirs)
    if len(comparable) < 400:
        print(f"THRESHOLDS: only {len(comparable)} comparable sites - the matcher is broken, not the code")
        return 1

    drift: list[str] = []
    for key, args in sorted(ours.items()):
        file, method, func, index = key
        other = theirs.get(key)
        if other is None:
            continue  # we call it where upstream has no counterpart (new flow code)
        for name, value in args.items():
            theirs_value = other.get(name)
            if theirs_value is not None and theirs_value != value:
                drift.append(f"{file} {func}() #{index} {method}({name}=): ours {value} vs upstream {theirs_value}")

    print(f"compared {len(comparable)} sites against {ref}")
    for line in drift:
        print(f"  {line}")
    if drift:
        print(f"THRESHOLDS: {len(drift)} site(s) differ from {ref}")
        return 1 if check else 0
    print(f"THRESHOLDS: no drift against {ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
