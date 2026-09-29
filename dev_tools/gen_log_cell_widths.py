"""Generate `webapp/src/lib/cell-widths.json` from rich's own cell table.

The WebUI log is laid out by the backend: `module/webui/api/helpers.py::render_log`
prints rich renderables at a fixed width, so every border/column in the browser
must land on the cell grid *rich* assumed - not on whatever width the browser's
font fallback happens to give a glyph. This generator exports that same table
so the frontend pins each character into exactly the number of cells rich
counted for it (single source of truth, no hand-copied CJK ranges).

Run:  .venv\\Scripts\\python.exe dev_tools/gen_log_cell_widths.py
Gate: dev_tools/verify_log_cell_widths.py (regenerate -> git diff must be empty)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "webapp" / "src" / "lib" / "cell-widths.json"


def _ranges(widths: list[tuple[int, int, int]], width: int) -> list[list[int]]:
    """Collapse the table's (start, end, width) spans into width-`width` ranges."""
    out: list[list[int]] = []
    for start, end, w in widths:
        if w != width:
            continue
        if out and out[-1][1] + 1 >= start:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def build() -> dict:
    try:
        from rich._unicode_data import load as load_cell_table
    except ImportError:  # pragma: no cover - rich is a hard dependency
        raise SystemExit("rich is not importable; run inside the project venv") from None

    table = load_cell_table("auto")
    # rich decides control characters in code, not in its data table
    # (rich/cells.py::get_character_cell_size: `codepoint < 32 or
    # 0x7F <= codepoint < 0xA0 -> 0`). Mirror it here so the frontend stays a
    # pure table lookup and never pins a CR/LF into a phantom cell - the
    # rendered log is full of them (every line ends with ESC[0m + CR).
    control = [[0x00, 0x1F], [0x7F, 0x9F]]
    return {
        "unicodeVersion": table.unicode_version,
        # cell width 2 -> the browser must be forced into a 2-cell box
        "wide": _ranges(list(table.widths), 2),
        # cell width 0 -> control characters, combining marks, zero-width
        # joiners, BOM: rich does not advance the cursor, so neither may the
        # browser.
        "zero": _merge([*_ranges(list(table.widths), 0), *control]),
    }


def _merge(ranges: list[list[int]]) -> list[list[int]]:
    """Sort and coalesce overlapping/adjacent ranges."""
    out: list[list[int]] = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main() -> int:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = render(data)
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"drift: {OUT.relative_to(REPO_ROOT)} is stale, rerun gen_log_cell_widths.py")
            return 1
        print(f"ok: {OUT.relative_to(REPO_ROOT)} matches rich {data['unicodeVersion']}")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} (rich {data['unicodeVersion']})")
    print(f"  wide ranges: {len(data['wide'])}  zero ranges: {len(data['zero'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
