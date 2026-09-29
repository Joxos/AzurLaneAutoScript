import { describe, expect, it } from "vitest";

import { cellWidth, pinCells } from "./cells";

describe("cellWidth", () => {
  it("reads the widths rich laid the log out with", () => {
    expect(cellWidth("M".codePointAt(0)!)).toBe(1);
    expect(cellWidth("│".codePointAt(0)!)).toBe(1); // box drawing
    expect(cellWidth("─".codePointAt(0)!)).toBe(1);
    expect(cellWidth("中".codePointAt(0)!)).toBe(2);
    expect(cellWidth("：".codePointAt(0)!)).toBe(2); // fullwidth colon
    expect(cellWidth("　".codePointAt(0)!)).toBe(2); // ideographic space
    expect(cellWidth("ア".codePointAt(0)!)).toBe(2); // katakana
    expect(cellWidth("가".codePointAt(0)!)).toBe(2); // hangul
    expect(cellWidth("".codePointAt(0)!)).toBe(0); // zero-width space
    expect(cellWidth("﻿".codePointAt(0)!)).toBe(0); // BOM
  });

  it("treats symbols rich counts as one cell as one cell", () => {
    // Measured in the browser at 1.1-2.5 cells (Segoe UI Symbol/Emoji
    // fallback); the *target* is still 1, which is what the pin enforces.
    for (const ch of ["✔", "✖", "⚠", "→", "·"]) {
      expect(cellWidth(ch.codePointAt(0)!)).toBe(1);
    }
  });
});

describe("pinCells", () => {
  it("pins wide characters inside already-escaped text", () => {
    // pinCells runs on the escaped text (see ansiToHtml), so it must not
    // touch the entities and must still pin the wide characters next to them.
    expect(pinCells("a&lt;b中")).toBe('a&lt;b<span class="cell-pin" style="width:2ch">中</span>');
  });

  it("merges a run of wide characters into a single box", () => {
    expect(pinCells("计算失败")).toBe('<span class="cell-pin" style="width:8ch">计算失败</span>');
  });

  it("keeps the accumulated width of mixed runs", () => {
    expect(pinCells("错误1")).toBe('<span class="cell-pin" style="width:4ch">错误</span>1');
  });

  it("passes pure-Latin text through untouched", () => {
    expect(pinCells("Traceback (most recent call last)")).toBe("Traceback (most recent call last)");
  });
});
