import { describe, expect, it } from "vitest";

import { ansiToHtml } from "./ansi";

describe("ansiToHtml", () => {
  it("returns plain text unchanged", () => {
    expect(ansiToHtml("hello world")).toBe("hello world");
  });

  it("escapes HTML before mapping SGR codes", () => {
    expect(ansiToHtml('<a> & "')).toBe('&lt;a&gt; &amp; "');
  });

  it("maps SGR colors to theme-aware spans and resets them", () => {
    expect(ansiToHtml("\x1b[31mred\x1b[0mplain")).toBe(
      '<span style="color:var(--ansi-red, #cd3131)">red</span>plain',
    );
  });

  it("combines multiple styles in one span", () => {
    expect(ansiToHtml("\x1b[1;31mbold red\x1b[0m")).toBe(
      '<span style="font-weight:700;color:var(--ansi-red, #cd3131)">bold red</span>',
    );
  });

  it("closes a pending span at end of input without a reset code", () => {
    expect(ansiToHtml("\x1b[32mgreen")).toBe(
      '<span style="color:var(--ansi-green, #0dbc79)">green</span>',
    );
  });

  it("drops unsupported codes", () => {
    expect(ansiToHtml("\x1b[99mX\x1b[0m")).toBe("X");
  });

  it("pins wide CJK characters into one box per run, on every line", () => {
    // Without a measurement host (unit tests) the pinner falls back to rich's
    // own table: 2-cell characters get a box, everything else is left to the
    // font. Runs share a box so a 12-character Chinese line costs one span.
    expect(ansiToHtml("运行 委托")).toBe(
      '<span class="cell-pin" style="width:4ch">运行</span> <span class="cell-pin" style="width:4ch">委托</span>',
    );
    expect(ansiToHtml("\x1b[31m完成\x1b[0m")).toBe(
      '<span style="color:var(--ansi-red, #cd3131)"><span class="cell-pin" style="width:4ch">完成</span></span>',
    );
  });

  it("never lets a pin box straddle an SGR boundary", () => {
    // The colour changes mid-run: each side gets its own box, and the
    // accumulated cell width resets with it.
    expect(ansiToHtml("\x1b[31m中\x1b[32m文\x1b[0m")).toBe(
      '<span style="color:var(--ansi-red, #cd3131)"><span class="cell-pin" style="width:2ch">中</span></span>' +
        '<span style="color:var(--ansi-green, #0dbc79)"><span class="cell-pin" style="width:2ch">文</span></span>',
    );
  });

  it("normalizes the CR that rich leaves at the end of every captured line", () => {
    // A captured terminal Console ends each line with ESC[0m + CR. Left in,
    // the browser's HTML parser turns it into a line break (a phantom blank
    // line after every log entry) and the pinner would give it a whole cell.
    expect(ansiToHtml("\x1b[31m错误\x1b[0m\r\n\x1b[32m下一行\x1b[0m\r")).toBe(
      '<span style="color:var(--ansi-red, #cd3131)"><span class="cell-pin" style="width:4ch">错误</span></span>\n' +
        '<span style="color:var(--ansi-green, #0dbc79)"><span class="cell-pin" style="width:6ch">下一行</span></span>',
    );
  });

  it("leaves zero-width and Latin characters unpinned", () => {
    expect(ansiToHtml("a 中 b")).toBe('a <span class="cell-pin" style="width:2ch">中</span> b');
    expect(ansiToHtml("|---|")).toBe("|---|");
  });
});
