"""Render representative log output through the WebUI renderer, for the
log-alignment gate (dev_tools/verify_log_align.mjs).

The sample deliberately mixes what the real log mixes: rich boxes (traceback,
panel, table, rules) and plain lines, each with and without CJK and with
symbol glyphs, because those are the three ways the cell grid can drift.

Usage: python dev_tools/gen_log_sample.py <output-dir> [width]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

from module.logger import WEB_THEME

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def build() -> list:
    """Renderables in the shapes the bot actually logs."""
    out = []

    # 1. Traceback: a box full of CJK inside the source line and the message.
    def inner(a, b):
        total = a + b
        raise ValueError(f"计算失败：{total} 不在允许区间内，请检查配置 Alas.Emulator.Serial")

    def outer():
        try:
            inner(1, 2)
        except ValueError as e:
            raise RuntimeError("任务启动失败，模拟器无响应") from e

    try:
        outer()
    except Exception:
        out.append(Traceback(show_locals=True))

    # 2. A bare error line: no box characters at all. This is the case the old
    #    box-drawing gate skipped, and the one that made the log look ragged.
    out.append(Text("Error: 委托列表为空，请检查 MomoShipyard.Fleet1 配置"))

    # 3. Symbol glyphs: rich lays them out as 1 cell, the browser draws them
    #    1.1-2.5 cells wide (Segoe UI Symbol / Emoji fallback).
    out.append(Text("状态 ✔ 完成 ✖ 失败 ⚠ 警告 → 下一步"))

    # 4. Panel (the classic "error box").
    out.append(
        Panel(
            Text.from_markup(
                "[red]Error[/red] 设备连接失败：127.0.0.1:16384 refused\n"
                "retry 3/3 after 5s；如仍失败请检查模拟器是否已启动"
            ),
            title="[red]ALAS Error[/red]",
            border_style="red",
        )
    )

    # 5. Table (box drawing + column padding + CJK headers).
    table = Table(title="任务调度")
    table.add_column("任务")
    table.add_column("状态")
    table.add_column("下次运行")
    table.add_row("MomoShipyard", "[red]失败[/red]", "2026-09-29 03:10:00")
    table.add_row("Freebies", "[green]完成[/green]", "2026-09-29 04:00:00")
    out.append(table)

    # 6. Rules (the hr() separators the logger prints around every phase).
    out.append(Rule("[bold cyan]启动任务[/]", style="cyan"))
    out.append(Rule("="))

    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    # The WebUI render console is a captured (non-tty) Console, so rich falls
    # back to 80 columns; keep the sample on the same grid.
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 80

    console = Console(
        theme=WEB_THEME,
        no_color=False,
        color_system="standard",
        force_terminal=True,
        width=width,
    )
    chunks = []
    for renderable in build():
        with console.capture() as capture:
            console.print(renderable)
        chunks.append(capture.get())
    text = "".join(chunks)

    (out_dir / "sample.ans").write_text(text, encoding="utf-8")
    (out_dir / "truth.json").write_text(
        json.dumps(
            [
                {"cells": cell_len(ANSI_RE.sub("", line))}
                for line in text.split("\n")
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"sample: {len(text.splitlines())} lines at width {width} -> {out_dir}")
    return 0


if __name__ == "__main__":
    from rich.cells import cell_len

    raise SystemExit(main())
