"""Collapse identical per-server asset values back to bare values (Phase 4B).

Our fork stores `Button(area=(...), color=(...), ...)` when all four servers
share the same value, and falls back to the per-server dict only when they
differ. Upstream writes the dict form everywhere, so every merge that takes an
`assets.py` from upstream silently undoes the de-duplication (smaller files,
same semantics).

Each `NAME = Button(...)` / `Template(...)` assignment is rebuilt from the AST
after collapsing the qualifying dicts, so the result is exactly our format and
nothing else in the file is touched. `dev_tools/verify_assets.py` proves the
rewrite is semantics-preserving: dump before and after must be identical.

Usage:
    .venv\\Scripts\\python.exe dev_tools/dedup_assets.py [--check] [path ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVERS = ("cn", "en", "jp", "tw")
FIELDS = ("area", "color", "button", "file")


def _collapse(node: ast.AST) -> ast.AST:
    """Replace per-server dicts whose four values are identical with the value."""
    for parent in ast.walk(node):
        for field, value in list(ast.iter_fields(parent)):
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        value[i] = _collapse(item)
            elif isinstance(value, ast.AST):
                setattr(parent, field, _collapse(value))

    if isinstance(node, ast.Call):
        for keyword in node.keywords:
            if keyword.arg not in FIELDS or keyword.value is None:
                continue
            dict_node = keyword.value
            if not isinstance(dict_node, ast.Dict):
                continue
            keys = [k.value for k in dict_node.keys if isinstance(k, ast.Constant)]
            if set(keys) != set(SERVERS):
                continue
            first = ast.dump(dict_node.values[0])
            if all(ast.dump(v) == first for v in dict_node.values[1:]):
                keyword.value = dict_node.values[0]
    return node


def dedup_source(text: str) -> str:
    tree = ast.parse(text)
    lines = text.split("\n")
    edits: list[tuple[int, int, str]] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id not in ("Button", "Template"):
            continue
        if not any(
            isinstance(keyword.value, ast.Dict)
            and {k.value for k in keyword.value.keys if isinstance(k, ast.Constant)} == set(SERVERS)
            and len({ast.dump(v) for v in keyword.value.values}) == 1
            for keyword in call.keywords
            if keyword.arg in FIELDS and keyword.value is not None
        ):
            continue
        assign = ast.Assign(targets=[target], value=_collapse(call))
        # ast.unparse reads `lineno` off the node it is given.
        ast.copy_location(assign, node)
        rebuilt = ast.unparse(assign)
        edits.append((node.lineno, node.end_lineno, rebuilt))

    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1 : end] = [replacement]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        paths = [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted(ROOT.glob("module/**/assets.py"))]

    changed: list[str] = []
    for rel in paths:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        new = dedup_source(text)
        if new == text:
            continue
        ast.parse(new)  # never write something that does not parse
        changed.append(rel)
        if not check:
            path.write_text(new, encoding="utf-8")

    if check:
        if changed:
            print(f"dedup: {len(changed)} file(s) still use the per-server dict form:")
            for rel in changed:
                print(f"  {rel}")
            return 1
        print("dedup: all asset bundles use the collapsed form")
        return 0

    print(f"dedup: collapsed per-server dicts in {len(changed)} file(s)")
    for rel in changed:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
