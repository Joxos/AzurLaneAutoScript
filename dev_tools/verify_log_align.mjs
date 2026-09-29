/**
 * Log cell-grid gate.
 *
 * Renders a real rich log sample through the real frontend pipeline
 * (webapp/src/lib/ansi.ts + cells.ts) inside a replica of the log container,
 * measures every line in headless Edge, and compares it with the cell count
 * rich laid it out with. A line drifts when the browser draws the line
 * narrower or wider than `cells * cellWidth` - which is exactly the "right
 * edge of the error box does not line up" bug.
 *
 * Also checks that pinning does not change the row height (a boxed glyph that
 * grows the line box would make the whole log jitter while streaming).
 *
 * Usage:  node dev_tools/verify_log_align.mjs [--edge <path>] [--keep]
 * Gate:   exits non-zero when the worst drift exceeds 1px.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");
// The app sources are TypeScript with extensionless imports; bundle them with
// the app's own toolchain so the gate exercises the shipped code, not a copy.
const webappRequire = createRequire(join(repo, "webapp", "package.json"));
const vite = await import(pathToFileURL(webappRequire.resolve("vite")).href);

const args = process.argv.slice(2);
const keep = args.includes("--keep");
const edgeArg = args.indexOf("--edge");
const EDGE_CANDIDATES = [
  ...(edgeArg >= 0 ? [args[edgeArg + 1]] : []),
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/microsoft-edge",
  "/usr/bin/google-chrome",
];
const TOLERANCE_PX = 1.0;

const edge = EDGE_CANDIDATES.find((p) => p && existsSync(p));
if (!edge) {
  console.error("no Chromium browser found; pass --edge <path>");
  process.exit(2);
}

const work = mkdtempSync(join(tmpdir(), "alas-logalign-"));
const python = join(repo, ".venv", "Scripts", "python.exe");
const pythonCmd = existsSync(python) ? python : "python3";

try {
  execFileSync(pythonCmd, [join(repo, "dev_tools", "gen_log_sample.py"), work], {
    cwd: repo,
    stdio: "inherit",
  });

  const sample = readFileSync(join(work, "sample.ans"), "utf8");
  const truth = JSON.parse(readFileSync(join(work, "truth.json"), "utf8"));
  const lines = sample.split("\n").map((l) => l.replace(/\x1b\[[0-9;]*m/g, ""));
  const baseCss = readFileSync(join(repo, "webapp/src/styles/base.css"), "utf8");

  const built = await vite.build({
    root: join(repo, "webapp"),
    logLevel: "error",
    build: {
      write: false,
      minify: false,
      lib: {
        entry: join(repo, "webapp/src/lib/ansi.ts"),
        name: "AlasLog",
        formats: ["iife"],
        fileName: () => "ansi.iife.js",
      },
    },
  });
  const chunks = Array.isArray(built) ? built[0].output : built.output;
  const code = chunks.find((c) => c.type === "chunk").code;

  const script = `
const R = document.getElementById('report');
try {
  const sample = JSON.parse(document.getElementById('sample').textContent);
  const lines = JSON.parse(document.getElementById('lines').textContent);
  const pre = document.querySelector('.alas-log');
  document.getElementById('code').innerHTML = AlasLog.ansiToHtml(sample, pre);
  const probe = document.createElement('pre');
  probe.className = 'alas-log';
  probe.style.cssText = 'position:absolute;visibility:hidden;left:-99999px;top:0;';
  document.body.appendChild(probe);
  const widths = lines.map((line) => {
    // Measure what the app actually renders, not the raw text: the pinner is
    // the thing under test.
    probe.innerHTML = line === '' ? ' ' : AlasLog.ansiToHtml(line, probe);
    return probe.getBoundingClientRect().width;
  });
  probe.textContent = 'M'.repeat(32);
  const cell = probe.getBoundingClientRect().width / 32;
  // Row height of a real rendered line vs a plain-Latin line.
  probe.textContent = 'plain ascii line';
  const latinRow = probe.getBoundingClientRect().height;
  probe.innerHTML = AlasLog.ansiToHtml('中文字符行 padded 中文', probe);
  const cjkRow = probe.getBoundingClientRect().height;
  R.textContent = JSON.stringify({ widths, cell, latinRow, cjkRow, pins: document.querySelectorAll('.cell-pin').length,
    debug: { len: lines.slice(0,3).map((l) => l.length), plain: lines.slice(0,3).map((l) => { probe.textContent = l; return +probe.getBoundingClientRect().width.toFixed(2); }),
      tail0: JSON.stringify(lines[0].slice(-6)) } });
} catch (e) { R.textContent = 'ERROR@' + (e && e.stack ? e.stack : e); }
`;

  // "<" is escaped so no payload can terminate the script element early.
  const asJson = (value) => JSON.stringify(value).replace(/</g, "\\u003c");
  const html = `<!doctype html>
<html data-theme="dark"><head><meta charset="utf-8"><style>
:root { --font-mono: Menlo, consolas, "DejaVu Sans Mono", "Courier New", monospace; --log-fg:#d4d9de; }
${baseCss}
pre { margin: 0; }
</style></head><body>
<pre class="alas-log" id="log"><code id="code"></code></pre>
<pre id="report"></pre>
<script>${code}</script>
<script type="application/json" id="sample">${asJson(sample)}</script>
<script type="application/json" id="lines">${asJson(lines)}</script>
<script type="application/json" id="truth">${asJson(truth)}</script>
<script>${script}</script>
</body></html>`;

  const page = join(work, "probe.html");
  writeFileSync(page, html, "utf8");

  const dom = execFileSync(
    edge,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      `--user-data-dir=${join(work, "profile")}`,
      "--virtual-time-budget=8000",
      "--window-size=1600,1200",
      "--dump-dom",
      `file:///${page.replace(/\\/g, "/")}`,
    ],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] },
  );

  const m = dom.match(/<pre id="report">([\s\S]*?)<\/pre>/);
  if (!m) throw new Error("browser produced no report");
  const raw = m[1]
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
  if (raw.startsWith("ERROR@")) throw new Error(raw);
  const data = JSON.parse(raw);

  const rows = lines.map((line, i) => ({
    i,
    cells: truth[i]?.cells ?? null,
    drift: truth[i] ? data.widths[i] - truth[i].cells * data.cell : null,
    text: line,
  }));
  const scored = rows.filter((r) => r.drift !== null && r.text.trim() !== "");
  const worst = scored.reduce((a, b) => (Math.abs(b.drift) > Math.abs(a.drift) ? b : a));
  const over = scored.filter((r) => Math.abs(r.drift) > TOLERANCE_PX);

  console.log(`cell width      : ${data.cell.toFixed(4)}px`);
  console.log(`lines measured  : ${scored.length}`);
  console.log(`worst drift     : ${worst.drift.toFixed(2)}px (line ${worst.i})`);
  console.log(`row height      : latin ${data.latinRow.toFixed(2)}px / cjk ${data.cjkRow.toFixed(2)}px`);
  console.log(`pin boxes       : ${data.pins}`);
  if (args.includes("--debug")) console.log(`debug           : ${JSON.stringify(data.debug)}`);
  for (const r of over.slice(0, 10)) {
    console.log(`  drift ${r.drift.toFixed(2).padStart(8)}px  [${r.i}] ${r.text.slice(0, 70)}`);
  }
  const rowShift = Math.abs(data.latinRow - data.cjkRow);
  if (rowShift > 0.5) console.log(`  row height shift: ${rowShift.toFixed(2)}px (pinning changed the line box)`);

  if (over.length) {
    console.error(`FAIL: ${over.length}/${scored.length} lines drift more than ${TOLERANCE_PX}px`);
    process.exitCode = 1;
  } else if (rowShift > 0.5) {
    console.error("FAIL: pinning changes the row height");
    process.exitCode = 1;
  } else {
    console.log("OK: every line lands on rich's cell grid");
  }
} finally {
  if (keep) console.log(`artifacts kept in ${work}`);
  else rmSync(work, { recursive: true, force: true });
}
